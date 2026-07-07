#!/usr/bin/env python3
"""Glob-set scope-overlap gate for the Dynamic Traceback Harness (SPEC §S3).

Overlap between two task `scope[]` glob lists is decided by MATERIALIZING each
glob against the real repo tree and intersecting the concrete file SETS — never
by symbolic glob-vs-glob algebra (SPEC S3, PRD R-2). `fnmatch` is banned for
path scopes because it treats `/` as an ordinary character; we reuse the
canonical `_glob_to_re` from `ledger` (where `**` spans directories) over the
pathlib-walked tree — exactly `PurePath.full_match` over the tracked file list.

A planned, not-yet-created file (a task's own new file) still reserves its path:
each glob's literal non-magic prefix is injected into the file universe before
materialization, so a covering glob in the other scope resolves onto it (S3.1).

Kept separate from `ledger.py`, which is at the STANDARDS `max_file_lines: 400`
cap; this module imports its glob/path helpers rather than growing it.

No third-party deps; stdlib only (Python 3.8+).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ledger import _glob_to_re  # noqa: E402

# Directory names never walked when materializing the tree.
_SKIP_DIRS = {".git"}

# First shell-glob magic character; text before it is a literal path prefix.
_MAGIC = re.compile(r"[*?\[]")


def _tree_files(repo: Path) -> set[str]:
    """Repo-relative POSIX paths of every real file under `repo` (skips .git)."""
    files: set[str] = set()
    for p in repo.rglob("*"):
        rel = p.relative_to(repo)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        if p.is_file():
            files.add(rel.as_posix())
    return files


def _literal_prefix(glob: str) -> str:
    """The path up to the first magic char (`*`/`?`/`[`), trailing slash stripped.

    A glob with no magic (a planned literal file) returns itself, so a
    not-yet-created file still reserves its exact path (SPEC S3.1)."""
    m = _MAGIC.search(glob)
    prefix = glob if m is None else glob[: m.start()]
    return prefix.rstrip("/")


def _reserved_paths(globs: list[str]) -> set[str]:
    """The literal non-magic prefix each glob reserves (planned-file paths)."""
    out: set[str] = set()
    for g in globs:
        prefix = _literal_prefix(g) if g else ""
        if prefix:
            out.add(prefix)
    return out


def _materialize(globs: list[str], universe: set[str]) -> set[str]:
    """Paths in `universe` matched by any glob (via ledger's `_glob_to_re`)."""
    result: set[str] = set()
    for g in globs:
        if not g:
            continue
        rx = _glob_to_re(g)
        result.update(f for f in universe if rx.match(f))
    return result


def expand_scope(repo, globs: list[str]) -> set[str]:
    """Materialize `globs` against the real tree under `repo` -> repo-relative
    POSIX paths (SPEC S3.1), the file universe unioned with each glob's literal
    non-magic prefix so a planned new file reserves its path. Empty list -> set()."""
    if not globs:
        return set()
    repo = Path(repo)
    universe = _tree_files(repo) | _reserved_paths(globs)
    return _materialize(globs, universe)


def scopes_overlap(repo, a: list[str], b: list[str]) -> bool:
    """True iff the materialized file sets of `a` and `b` intersect (SPEC S3.2).

    Both scopes are materialized over ONE shared universe — the real tree plus
    both sides' reserved planned paths — so a planned new file in one scope is
    seen by a covering glob in the other. Symmetric; reflexive on non-empty
    sets; an empty scope reserves nothing, so `[] vs anything -> False`."""
    if not a or not b:
        return False
    repo = Path(repo)
    universe = _tree_files(repo) | _reserved_paths(a) | _reserved_paths(b)
    return bool(_materialize(a, universe) & _materialize(b, universe))
