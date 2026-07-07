#!/usr/bin/env python3
"""git pre-commit scope hook for every CLI tool (SPEC §S8.1/§S8.2/§S8.5).

Installed as a repo `pre-commit` hook (or via `core.hooksPath`), this runs with
cwd = the worktree being committed. It resolves *that worktree's* active claim
from the shared ledger and blocks the commit (exit non-zero, offenders named on
stderr) when any staged path is outside `claim.scope ∪ ledger.ALWAYS_ALLOWED`,
or matches the sensitive-path deny-list (`.env`, `*.pem`, `*.key`, credentials).

Two contracts, mirroring `scope_guard.py`:
  * FAIL OPEN (exit 0) when there is no active claim for this worktree — a
    developer's own manual commit must never be bricked (S8.2).
  * FAIL CLOSED on the block path — once a violation is found, block.

`--no-verify` / `-n` skips this hook entirely (git never runs it), so it cannot
see the flag that disables it. `check_commit_args()` is the companion PRE-TOOL
guard (wired into a Bash matcher) that denies such a bypass BEFORE git runs;
the two layers together close the skip (S8.5).

No third-party deps; stdlib only. git is always invoked via an argument array.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402

# Own copy of the sensitive-path deny-list — per-surface self-containment; the
# authoritative reference lives in autodrive/audit.py (SENSITIVE_PATHS). Matched
# on the file BASENAME via fnmatch so nested copies (config/prod.pem) are caught.
SENSITIVE_PATHS = (
    ".env", ".env*", "*.pem", "*.key", "*credentials*", "id_*", "*_token*",
)

ALLOW = 0
BLOCK = 1  # any non-zero return aborts the commit

_FLAG_CLUSTER = re.compile(r"^-[A-Za-z]+$")  # e.g. -n, -nm (short-flag bundle)


# --------------------------------------------------------------------------- #
# git / path helpers (argument arrays only — no shell interpolation)
# --------------------------------------------------------------------------- #
def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )


def is_sensitive(rel_path: str) -> bool:
    base = rel_path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(base, pat) for pat in SENSITIVE_PATHS)


def staged_files(cwd: Path) -> list[str]:
    """Repo-relative paths of files added/copied/modified in the index."""
    r = _git(cwd, "diff", "--cached", "--name-only", "--diff-filter=ACM")
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def worktree_root(cwd: Path) -> Path:
    r = _git(cwd, "rev-parse", "--show-toplevel")
    out = r.stdout.strip()
    return Path(out).resolve() if r.returncode == 0 and out else Path(cwd).resolve()


def main_repo_root(cwd: Path) -> Path:
    """The main working tree that holds docs/LEDGER.state.json. In a linked
    worktree `--git-common-dir` points at the shared `.git`; its parent is the
    main repo. Falls back to this worktree's own root."""
    r = _git(cwd, "rev-parse", "--git-common-dir")
    out = r.stdout.strip()
    if r.returncode == 0 and out:
        gd = Path(out)
        if not gd.is_absolute():
            gd = Path(cwd) / gd
        return gd.resolve().parent
    return worktree_root(cwd)


def resolve_claim(
    state: dict[str, Any], main_root: Path, wt_root: Path
) -> Optional[dict[str, Any]]:
    """The active claim whose `worktree` path matches this worktree, or None.
    Matching by worktree is what makes the hook enforce the *committing* session's
    scope in parallel mode, not the singleton."""
    for entry in (state.get("active_tasks") or {}).values():
        wt = entry.get("worktree")
        if not wt:
            continue
        wp = Path(wt)
        if not wp.is_absolute():
            wp = main_root / wp
        try:
            if wp.resolve() == wt_root:
                return entry
        except OSError:
            continue
    return None


def offending_files(
    files: list[str], scope: list[str]
) -> tuple[list[str], list[str]]:
    """Split staged paths into (out_of_scope, sensitive). Sensitive is checked
    FIRST so a secret blocks even when it falls inside the claimed scope (A5)."""
    out_of_scope, sensitive = [], []
    for rel in files:
        if is_sensitive(rel):
            sensitive.append(rel)
        elif ledger.is_always_allowed(rel) or ledger.path_in_scope(rel, scope):
            continue
        else:
            out_of_scope.append(rel)
    return out_of_scope, sensitive


def check_commit_args(argv: list[str]) -> int:
    """PRE-TOOL guard (S8.5): deny (non-zero) a `git commit` that would skip the
    pre-commit hook via `--no-verify` / `-n`. Wired into a Bash pre-tool matcher;
    the pre-commit hook itself cannot see this flag (git never runs it when it is
    set), so this second layer is what actually closes the bypass."""
    tokens = [t for t in (argv or []) if isinstance(t, str)]
    if not any(Path(t).name == "git" for t in tokens) or "commit" not in tokens:
        return ALLOW
    for t in tokens:
        if t == "--no-verify":
            return BLOCK
        if _FLAG_CLUSTER.match(t) and "n" in t[1:]:
            return BLOCK
    return ALLOW


def _format_block(task_id: str, oos: list[str], sens: list[str],
                  scope: list[str]) -> str:
    lines = [f"[precommit-scope] BLOCKED commit for task {task_id}."]
    if oos:
        lines.append(f"  out-of-scope staged files (scope={scope}):")
        lines += [f"    - {p}" for p in oos]
    if sens:
        lines.append("  sensitive files must never be committed:")
        lines += [f"    - {p}" for p in sens]
    lines.append(
        "  Unstage these files (git restore --staged <path>) or add them to the "
        "task's scope[] via a challenge. Do NOT bypass with --no-verify."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    cwd = Path.cwd()
    try:
        wt_root = worktree_root(cwd)
        state = ledger.load_state(main_repo_root(cwd))
        claim = resolve_claim(state, main_repo_root(cwd), wt_root)
    except Exception:
        return ALLOW  # never brick git if resolution itself fails
    if claim is None:
        return ALLOW  # S8.2 fail-open: no active claim for this worktree
    scope = claim.get("scope") or []
    oos, sens = offending_files(staged_files(cwd), scope)
    if not oos and not sens:
        return ALLOW
    sys.stderr.write(_format_block(claim.get("id", "?"), oos, sens, scope))
    return BLOCK


if __name__ == "__main__":
    sys.exit(main())
