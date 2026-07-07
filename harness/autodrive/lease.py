#!/usr/bin/env python3
"""Lease, heartbeat, and crash reaper for the parallel autodrive engine (SPEC §S6).

Thin logic module that `engine.py` (a CLI dispatcher near the STANDARDS
`max_file_lines: 400` cap) imports and delegates to. Two entry points:

    heartbeat(repo, session)
        Refresh the session's claim `heartbeat` + `lease_expiry` by the
        configured TTL, under the ledger state lock (S6.1).

    reap(repo)
        Reclaim every claim whose `lease_expiry < now` (S6.2), leaving claims
        still inside their lease untouched (S6.3 isolation — one live agent can
        never reap another). Death is confirmed with LAYERED detection (S6.4):
        primary is acquiring the per-task claim file's `flock(LOCK_EX|LOCK_NB)`
        (success ⇒ the owner process exited and the OS auto-released ⇒
        reclaimable); backstop is the claim's `pid`+`start_time` (guards PID
        reuse) plus heartbeat-mtime vs the lease. Fixed reclaim ORDER (S6.4/A7):
        confirm death → remove any stale `<worktree>/.git/index.lock` (ONLY
        after confirmation) → `git worktree remove --force` → prune →
        reset the task to `todo` if the worktree was clean, else move the branch
        to `quarantine/<id>-<sha>` and set the task `needs-human`.

Worktree teardown reuses `parallel.worktree_remove` (SPEC §S5); the claim
registry schema (`lease_expiry`/`heartbeat`/`pid`/`start_time`) is owned by
`ledger` and only read/refreshed here, never redefined. Stdlib only.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hooks"))
import engine  # noqa: E402
import ledger  # noqa: E402

_TS_FMT = "%Y-%m-%dT%H:%MZ"  # matches ledger.now_iso / claim_task exactly
_DEFAULT_TTL_MIN = 90
_DEFAULT_HEARTBEAT_MIN = 30  # matches harness-yaml.md parallel.heartbeat_minutes


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt(dt: datetime) -> str:
    return dt.strftime(_TS_FMT)


def _lease_ttl_minutes(repo: Path) -> int:
    """Lease TTL from `.harness.yaml parallel.lease_ttl_minutes` (default 90,
    matching ledger.claim_task's claim TTL)."""
    import parallel  # noqa: E402  (lazy — avoids any import-order surprise)
    v = parallel._harness_block(repo, "parallel").get("lease_ttl_minutes")
    return v if isinstance(v, int) and v > 0 else _DEFAULT_TTL_MIN


def _heartbeat_minutes(repo: Path) -> int:
    """Heartbeat cadence from `.harness.yaml parallel.heartbeat_minutes`
    (default 30 = `_DEFAULT_HEARTBEAT_MIN`), mirroring `_lease_ttl_minutes`."""
    import parallel  # noqa: E402
    v = parallel._harness_block(repo, "parallel").get("heartbeat_minutes")
    return v if isinstance(v, int) and v > 0 else _DEFAULT_HEARTBEAT_MIN


# --------------------------------------------------------------------------- #
# S6.1 — heartbeat
# --------------------------------------------------------------------------- #
def heartbeat(repo: Path, session: str) -> dict[str, Any]:
    """Refresh the session's claim `heartbeat` + `lease_expiry` by the configured
    TTL under the ledger state lock (S6.1). No live claim -> refreshed False."""
    ttl = _lease_ttl_minutes(repo)
    with ledger._state_lock(repo):
        st = ledger.load_state(repo)
        active = st.setdefault("active_tasks", {})
        entry = active.get(session)
        if not entry:
            return {"session": session, "refreshed": False,
                    "error": "no live claim for session"}
        now = _now()
        entry["heartbeat"] = _fmt(now)
        entry["lease_expiry"] = _fmt(now + timedelta(minutes=ttl))
        ledger.save_state(repo, st)
    return {"session": session, "refreshed": True, "task": entry.get("id"),
            "lease_expiry": entry["lease_expiry"]}


# --------------------------------------------------------------------------- #
# S6.4 — layered death detection
# --------------------------------------------------------------------------- #
def _flock_free(path: Path) -> bool:
    """True iff the claim file's exclusive flock is acquirable — i.e. no live
    process holds it, so the owner has exited (S6.4a). Absent file ⇒ free."""
    if not path.exists():
        return True
    fd = os.open(str(path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    except OSError:
        return False  # another process still holds the lock -> owner alive
    finally:
        os.close(fd)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    return True


def _proc_start(pid: int) -> Optional[str]:
    r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                       capture_output=True, text=True, check=False)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def _claim_pid(path: Path) -> Optional[int]:
    try:
        return int(path.read_text(encoding="utf-8").strip().splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None


def _heartbeat_stale(entry: dict[str, Any], ttl: int) -> bool:
    hb = entry.get("heartbeat")
    if not hb:
        return True
    return hb < _fmt(_now() - timedelta(minutes=ttl))


def _confirm_death(repo: Path, task: str, entry: dict[str, Any], ttl: int) -> bool:
    """Layered liveness check (S6.4): flock primary, then pid+start_time+heartbeat
    backstop. Caller has already gated on `lease_expiry < now` (S6.3)."""
    cf = ledger._claim_path(repo, task)
    if _flock_free(cf):
        return True
    pid = entry.get("pid") or _claim_pid(cf)
    if pid is not None:
        if not _pid_alive(pid):
            return True
        start = entry.get("start_time")
        if start and _proc_start(pid) != start:
            return True  # PID reused by a new, unrelated process
    return _heartbeat_stale(entry, ttl)


# --------------------------------------------------------------------------- #
# S6.2 / S6.4 — reclaim (fixed order A7)
# --------------------------------------------------------------------------- #
def _worktree_dir(repo: Path, task: str, entry: dict[str, Any]) -> Path:
    wt = entry.get("worktree")
    if wt:
        p = Path(wt)
        return p if p.is_absolute() else repo / wt
    return repo / ".worktrees" / task


def _remove_index_lock(wt_dir: Path) -> None:
    """Remove a stale `<worktree>/.git/index.lock` — ONLY after death is confirmed
    (S6.4/A7). A linked worktree's `.git` is a file, so also clear the resolved
    git dir's index.lock."""
    if not wt_dir.exists():
        return
    import parallel  # noqa: E402
    targets = [wt_dir / ".git" / "index.lock"]
    gd = parallel.git_dir(wt_dir)
    if gd:
        gp = Path(gd)
        targets.append((gp if gp.is_absolute() else wt_dir / gp) / "index.lock")
    for t in targets:
        with contextlib.suppress(OSError):
            t.unlink()


def _worktree_clean(wt_dir: Path) -> bool:
    """Clean-vs-dirty per `git status --porcelain` in the worktree (TASK-WORKTREE
    check, not a heuristic). Missing/unreadable worktree ⇒ nothing to preserve."""
    if not wt_dir.exists():
        return True
    r = ledger.git(wt_dir, "status", "--porcelain")
    if r.returncode != 0:
        return True
    return not r.stdout.strip()


def _short_sha(repo: Path, branch: str) -> str:
    r = ledger.git(repo, "rev-parse", "--short", branch)
    return r.stdout.strip() or "unknown" if r.returncode == 0 else "unknown"


def _reclaim(repo: Path, session: str, task: str, entry: dict[str, Any]) -> str:
    """Confirmed-dead claim: index.lock -> worktree remove/prune -> reset/quarantine
    -> drop claim entry+file (S6.2/S6.4). Returns the action taken."""
    import parallel  # noqa: E402
    wt_dir = _worktree_dir(repo, task, entry)
    branch = entry.get("branch") or f"task/{task}"
    clean = _worktree_clean(wt_dir)          # read BEFORE teardown
    _remove_index_lock(wt_dir)               # only after death confirmed (A7)
    parallel.worktree_remove(repo, task, force=True)  # remove --force + prune
    if clean:
        engine.set_task_state(repo, task, "todo")
        action = "todo"
    else:
        quarantine = f"quarantine/{task}-{_short_sha(repo, branch)}"
        ledger.git(repo, "branch", "-m", branch, quarantine)
        engine.set_task_state(repo, task, "needs-human")
        action = f"quarantine:{quarantine}"
    ledger.release_claim(repo, session)      # drop registry entry + claim file
    ledger.append_event(repo, task, "transition", f"reaped -> {action}")
    return action


def reap(repo: Path) -> dict[str, Any]:
    """Reclaim every claim past its lease whose owner is confirmed dead (S6.2/S6.4);
    leave claims still inside their lease untouched (S6.3 isolation)."""
    ttl = _lease_ttl_minutes(repo)
    now = ledger.now_iso()
    active = dict((ledger.load_state(repo).get("active_tasks") or {}))
    reaped: list[dict[str, Any]] = []
    skipped = 0
    for session, entry in active.items():
        exp = entry.get("lease_expiry")
        if exp and exp >= now:               # within lease -> never touched (S6.3)
            skipped += 1
            continue
        task = entry.get("id")
        if not task or not _confirm_death(repo, task, entry, ttl):
            skipped += 1
            continue
        reaped.append({"session": session, "task": task,
                       "action": _reclaim(repo, session, task, entry)})
    return {"reaped": reaped, "skipped_live": skipped}


# --------------------------------------------------------------------------- #
# S6.5 — process-lifetime claim holder (makes the flock primary real)
# --------------------------------------------------------------------------- #
def _watched_alive(pid: int, watch_parent: bool) -> bool:
    """True while the watched agent still lives. For the parent-default, a changed
    ppid means the parent died and we were reparented (init/launchd) -> dead."""
    if watch_parent and os.getppid() != pid:
        return False
    return _pid_alive(pid)


def hold_claim(repo: Path, session: str, task: str, watch_pid: Optional[int] = None,
               heartbeat_minutes: Optional[int] = None) -> int:
    """Long-lived holder (S6.5): acquire and HOLD `flock(LOCK_EX)` on the per-task
    claim file for the whole run; refresh heartbeat/lease every N minutes; exit
    (releasing the flock) on SIGTERM/SIGINT or when the watched pid dies."""
    cf = ledger._claim_path(repo, task)
    watch_parent = watch_pid is None
    if watch_pid is None:
        watch_pid = os.getppid()
    if isinstance(heartbeat_minutes, int) and heartbeat_minutes > 0:
        hb_min = heartbeat_minutes
    else:
        hb_min = _heartbeat_minutes(repo)
    cf.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(cf), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        print(json.dumps({"held": False, "task": task,
                          "error": "claim flock already held by another process"}))
        return 1
    # Stamp OUR pid into the flocked file so the S6.4(b) pid-backstop tracks the
    # holder (the per-task liveness proxy), staying consistent with the flock.
    payload = f"{os.getpid()}\n".encode("utf-8")
    os.ftruncate(fd, 0)
    os.pwrite(fd, payload, 0)
    stop = {"flag": False}

    def _shutdown(_signum, _frame):  # noqa: ANN001
        stop["flag"] = True
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    print(json.dumps({"held": True, "task": task, "session": session,
                      "watch_pid": watch_pid, "heartbeat_minutes": hb_min}), flush=True)
    try:
        heartbeat(repo, session)  # initial refresh under the ledger state lock
        interval = hb_min * 60
        last = time.monotonic()
        while not stop["flag"]:
            time.sleep(1.0)
            if stop["flag"] or not _watched_alive(watch_pid, watch_parent):
                break
            if time.monotonic() - last >= interval:
                heartbeat(repo, session)
                last = time.monotonic()
        return 0
    finally:
        os.close(fd)  # closing the fd releases the held flock


# --------------------------------------------------------------------------- #
# CLI handlers — thin (engine.py delegates here to stay under max_file_lines).
# --------------------------------------------------------------------------- #
def cmd_hold_claim(repo: Path, args) -> int:
    return hold_claim(repo, args.session, args.task,
                      watch_pid=args.watch_pid, heartbeat_minutes=args.heartbeat_minutes)
def cmd_heartbeat(repo: Path, args) -> int:
    res = heartbeat(repo, args.session)
    print(json.dumps(res))
    return 0 if res.get("refreshed") else 1


def cmd_reap(repo: Path, args) -> int:
    print(json.dumps(reap(repo)))
    return 0
