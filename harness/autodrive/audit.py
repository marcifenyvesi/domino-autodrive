#!/usr/bin/env python3
"""Authoritative post-turn scope audit for the autodrive engine (SPEC §S8.4).

This is the ONE enforcement layer no cooperating agent can bypass. The PreToolUse
guard and the pre-commit hook are fast-fail guardrails, but both are skippable
(`git commit --no-verify`, a disabled hook). This command re-derives the changed
file set straight from GIT — the committed diff of the task branch vs its base,
plus staged and untracked files — and re-checks every path against the SAME
shared scope-checker the hooks use (`ledger.path_in_scope` / `ledger.is_always_allowed`,
PRD-R8) plus a sensitive-path deny-list. The loop runs it after each implement
turn, BEFORE accepting the commit; a `clean:false` result (non-zero exit) tells
the loop to roll back or mark the task `needs-human` (PRD-R13 / SPEC-A2).

Thin logic module: `engine.py` (a CLI dispatcher near the STANDARDS
`max_file_lines: 400` cap) delegates to `cmd_scope_audit` here. Stdlib only.
"""
from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hooks"))
import ledger  # noqa: E402

# Sensitive paths that are a violation even when nominally in scope — mirrors the
# repo's secret patterns beside ledger.ALWAYS_ALLOWED. Matched on the file's
# BASENAME via fnmatch so nested copies (config/prod.pem) are caught too.
# NOTE: TASK-PRECOMMIT (batch 030) keeps its own copy for the git-hook surface —
# per-surface self-containment; a later refactor may centralize the single list.
SENSITIVE_PATHS = (
    ".env", ".env*", "*.pem", "*.key", "*credentials*", "id_*", "*_token*",
)


def _is_sensitive(rel_path: str) -> bool:
    base = rel_path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(base, pat) for pat in SENSITIVE_PATHS)


def _base_ref(repo: Path) -> str:
    """The ref the task worktree was cut from — the integration branch (the main
    repo's current branch), falling back to its HEAD sha when detached. A
    three-dot diff against this reveals exactly what the task branch added."""
    base = ledger.git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not base or base == "HEAD":
        base = ledger.git(repo, "rev-parse", "HEAD").stdout.strip()
    return base


def _changed_files(worktree: Path, base: str) -> list[str]:
    """Every path the worktree touched, re-derived from git itself (never a hook,
    so `--no-verify` cannot hide it): committed on the branch since it diverged
    from `base`, plus staged, plus untracked. Repo-relative POSIX paths."""
    seen: list[str] = []
    runs = [
        ledger.git(worktree, "diff", "--name-only", f"{base}...HEAD"),
        ledger.git(worktree, "diff", "--cached", "--name-only"),
        ledger.git(worktree, "ls-files", "--others", "--exclude-standard"),
    ]
    for r in runs:
        for line in r.stdout.splitlines():
            p = line.strip()
            if p and p not in seen:
                seen.append(p)
    return seen


def scope_audit(repo: Path, session: str) -> dict[str, Any]:
    """Re-diff `session`'s worktree from git and check every changed path against
    the claim's scope ∪ ALWAYS_ALLOWED and the sensitive-path deny-list (SPEC-S8.4).

    A path is a VIOLATION if it is outside scope ∪ ALWAYS_ALLOWED OR it matches the
    deny-list (sensitive even when nominally in scope). No claim for the session ->
    nothing to audit -> clean (S8.2 fail-open contract, mirroring the hooks)."""
    repo = Path(repo)
    entry = (ledger.load_state(repo).get("active_tasks") or {}).get(session)
    if not entry:
        return {"clean": True, "violations": []}
    scope = entry.get("scope") or []
    wt = entry.get("worktree")
    worktree = Path(wt) if wt and Path(wt).is_absolute() else (repo / wt) if wt else repo
    base = _base_ref(repo)
    violations = [
        p for p in _changed_files(worktree, base)
        if _is_sensitive(p)
        or not (ledger.path_in_scope(p, scope) or ledger.is_always_allowed(p))
    ]
    return {"clean": not violations, "violations": violations}


def cmd_scope_audit(repo: Path, args) -> int:
    """Print the audit JSON; exit NON-ZERO on `clean:false` so the loop rejects the
    turn and rolls back / escalates rather than accepting the commit (SPEC-A2)."""
    res = scope_audit(repo, args.session)
    print(json.dumps(res))
    return 0 if res["clean"] else 1
