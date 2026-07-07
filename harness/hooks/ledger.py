#!/usr/bin/env python3
"""Shared ledger library for the Dynamic Traceback Harness.

State lives under <repo>/docs/: LEDGER.md (append-only forensic log, never
mutated) and LEDGER.state.json (resume anchor: lock, active task, frontier).
The hooks (scope_guard.py, ledger_commit.py) and the /autodrive loop share
this module so the on-disk grammar has exactly one implementation.
Stdlib only (Python 3.8+).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

STATE_FILE = "docs/LEDGER.state.json"
LOG_FILE = "docs/LEDGER.md"
LOCKS_DIR = "docs/.locks"
STATE_VERSION = 2

# Paths the scope guard always allows, regardless of the active task's scope[]
# — orchestration/bookkeeping, not implementation.
ALWAYS_ALLOWED = (
    "docs/",
    "reviews/",
    "STANDARDS.md",
    ".harness.yaml",
    ".claude/",
)

# Tool names whose writes the scope guard inspects.
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


# --- repo / path helpers ---
def find_repo_root(start: Optional[str] = None) -> Optional[Path]:
    """Walk up from `start` (or CLAUDE_PROJECT_DIR / cwd) to the nearest .git."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    base = Path(start or env or os.getcwd()).resolve()
    for d in (base, *base.parents):
        if (d / ".git").exists():
            return d
    return base if base.exists() else None


def to_repo_rel(path: str, repo_root: Path) -> Optional[str]:
    """Normalize an absolute-or-relative path to a repo-relative POSIX string."""
    if not path:
        return None
    p = Path(path)
    if not p.is_absolute():
        p = (repo_root / p)
    try:
        rel = p.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return None  # outside the repo entirely
    return rel.as_posix()


def _glob_to_re(pattern: str) -> "re.Pattern[str]":
    """POSIX-ish glob -> regex. '**' spans dirs, '*' within a segment, '?' one char."""
    i, n, out = 0, len(pattern), ["^"]
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                if i < n and pattern[i] == "/":
                    i += 1  # consume the slash after **
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def path_in_scope(rel_path: str, scope: list[str]) -> bool:
    for pat in scope or []:
        if _glob_to_re(pat).match(rel_path):
            return True
    return False


def is_always_allowed(rel_path: str) -> bool:
    return any(
        rel_path == a.rstrip("/") or rel_path.startswith(a)
        for a in ALWAYS_ALLOWED
    )


# --- state read / write ---
def _empty_state() -> dict[str, Any]:
    return {
        "version": STATE_VERSION,
        "lock": None,            # {"session": str, "expiry": iso8601}
        "active_task": None,     # DERIVED VIEW of active_tasks (see _derive_active_task)
        "active_tasks": {},      # registry keyed by session id (see claim_task)
        "frontier": {"active_batch": None, "last_event_ts": None},
    }


def _migrate_state(data: dict[str, Any]) -> dict[str, Any]:
    """Up-migrate v1->v2 in place: a v1 `active_task` -> one entry keyed by its session (else "legacy"); none -> empty (S1.1)."""
    if "active_tasks" not in data:
        registry: dict[str, Any] = {}
        at = data.get("active_task")
        if at:
            registry[at.get("session") or "legacy"] = at
        data["active_tasks"] = registry
    data["version"] = STATE_VERSION
    return data


def load_state(repo_root: Path) -> dict[str, Any]:
    f = repo_root / STATE_FILE
    if not f.exists():
        return _empty_state()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_state()
        return _migrate_state(data)
    except (json.JSONDecodeError, OSError):
        return _empty_state()


def save_state(repo_root: Path, state: dict[str, Any]) -> None:
    """Recompute derived `active_task` (sole entry iff one claim, else null; empty leaves it alone, S1.2), then write atomically (S2.1)."""
    active = state.get("active_tasks")
    if active:
        state["active_task"] = next(iter(active.values())) if len(active) == 1 else None
    f = repo_root / STATE_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, ensure_ascii=False) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(f.parent), prefix=".LEDGER.state.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, str(f))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


# --- active task (the "scope writer" the PreToolUse hook reads) ---
def set_active_task(repo_root: Path, task_id: str, batch: str, state_name: str,
                    scope: list[str], branch: Optional[str] = None,
                    expect_sha: Optional[str] = None) -> None:
    st = load_state(repo_root)
    prev = st.get("active_task") or {}
    st["active_task"] = {
        "id": task_id,
        "batch": batch,
        "state": state_name,
        "branch": branch if branch is not None else prev.get("branch"),
        "scope": scope,
        "expect_sha": expect_sha if expect_sha is not None else prev.get("expect_sha"),
        "attempts": prev.get("attempts", 0) if prev.get("id") == task_id else 0,
        "failure_signature": (prev.get("failure_signature")
                              if prev.get("id") == task_id else None),
    }
    st["frontier"]["active_batch"] = batch
    st["frontier"]["last_event_ts"] = now_iso()
    save_state(repo_root, st)


def clear_active_task(repo_root: Path) -> None:
    st = load_state(repo_root)
    st["active_task"] = None
    st["frontier"]["last_event_ts"] = now_iso()
    save_state(repo_root, st)


def active_scope(repo_root: Path, session: Optional[str] = None) -> Optional[list[str]]:
    """Claim scope[] or None (S1.3): `session` -> that entry's claim; else sole claim."""
    st = load_state(repo_root)
    if session is not None:
        entry = (st.get("active_tasks") or {}).get(session)
        return (entry.get("scope") or []) if entry else None
    at = st.get("active_task")
    if not at:
        return None
    return at.get("scope") or []


# --- single-writer lock ---
def _minutes_since(ts: Optional[str]) -> Optional[float]:
    """Minutes since a now_iso() (`%Y-%m-%dT%H:%MZ`, UTC) timestamp; None if unparseable."""
    try:
        dt = datetime.strptime(ts or "", "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0


def _lock_orphaned(state: dict[str, Any], idle_minutes: int) -> bool:
    """True iff a lock is held with NO live work behind it: no active_task, no claim
    with an unexpired lease_expiry, AND heartbeat older than idle_minutes. A missing/
    None heartbeat is treated as NOT orphaned (never steal on missing info)."""
    lock = state.get("lock")
    if not lock or state.get("active_task"):
        return False
    now = now_iso()
    if any((e.get("lease_expiry") or "") > now
           for e in (state.get("active_tasks") or {}).values()):
        return False  # a live claim
    age = _minutes_since(lock.get("heartbeat"))
    return age is not None and age >= idle_minutes


def acquire_lock(repo_root: Path, session: str, ttl_minutes: int = 90,
                 idle_minutes: int = 15) -> bool:
    """Refuse only if a DIFFERENT session holds a lock that is still live — neither
    TTL-expired nor orphaned. Else grant, stamping session+expiry+heartbeat."""
    st = load_state(repo_root)
    lock = st.get("lock")
    if (lock and lock.get("session") != session
            and lock.get("expiry", "") > now_iso()
            and not _lock_orphaned(st, idle_minutes)):
        return False
    exp = datetime.now(timezone.utc).timestamp() + ttl_minutes * 60
    st["lock"] = {
        "session": session,
        "expiry": datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "heartbeat": now_iso(),
    }
    save_state(repo_root, st)
    return True


def refresh_lock(repo_root: Path, session: str) -> None:
    """Stamp the held lock's heartbeat to now (for a loop to call each iteration)."""
    st = load_state(repo_root)
    lock = st.get("lock")
    if lock and lock.get("session") == session:
        lock["heartbeat"] = now_iso()
        save_state(repo_root, st)


def release_lock(repo_root: Path, session: str) -> None:
    st = load_state(repo_root)
    if (st.get("lock") or {}).get("session") == session:
        st["lock"] = None
        save_state(repo_root, st)


# --- claim registry + atomic claim primitive (SPEC §S2) ---
def _locks_dir(repo_root: Path) -> Path:
    d = repo_root / LOCKS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextlib.contextmanager
def _state_lock(repo_root: Path) -> Iterator[None]:
    """Hold fcntl.flock(LOCK_EX) on docs/.locks/state.lock for a whole RMW (S2.1)."""
    fd = os.open(str(_locks_dir(repo_root) / "state.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _claim_path(repo_root: Path, task: str) -> Path:
    return _locks_dir(repo_root) / f"{task}.claim"


def claim_task(repo_root: Path, session: str, task: str, scope: list[str],
               branch: Optional[str] = None, worktree: Optional[str] = None,
               ttl: int = 90) -> bool:
    """Atomically claim `task` for `session` (S2.2/S2.3). Under the state lock, refuse
    (no write) if the task is claimed or the session holds one; else write entry +
    claim file. Flock-serialized: one winner."""
    with _state_lock(repo_root):
        st = load_state(repo_root)
        active: dict[str, Any] = st.setdefault("active_tasks", {})
        if session in active or any(e.get("id") == task for e in active.values()):
            return False
        now = datetime.now(timezone.utc)
        expiry = now.timestamp() + max(0, ttl) * 60
        exp_iso = datetime.fromtimestamp(expiry, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        active[session] = {
            "id": task, "scope": scope, "branch": branch, "worktree": worktree,
            "lease_expiry": exp_iso, "heartbeat": now.strftime("%Y-%m-%dT%H:%MZ"),
            "attempts": 0, "failure_signature": None,
        }
        _claim_path(repo_root, task).write_text(f"{os.getpid()}\n", encoding="utf-8")
        save_state(repo_root, st)
    return True


def release_claim(repo_root: Path, session: str) -> None:
    """Remove the session's registry entry and its claim file, idempotently (S2.4)."""
    task: Optional[str] = None
    with _state_lock(repo_root):
        st = load_state(repo_root)
        active: dict[str, Any] = st.setdefault("active_tasks", {})
        entry = active.pop(session, None)
        if entry:
            task = entry.get("id")
        if not active:
            st["active_task"] = None
        save_state(repo_root, st)
    if task:
        with contextlib.suppress(FileNotFoundError):
            _claim_path(repo_root, task).unlink()


# --- append-only forensic log (LEDGER.md) ---
VALID_KINDS = {
    "transition", "intent", "finding", "gotcha",
    "traceback", "needs-human", "revert", "lock", "unlock",
}


def append_event(repo_root: Path, task_id: str, kind: str, detail: str,
                 sha: str = "-") -> None:
    """Append one event line to LEDGER.md. `kind` must be in VALID_KINDS."""
    if kind not in VALID_KINDS:
        kind = "finding"  # never silently drop; record under the catch-all
    f = repo_root / LOG_FILE
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text("# LEDGER — traceback log\n\n", encoding="utf-8")
    line = f"- {now_iso()} | {task_id} | {kind} | {detail} | {sha}\n"
    with f.open("a", encoding="utf-8") as fh:
        fh.write(line)
    st = load_state(repo_root)
    st["frontier"]["last_event_ts"] = now_iso()
    save_state(repo_root, st)


# --- git helpers (used by ledger_commit.py and the loop) ---
def git(repo_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


# Bookkeeping paths excluded from the CODE signature (churn must not read dirty).
_BOOKKEEPING_EXCLUDES = [
    ":(exclude)docs/**",
    ":(exclude)reviews/**",
    ":(exclude).claude/**",
    ":(exclude)STANDARDS.md",
    ":(exclude).harness.yaml",
]


def _code_porcelain(repo_root: Path) -> str:
    return git(repo_root, "status", "--porcelain", "--", ".",
               *_BOOKKEEPING_EXCLUDES).stdout.strip()


def _code_diff(repo_root: Path) -> str:
    return git(repo_root, "diff", "HEAD", "--", ".", *_BOOKKEEPING_EXCLUDES).stdout


def code_clean(repo_root: Path) -> bool:
    """No uncommitted *code* changes (ignoring bookkeeping churn); for resume."""
    return _code_porcelain(repo_root) == "" and _code_diff(repo_root).strip() == ""


def tree_sha(repo_root: Path) -> Optional[str]:
    """Stable signature of the CODE working tree (uncommitted code vs HEAD, excluding
    bookkeeping), for resume. Stable across ledger commits. None outside a git repo."""
    if git(repo_root, "rev-parse", "HEAD").returncode != 0:
        return None
    import hashlib

    payload = _code_diff(repo_root) + "\n" + _code_porcelain(repo_root)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
