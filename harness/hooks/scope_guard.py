#!/usr/bin/env python3
"""PreToolUse scope guard.

Hard-denies any Edit/Write/MultiEdit/NotebookEdit whose target file lies outside
the active task's declared scope[], at the tool layer — restoring the tool-layer
scope gate that an honor-system implementer loop otherwise loses. PostToolUse
cannot block (the write already happened); this MUST run on
PreToolUse.

Contract: reads the hook JSON on stdin. Exit 0 = allow. Exit 2 + stderr = deny
(Claude Code surfaces stderr to the model as the block reason).

This is a drift guardrail at the tool layer, not an adversarial sandbox: some
paths are always-allowed and the post-run audit (audit.py) is the backing
check. Confine untrusted agents with an OS-level sandbox. See SECURITY.md.

Session/worktree awareness (S8.3): in parallel mode several sessions hold
concurrent claims, each in its own worktree. The guard resolves *which* session
is doing the write (its worktree → claim, mirroring precommit_scope) and enforces
THAT claim's scope, not the singleton. With zero or one claim and no matching
worktree it collapses to today's singleton `active_scope` — byte-identical.

Path-based resolution (S11.3): because subagents in one Claude Code process may
share the orchestrator's `cwd`, the FIRST resolution attempt is by the target
file's worktree — which registered `active_tasks` worktree the write path lies
under (longest-prefix match, pathlib segment semantics). Only when the path is
under no registered worktree does it fall back to the cwd→session resolution,
then the singleton. This changes only WHICH claim is selected, not allow/deny.

Fail-open cases (exit 0): no active claim in flight, no LEDGER.state.json, path
outside the repo, or an always-allowed bookkeeping path (docs/, reviews/, etc.).
The guard only restricts *implementation* writes during an active task.

The scope decision itself lives in the reusable `scope_check(repo, session,
paths)` function so the pre-commit hook, this PreToolUse guard, and the
Codex/Gemini adapters (see ADAPTER-WIRING.md) all call ONE checker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402
import precommit_scope  # noqa: E402  (worktree resolution — reused, not duplicated)


# --------------------------------------------------------------------------- #
# Reusable scope checker (SPEC §S8.3 A3) — the ONE decision the pre-commit hook,
# this PreToolUse guard, and the Codex/Gemini adapters share.
# --------------------------------------------------------------------------- #
def _task_id_for(repo_root: Path, session: Optional[str]) -> str:
    """The task id whose scope we are enforcing, for the deny message / event.
    With a session it is that registry claim; without, the derived singleton view
    (matches the pre-feature guard's `active_task` read exactly)."""
    st = ledger.load_state(repo_root)
    if session is not None:
        return ((st.get("active_tasks") or {}).get(session) or {}).get("id", "?")
    return (st.get("active_task") or {}).get("id", "?")


def scope_check(
    repo_root: Path, session: Optional[str], paths: list[str]
) -> dict[str, Any]:
    """Pure-ish scope decision shared by every enforcement surface (A3).

    Resolves the enforced scope via `ledger.active_scope(repo_root, session=...)`:
    with `session`, that session/worktree's registry claim; without, the singleton
    `active_task` view (0/1-claim behaviour preserved EXACTLY). A path is a
    violation when it is outside `scope ∪ ledger.ALWAYS_ALLOWED`.

    Fail-open: when no claim resolves (`active_scope` is None — no task in flight),
    nothing violates. Returns
      {"clean": bool, "violations": [rel, ...], "scope": list|None, "task_id": str}.
    """
    scope = ledger.active_scope(repo_root, session=session)
    task_id = _task_id_for(repo_root, session)
    if scope is None:
        return {"clean": True, "violations": [], "scope": None, "task_id": task_id}
    violations = [
        rel
        for rel in paths
        if rel
        and not ledger.is_always_allowed(rel)
        and not ledger.path_in_scope(rel, scope)
    ]
    return {
        "clean": not violations,
        "violations": violations,
        "scope": scope,
        "task_id": task_id,
    }


def scope_violation(
    repo_root: Path, session: Optional[str], rel_path: str
) -> bool:
    """Boolean convenience over `scope_check`: True iff `rel_path` is out of scope
    for `session` (or the singleton when session is None). False on the fail-open
    path (no claim). Used by the adapters and the selftest."""
    return bool(scope_check(repo_root, session, [rel_path])["violations"])


# --------------------------------------------------------------------------- #
# session / worktree resolution (mirrors precommit_scope — no divergent scheme)
# --------------------------------------------------------------------------- #
def _main_root(cwd: Optional[str], fallback: Path) -> Path:
    """The main working tree that holds docs/LEDGER.state.json. In a linked
    worktree this differs from `cwd`'s own root; `precommit_scope.main_repo_root`
    resolves it via `--git-common-dir`. Falls back to `fallback` on any error."""
    try:
        return precommit_scope.main_repo_root(Path(cwd) if cwd else Path.cwd())
    except Exception:
        return fallback


def _resolve_session(main_root: Path, cwd: Optional[str]) -> Optional[str]:
    """The session id whose claim.worktree matches this write's worktree, or None.
    Reuses `precommit_scope.worktree_root`/`resolve_claim` so the "which claim is
    this?" logic has exactly one implementation. Returns None (→ singleton
    fallback) when the registry is empty (the N=1 fast path, no git calls) or no
    worktree matches. Fail-open on any error."""
    try:
        state = ledger.load_state(main_root)
        active = state.get("active_tasks") or {}
        if not active:
            return None  # N=1 / singleton: nothing to disambiguate
        c = Path(cwd) if cwd else Path.cwd()
        wt_root = precommit_scope.worktree_root(c)
        entry = precommit_scope.resolve_claim(state, main_root, wt_root)
        if entry is None:
            return None
        for sess, e in active.items():
            if e is entry:
                return sess
    except Exception:
        return None
    return None


def _resolve_by_path(main_root: Path, rel: str) -> tuple[Optional[str], str]:
    """Resolve the owning claim by which registered worktree the TARGET FILE lies
    under (SPEC §S11.3) — the first resolution attempt, so a subagent write is
    checked correctly even when its `cwd` is the orchestrator's shared directory
    rather than the worktree.

    `rel` is the write path made repo-relative to `main_root`. Each live claim's
    `worktree` is likewise relativized, then matched with pathlib SEGMENT
    semantics (`Path.is_relative_to`, NOT a string prefix — so `.worktrees/T1-extra`
    does not match `.worktrees/T1`). The most specific (longest-prefix)
    matching worktree wins (subsumes nested worktrees, A3). Claims with an
    empty/None worktree are skipped.

    Returns `(session, path_relative_to_that_worktree)` on a match — the inner
    path is what the claim's repo-relative `scope[]` is checked against — else
    `(None, rel)` so the caller falls back to cwd/session/singleton resolution.
    Fail-open (returns the no-match tuple) on any error."""
    try:
        active = (ledger.load_state(main_root).get("active_tasks") or {})
        if not active:
            return None, rel  # N=1 / singleton: nothing to disambiguate
        rel_path = Path(rel)
        best_session: Optional[str] = None
        best_wt: Optional[Path] = None
        best_depth = -1
        for session, entry in active.items():
            wt = entry.get("worktree")
            if not wt:
                continue  # no worktree registered — not a path-matchable claim
            wt_rel = ledger.to_repo_rel(wt, main_root)
            if wt_rel is None:
                continue  # worktree outside the main repo — skip
            wt_path = Path(wt_rel)
            depth = len(wt_path.parts)
            if rel_path.is_relative_to(wt_path) and depth > best_depth:
                best_session, best_wt, best_depth = session, wt_path, depth
        if best_session is None or best_wt is None:
            return None, rel
        return best_session, rel_path.relative_to(best_wt).as_posix()
    except Exception:
        return None, rel


def _resolve_claim_for(
    main_root: Path, cwd: Optional[str], rel: str
) -> tuple[Optional[str], str]:
    """Pick the owning claim's session + the path to scope-check against it, in the
    SPEC §S11.3 order: (1) path→worktree (`_resolve_by_path`); (2) the existing
    cwd→worktree→session resolution; (3) None → singleton `active_scope` / fail-open.
    Only WHICH claim is chosen changes here — the allow/deny semantics do not."""
    session, checked = _resolve_by_path(main_root, rel)
    if session is not None:
        return session, checked
    return _resolve_session(main_root, cwd), rel


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input — don't block the user

    tool = data.get("tool_name", "")
    if tool not in ledger.WRITE_TOOLS:
        return 0

    tin = data.get("tool_input", {}) or {}
    raw_path = tin.get("file_path") or tin.get("notebook_path") or ""
    if not raw_path:
        return 0

    # repo_root = the worktree the write lands in (the main repo in the N=1 case).
    # Scope patterns are repo-relative and the worktree mirrors the repo tree, so
    # relativizing against the worktree yields the correct repo-relative path.
    repo_root = ledger.find_repo_root(data.get("cwd"))
    if repo_root is None:
        return 0

    rel = ledger.to_repo_rel(raw_path, repo_root)
    if rel is None:
        return 0  # outside the repo — not ours to police

    # State (the claim registry) lives in the MAIN repo even when the write is in
    # a linked worktree; resolve the OWNING claim there — first by the target
    # file's worktree (S11.3), then by cwd — and enforce its scope against the
    # path relativized to that worktree. With 0/1 claims and no worktree match
    # this collapses to the singleton — byte-identical.
    main_root = _main_root(data.get("cwd"), repo_root)
    session, checked = _resolve_claim_for(main_root, data.get("cwd"), rel)
    result = scope_check(main_root, session, [checked])
    if result["clean"]:
        return 0

    # Out of scope during an active task -> deny + record a traceback event.
    scope = result["scope"]
    task_id = result["task_id"]
    try:
        ledger.append_event(
            main_root, task_id, "traceback",
            f"DENIED out-of-scope {tool} -> {rel} (scope={scope})",
        )
    except Exception:
        pass  # never let bookkeeping failure turn a deny into a crash

    sys.stderr.write(
        f"[scope-guard] BLOCKED: {tool} on '{rel}' is outside task {task_id}'s "
        f"declared scope[]. Allowed: {scope}. "
        f"If this file genuinely needs changing, stop and report it to the "
        f"orchestrator (add it to the task's scope[] via a challenge) rather "
        f"than widening the blast radius.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
