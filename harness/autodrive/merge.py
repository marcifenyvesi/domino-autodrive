#!/usr/bin/env python3
"""Sequential, verify-gated merge phase for the autodrive engine (SPEC §S7).

Thin logic module that `engine.py` (a CLI dispatcher near the STANDARDS
`max_file_lines: 400` cap) imports and delegates to. Two entry points:

    merge_ready(repo, base=None)
        The `task/<id>` branches whose task state is `done` and which are NOT
        yet merged into the integration branch (the current branch, or a
        configured `base`). Returns {"branches": [...]} (S7.1).

    merge_sequence(repo, branches=None, verify_cmd=None, base=None)
        Merge each ready branch ONE AT A TIME onto the integration branch and
        run the repo verify after EACH merge (S7.2). On a git conflict OR a
        failing verify: STOP, leave already-merged (and verified) branches
        intact, undo only the offending merge (`git merge --abort` for a
        conflict / reset to the pre-merge commit for a red verify) so the
        integration branch sits at the last GOOD commit, and emit a
        `needs-human` ledger event for the offending branch. Returns a
        per-branch result list.

S7.4 (research: necessary-but-not-sufficient). A clean *textual* merge is NOT a
green build: disjoint scopes only guarantee no text conflicts, while a semantic
conflict (a rename at call sites vs a new call to the old name) merges clean yet
breaks compilation — so the per-merge verify in S7.2 is the real gate, never the
merge exit status. Shared generated/index files (lockfiles, barrel/`__init__.py`
index files, formatter-owned config) MUST be kept out of agent `scope[]`; a
ready branch that touched one is FLAGGED here (it slipped scope), and lockfiles
are regenerated ONCE post-merge (not merged) via `regenerate_lockfiles`. Run git
via argument arrays (STANDARDS §8), never an interpolated shell string. Stdlib
only.
"""
from __future__ import annotations

import fnmatch
import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hooks"))
import engine  # noqa: E402
import ledger  # noqa: E402

_BRANCH_PREFIX = "task/"
# Default verify when neither the caller nor `.harness.yaml merge.verify`
# supplies one: run the harness selftests (the same gate the loop relies on).
_DEFAULT_VERIFY = ["python3", "harness/autodrive/_selftest.py"]

# Shared generated/index files that MUST stay out of agent scope[] (S7.4). A
# ready branch that touched one slipped scope and is flagged; matched on the
# file's BASENAME via fnmatch so nested copies (frontend/uv.lock) are caught too.
_SHARED_GENERATED_GLOBS = (
    "*.lock", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
    "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock", "Gemfile.lock",
    "composer.lock", "go.sum",
    "__init__.py", "index.js", "index.ts", "index.jsx", "index.tsx", "mod.rs",
    ".prettierrc", ".prettierrc.*", "prettier.config.*", ".editorconfig",
    ".eslintrc", ".eslintrc.*", ".rustfmt.toml", "rustfmt.toml", ".clang-format",
)


# --------------------------------------------------------------------------- #
# integration-branch + git helpers (arg-array only, STANDARDS §8)
# --------------------------------------------------------------------------- #
def _current_branch(repo: Path) -> str:
    r = ledger.git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return r.stdout.strip() or "HEAD"


def _integration_branch(repo: Path, base: Optional[str]) -> str:
    """The branch merges land on: explicit `base`, else `.harness.yaml
    merge.base`, else the currently checked-out branch (S7.1)."""
    if base:
        return base
    cfg = _merge_cfg(repo).get("base")
    return cfg if isinstance(cfg, str) and cfg else _current_branch(repo)


def _branch_exists(repo: Path, branch: str) -> bool:
    return ledger.git(
        repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
    ).returncode == 0


def _is_merged(repo: Path, branch: str, base: str) -> bool:
    """True iff `branch`'s tip is already an ancestor of `base` (already merged)."""
    return ledger.git(
        repo, "merge-base", "--is-ancestor", branch, base
    ).returncode == 0


def _branch_files(repo: Path, branch: str, base: str) -> list[str]:
    """Paths changed on `branch` since it diverged from `base` (`base...branch`)."""
    r = ledger.git(repo, "diff", "--name-only", f"{base}...{branch}")
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


def _merge_cfg(repo: Path) -> dict[str, Any]:
    import parallel  # noqa: E402  (lazy — avoids any import-order surprise)
    return parallel._harness_block(repo, "merge")


# --------------------------------------------------------------------------- #
# S7.4 — shared generated/index file flagging
# --------------------------------------------------------------------------- #
def shared_generated_hits(files: list[str]) -> list[str]:
    """The subset of `files` that are shared generated/index files (S7.4) — these
    should have been kept out of the agent's scope[]."""
    hits: list[str] = []
    for f in files:
        base = f.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(base, g) for g in _SHARED_GENERATED_GLOBS):
            hits.append(f)
    return hits


# --------------------------------------------------------------------------- #
# S7.1 — merge-ready
# --------------------------------------------------------------------------- #
def merge_ready(repo: Path, base: Optional[str] = None) -> dict[str, Any]:
    """`task/<id>` branches whose task state is `done` and that are not yet merged
    into the integration branch (S7.1)."""
    repo = Path(repo)
    integ = _integration_branch(repo, base)
    branches: list[str] = []
    for tid, t in engine.all_tasks(repo).items():
        if t.get("state") != engine.TERMINAL_OK:
            continue
        branch = f"{_BRANCH_PREFIX}{tid}"
        if not _branch_exists(repo, branch):
            continue
        if _is_merged(repo, branch, integ):
            continue  # tip already an ancestor of the integration branch
        branches.append(branch)
    return {"branches": branches}


# --------------------------------------------------------------------------- #
# S7.2 — sequential merge with per-merge verify gate
# --------------------------------------------------------------------------- #
def _resolve_verify(repo: Path, verify_cmd) -> list[str]:
    """Verify as an arg-list: caller value, else `.harness.yaml merge.verify`,
    else the harness selftests. A string is shlex-split (shell=False, §8)."""
    if verify_cmd is None:
        verify_cmd = _merge_cfg(repo).get("verify")
    if not verify_cmd:
        return list(_DEFAULT_VERIFY)
    return shlex.split(verify_cmd) if isinstance(verify_cmd, str) else list(verify_cmd)


def _run_verify(repo: Path, verify_list: list[str]) -> bool:
    """Run the verify command (arg-array, no shell). True iff it exits 0."""
    if not verify_list:
        return True
    return subprocess.run(
        verify_list, cwd=str(repo), capture_output=True, text=True, check=False,
    ).returncode == 0


def _merge_one(repo: Path, branch: str, verify_list: list[str]) -> str:
    """Merge one branch onto the current integration branch, then verify. Returns
    'merged' | 'conflict' | 'verify-failed'. On failure the offending merge is
    undone so the integration branch is left at the last good commit (S7.2)."""
    pre = ledger.git(repo, "rev-parse", "HEAD").stdout.strip()
    m = ledger.git(repo, "merge", "--no-edit", branch)
    if m.returncode != 0:
        ledger.git(repo, "merge", "--abort")  # clean conflict, back to `pre`
        return "conflict"
    if not _run_verify(repo, verify_list):
        # clean text, red build (a semantic conflict, S7.4): roll back this merge
        ledger.git(repo, "reset", "--hard", pre)
        return "verify-failed"
    return "merged"


def merge_sequence(
    repo: Path,
    branches: Optional[list[str]] = None,
    verify_cmd=None,
    base: Optional[str] = None,
) -> dict[str, Any]:
    """Merge each ready branch one at a time onto the integration branch, running
    the verify after each (S7.2). Stops on the first conflict/red verify, leaving
    already-merged branches intact and escalating the offender to needs-human."""
    repo = Path(repo)
    integ = _integration_branch(repo, base)
    if branches is None:
        branches = merge_ready(repo, integ)["branches"]
    verify_list = _resolve_verify(repo, verify_cmd)
    results: list[dict[str, Any]] = []
    stopped = False
    for branch in branches:
        tid = branch[len(_BRANCH_PREFIX):] if branch.startswith(_BRANCH_PREFIX) else branch
        flags = shared_generated_hits(_branch_files(repo, branch, integ))
        if flags:
            ledger.append_event(repo, tid, "finding",
                                f"shared generated/index files in scope (S7.4): {flags}")
        status = _merge_one(repo, branch, verify_list)
        results.append({"branch": branch, "task": tid, "status": status,
                        "shared_flags": flags})
        if status != "merged":
            ledger.append_event(repo, tid, "needs-human",
                                f"merge {status} on {branch} -> {integ}")
            stopped = True
            break
    out: dict[str, Any] = {"integration": integ, "results": results,
                           "stopped": stopped}
    if not stopped:
        out["lockfile_regen"] = regenerate_lockfiles(repo)
    return out


# --------------------------------------------------------------------------- #
# S7.4 — post-merge lockfile regeneration hook (run ONCE, not merged)
# --------------------------------------------------------------------------- #
def regenerate_lockfiles(repo: Path) -> dict[str, Any]:
    """Regenerate lockfiles ONCE after a full clean sequence (S7.4). Lockfiles are
    kept out of agent scope and never merged; instead the package manager
    reconciles them here and the result is committed if it changed. The concrete
    command is repo config (`.harness.yaml merge.lockfile_regen`); with none set
    this is a documented no-op that names the manual step."""
    cmd = _merge_cfg(repo).get("lockfile_regen")
    if isinstance(cmd, str) and cmd.strip():
        r = subprocess.run(shlex.split(cmd), cwd=str(repo), capture_output=True,
                           text=True, check=False)
        return {"ran": True, "cmd": cmd, "ok": r.returncode == 0}
    return {"ran": False, "note": "no merge.lockfile_regen configured; "
            "regenerate lockfiles once post-merge and commit if changed"}


# --------------------------------------------------------------------------- #
# CLI handlers — thin (engine.py delegates here to stay under max_file_lines).
# --------------------------------------------------------------------------- #
def cmd_merge_ready(repo: Path, args) -> int:
    print(json.dumps(merge_ready(repo, base=getattr(args, "base", None))))
    return 0


def cmd_merge(repo: Path, args) -> int:
    res = merge_sequence(repo, verify_cmd=getattr(args, "verify", None),
                         base=getattr(args, "base", None))
    print(json.dumps(res))
    return 1 if res.get("stopped") else 0
