#!/usr/bin/env python3
"""Claim-aware task selection for the parallel autodrive engine (SPEC §S4).

Thin logic module that `engine.py` (a CLI dispatcher near the STANDARDS
`max_file_lines: 400` cap) imports. Two entry points:

    next_task_claim_aware(repo, session=None)
        Like engine.next_task, but SKIPS any ready candidate whose scope
        overlaps a live claim, or that is itself already claimed. With NO live
        claims it returns byte-identical output to engine.next_task (S4.1,
        regression-locked by the selftest).

    next_parallel_set(repo, k)
        Greedy walk of ready tasks in DAG order, admitting a task iff its scope
        is disjoint from every already-admitted task AND every live claim; stops
        at K. Returns {"tasks": [{task, batch, scope, design_refs, file}, ...]}
        (S4.2) — one call yields a fleet of up to K disjoint agents (R-3).

Overlap is decided by `scope_algebra.scopes_overlap`, which materializes the
glob sets against the real tree (PRD R-2); this module never reimplements it.
Both paths honour existing batch/task `depends_on[]` gating unchanged (S4.3),
by reusing engine's DAG traversal helpers. Stdlib only.
"""
from __future__ import annotations

import contextlib
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hooks"))
import engine  # noqa: E402
import ledger  # noqa: E402
import scope_algebra  # noqa: E402


# --------------------------------------------------------------------------- #
# ready-candidate frontier (mirrors engine.next_task's DAG traversal)
# --------------------------------------------------------------------------- #
def _ready_candidates(repo: Path) -> list[dict[str, Any]]:
    """Ordered ready tasks across eligible batches, in engine.next_task order.

    Applies the same upstream-batch-done gate and per-task `depends_on` gate as
    engine.next_task, and collects EVERY ready task (not just the first) so the
    parallel set can admit more than one. Unlike serial engine.next_task — which
    deliberately STOPS at the first batch that has todo tasks but none ready
    (surfacing a stuck layer rather than jumping ahead) — the parallel walk
    SKIPS such a temporarily-blocked batch and keeps collecting from later
    deps-satisfied INDEPENDENT batches, so the fleet can fan out across all
    ready work the DAG permits (F-B fix; S4.2/PRD-R3). The first element still
    equals engine.next_task's pick when the first eligible batch has a ready
    task (the common case); when an earlier batch is fully blocked, the parallel
    walk intentionally reaches independent ready work the serial pick skips."""
    batches = engine.load_batches(repo)
    done_batches = {b["batch"] for b in batches if b.get("state") == "done"}
    tasks = engine.all_tasks(repo)
    out: list[dict[str, Any]] = []
    for b in batches:
        if b.get("state") == "done":
            continue
        if not all(dep in done_batches for dep in b.get("depends_on", [])):
            continue  # an upstream batch isn't done — skip this layer
        for tid in b.get("tasks", []):
            t = tasks.get(tid)
            if not t or t.get("state") != "todo":
                continue
            if engine._deps_done(t.get("depends_on", []), tasks):
                out.append({
                    "task": tid,
                    "batch": b["batch"],
                    "scope": t.get("scope", []),
                    "design_refs": t.get("design_refs", []),
                    "file": str(t["_file"]),
                })
        # NOTE: unlike serial engine.next_task, we do NOT stop at a batch that has
        # todo tasks but none ready — we fall through to later independent batches
        # so the fleet fans out across all deps-satisfied ready work the DAG
        # permits (F-B fix). The per-task depends_on gate above already excludes
        # non-ready tasks, so a blocked batch simply contributes nothing here.
    return out


# --------------------------------------------------------------------------- #
# live claims (the registry entries other sessions currently hold)
# --------------------------------------------------------------------------- #
def _live_claims(repo: Path, exclude_session: Optional[str] = None) -> list[dict[str, Any]]:
    """Registry entries with an unexpired lease, excluding `exclude_session`'s own
    claim. These are the scopes a new task must stay disjoint from (S4.1/PRD-R2)."""
    st = ledger.load_state(repo)
    active = st.get("active_tasks") or {}
    now = ledger.now_iso()
    claims: list[dict[str, Any]] = []
    for sess, entry in active.items():
        if exclude_session is not None and sess == exclude_session:
            continue
        exp = entry.get("lease_expiry")
        if exp and exp < now:
            continue  # expired lease — no longer a live claim
        claims.append(entry)
    return claims


def _overlaps_any(repo: Path, scope: list[str], claims: list[dict[str, Any]]) -> bool:
    return any(
        scope_algebra.scopes_overlap(repo, scope, c.get("scope") or [])
        for c in claims
    )


# --------------------------------------------------------------------------- #
# public selection API (SPEC §S4)
# --------------------------------------------------------------------------- #
def next_task_claim_aware(
    repo: Path, session: Optional[str] = None
) -> Optional[dict[str, Any]]:
    """First ready task whose scope is disjoint from every live claim and that is
    not itself already claimed (S4.1). With no live claims, byte-identical to
    engine.next_task. `session`, if given, excludes that session's own claim."""
    claims = _live_claims(repo, exclude_session=session)
    claimed_ids = {c.get("id") for c in claims}
    for cand in _ready_candidates(repo):
        if cand["task"] in claimed_ids:
            continue
        if _overlaps_any(repo, cand["scope"], claims):
            continue
        return cand
    return None


def next_parallel_set(repo: Path, k: int) -> dict[str, Any]:
    """≤K ready tasks, mutually scope-disjoint AND disjoint from every live claim,
    chosen greedily in DAG order (S4.2). Suitable for launching a fleet of up to
    K agents in a single call (PRD-R3)."""
    claims = _live_claims(repo)
    claimed_ids = {c.get("id") for c in claims}
    admitted: list[dict[str, Any]] = []
    admitted_scopes: list[list[str]] = []
    for cand in _ready_candidates(repo):
        if len(admitted) >= k:
            break
        if cand["task"] in claimed_ids:
            continue
        scope = cand["scope"]
        if _overlaps_any(repo, scope, claims):
            continue
        if any(scope_algebra.scopes_overlap(repo, scope, a) for a in admitted_scopes):
            continue
        admitted.append(cand)
        admitted_scopes.append(scope)
    return {"tasks": admitted}


# --------------------------------------------------------------------------- #
# worktree manager (SPEC §S5) — one dedicated working tree per claimed task.
#
# S5.4 gotchas encoded below: creation is SERIALIZED under ledger's state flock
# (concurrent `git worktree add` race on `.git/config.lock`); a linked worktree's
# `.git` is a FILE, resolved via `git rev-parse --git-dir`, never stat'd as a dir;
# submodules make parallel worktrees unsupported, so we REFUSE; teardown is
# `git worktree remove [--force]` + `prune`, NEVER `rm -rf`. Agents MUST NOT run
# `git stash` — the stash reflog is a single stack shared across every worktree,
# so a stash in one silently surfaces/drops another's work (data loss).
# --------------------------------------------------------------------------- #
_HARNESS = ".harness.yaml"
_WORKTREES = ".worktrees"


def _harness_block(repo: Path, top: str) -> dict[str, Any]:
    """Mapping nested under a top-level `top:` key in .harness.yaml.

    Indentation-aware (the shared engine._mini_yaml is flat and PyYAML is not
    installed here): scalar values and `- item` block lists only, which is all
    the `worktree:`/`parallel:` blocks use. Absent file/section -> {}."""
    f = repo / _HARNESS
    if not f.exists():
        return {}
    out: dict[str, Any] = {}
    in_section = False
    cur: Optional[str] = None
    for raw in f.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        stripped = raw.strip()
        if raw[:1] not in (" ", "\t"):  # top-level key
            in_section = stripped.rstrip() == f"{top}:"
            cur = None
            continue
        if not in_section:
            continue
        if stripped.startswith("- ") and cur is not None:
            out.setdefault(cur, [])
            if isinstance(out[cur], list):
                out[cur].append(engine._scalar(stripped[2:]))
        elif ":" in stripped:
            k, _, v = stripped.partition(":")
            cur = k.strip()
            out[cur] = engine._scalar(v) if v.strip() else []
    return out


def max_parallel(repo: Path) -> int:
    """`.harness.yaml parallel.max` concurrency cap (S5.4; default 4)."""
    v = _harness_block(repo, "parallel").get("max")
    return v if isinstance(v, int) and v > 0 else 4


def has_submodules(repo: Path) -> bool:
    return (Path(repo) / ".gitmodules").exists()


def git_dir(path: Path) -> Optional[str]:
    """Resolve a worktree's git dir via `git rev-parse --git-dir` (S5.4: a linked
    worktree's `.git` is a FILE pointing into .git/worktrees/<id>, never a real
    directory — always resolve it, never stat `.git` yourself)."""
    r = ledger.git(Path(path), "rev-parse", "--git-dir")
    return r.stdout.strip() if r.returncode == 0 else None


def _branch_exists(repo: Path, branch: str) -> bool:
    return ledger.git(
        repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
    ).returncode == 0


def _worktree_registered(repo: Path, rel: str) -> bool:
    target = str((repo / rel).resolve())
    r = ledger.git(repo, "worktree", "list", "--porcelain")
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            if str(Path(line[len("worktree "):].strip()).resolve()) == target:
                return True
    return False


def _provision(repo: Path, wt: Path) -> None:
    """Make a FRESH worktree runnable per `.harness.yaml worktree:` (S5.2/R-5):
    symlink `link:` entries, copy `copy:` entries, run `ready:` once. Called only
    on first creation so a resume never re-runs the (possibly costly) build."""
    cfg = _harness_block(repo, "worktree")
    if not cfg:
        return
    for entry in cfg.get("link") or []:
        dst = wt / str(entry)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            with contextlib.suppress(OSError):
                dst.symlink_to((repo / str(entry)).resolve())
    for entry in cfg.get("copy") or []:
        src = repo / str(entry)
        dst = wt / str(entry)
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    ready = cfg.get("ready")
    if isinstance(ready, str) and ready.strip():
        # arg-array, shell=False (STANDARDS §8): the command is repo config, but
        # we still never build a shell string.
        subprocess.run(shlex.split(ready), cwd=str(wt),
                       capture_output=True, text=True, check=False)


def _integration_base_sha(repo: Path) -> Optional[str]:
    """The integration base merge lands on, resolved to a commit sha, so a REUSED
    worktree builds on the SAME base the merge phase will target. Mirrors
    merge._integration_branch (`.harness.yaml merge.base`, else the current
    branch tip). Returns None when unresolvable (empty repo / bad config):
    callers then skip the guard and fall back to trusting the branch."""
    import merge  # noqa: E402  (lazy — merge imports parallel lazily; avoid a cycle)
    integ = merge._integration_branch(repo, None)
    r = ledger.git(repo, "rev-parse", "--verify", "--quiet", f"{integ}^{{commit}}")
    return r.stdout.strip() or None


def _stale_base_guard(repo: Path, wt: Path, branch: str, base_sha: str) -> dict[str, bool]:
    """Decide what to do with a REUSED `task/<id>` branch relative to `base_sha`.

    A branch that carries commits NOT in the base (`base..branch` non-empty) is
    genuine in-progress work → reuse as-is. A branch with no unique commits (an
    ancestor of / equal to the base) is a stale/fresh leftover: if the worktree
    is CLEAN, hard-reset it to the base so the subagent builds on current code;
    if it is DIRTY, leave it untouched (a reset would destroy uncommitted work)
    and flag `stale_base_dirty` so the caller can route it to needs-human."""
    ahead = ledger.git(repo, "rev-list", "--count", f"{base_sha}..{branch}")
    if (ahead.stdout.strip() or "0") != "0":
        return {"reset_to_base": False, "stale_base_dirty": False}
    dirty = ledger.git(wt, "status", "--porcelain").stdout.strip() != ""
    if dirty:
        return {"reset_to_base": False, "stale_base_dirty": True}
    ledger.git(wt, "reset", "--hard", base_sha)
    return {"reset_to_base": True, "stale_base_dirty": False}


def worktree_add(repo: Path, task_id: str) -> dict[str, Any]:
    """Create `.worktrees/<id>` on branch `task/<id>` (SPEC-S5.1), reusing an
    existing branch/worktree on resume rather than erroring. On reuse, a stale
    leftover branch (behind/at the integration base with no unique commits) is
    reset to the current base when the worktree is clean, so a subagent never
    builds on a dead session's stale base; a dirty stale worktree is flagged
    instead of reset. Creation is serialized under the state flock (S5.4);
    provisioning runs outside it. Refuses when submodules are present (S5.4)."""
    repo = Path(repo)
    if has_submodules(repo):
        return {"task": task_id, "error":
                "submodules present — parallel worktrees are unsupported (S5.4)"}
    rel = f"{_WORKTREES}/{task_id}"
    branch = f"task/{task_id}"
    wt = repo / rel
    base_sha = _integration_base_sha(repo)
    guard = {"reset_to_base": False, "stale_base_dirty": False}
    with ledger._state_lock(repo):  # serialize `git worktree add` (config.lock race)
        (repo / _WORKTREES).mkdir(parents=True, exist_ok=True)
        registered = _worktree_registered(repo, rel)
        reused_branch = _branch_exists(repo, branch)
        if not registered:
            add = ["worktree", "add", rel] + ([branch] if reused_branch else ["-b", branch])
            r = ledger.git(repo, *add)
            if r.returncode != 0:
                return {"task": task_id,
                        "error": r.stderr.strip() or "git worktree add failed"}
        if reused_branch and base_sha:  # only an EXISTING branch can be stale
            guard = _stale_base_guard(repo, wt, branch, base_sha)
    if not registered:
        _provision(repo, wt)
    return {"task": task_id, "path": str(wt), "branch": branch,
            "created": not registered, "reused": registered or reused_branch,
            "base": base_sha, **guard}


def worktree_remove(repo: Path, task_id: str, force: bool = False) -> dict[str, Any]:
    """Tear down `.worktrees/<id>` via `git worktree remove [--force]` then
    `prune` (SPEC-S5.3) — never `rm -rf`. A dirty worktree is NOT removed unless
    `force`; git itself enforces this and we surface its refusal."""
    repo = Path(repo)
    rel = f"{_WORKTREES}/{task_id}"
    args = ["worktree", "remove"] + (["--force"] if force else []) + [rel]
    r = ledger.git(repo, *args)
    ledger.git(repo, "worktree", "prune")
    if r.returncode != 0:
        return {"task": task_id, "removed": False,
                "error": r.stderr.strip() or "git worktree remove failed"}
    return {"task": task_id, "removed": True, "forced": force}


# --------------------------------------------------------------------------- #
# CLI handlers — thin (engine.py delegates here to stay under max_file_lines).
# --------------------------------------------------------------------------- #
def cmd_worktree_add(repo: Path, args) -> int:
    res = worktree_add(repo, args.task)
    print(json.dumps(res))
    return 1 if res.get("error") else 0


def cmd_worktree_remove(repo: Path, args) -> int:
    res = worktree_remove(repo, args.task, force=args.force)
    print(json.dumps(res))
    return 0 if res.get("removed") else 1


def cmd_claim(repo: Path, args) -> int:
    """Atomic CLI claim over ledger.claim_task (PRD-R1). Looks up the task's
    scope+batch, defaults branch `task/<id>` and worktree `.worktrees/<id>`,
    refuses on scope overlap with a live claim (S2/R-2) or a lost id race
    (non-zero exit so the caller tries another task), else claims, flips the task
    to in-progress, and prints the claim JSON."""
    import lease  # noqa: E402  (lazy — ttl default; avoids import-order surprise)
    t = engine.all_tasks(repo).get(args.task) or {}
    scope = t.get("scope", [])
    batch = t.get("batch", "?")
    branch = args.branch or f"task/{args.task}"
    worktree = args.worktree or f"{_WORKTREES}/{args.task}"
    claims = _live_claims(repo, exclude_session=args.session)
    conflict = any(c.get("id") == args.task for c in claims) or _overlaps_any(
        repo, scope, claims)
    ok = (not conflict) and ledger.claim_task(
        repo, args.session, args.task, scope, branch=branch, worktree=worktree,
        ttl=lease._lease_ttl_minutes(repo))
    if not ok:
        print(json.dumps({"claimed": False,
                          "reason": "already claimed or scope-conflict"}))
        return 1
    engine.set_task_state(repo, args.task, "in-progress")
    print(json.dumps({"claimed": True, "task": args.task, "session": args.session,
                      "batch": batch, "scope": scope, "branch": branch,
                      "worktree": worktree}))
    return 0


def cmd_release(repo: Path, args) -> int:
    """Release the session's claim (ledger.release_claim, idempotent, S2.4)."""
    ledger.release_claim(repo, args.session)
    print(json.dumps({"released": True}))
    return 0
