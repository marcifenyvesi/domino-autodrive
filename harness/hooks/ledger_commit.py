#!/usr/bin/env python3
"""Stop / SessionEnd ledger-commit hook.

Flushes and commits LEDGER.md + LEDGER.state.json on session end so a hard kill
(rate limit) still leaves a consistent resume anchor. Load-bearing, not optional.

Always exits 0 — a bookkeeping commit must never block the user's session from
stopping. Commits only the two ledger files (never the user's code), so it is
safe to run unconditionally.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ledger  # noqa: E402


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    repo_root = ledger.find_repo_root(data.get("cwd"))
    if repo_root is None:
        return 0

    paths = [p for p in (ledger.LOG_FILE, ledger.STATE_FILE)
             if (repo_root / p).exists()]
    if not paths:
        return 0

    # Stage only the ledger files.
    ledger.git(repo_root, "add", "--", *paths)

    # Anything actually staged among them?
    staged = ledger.git(repo_root, "diff", "--cached", "--quiet", "--", *paths)
    if staged.returncode == 0:
        return 0  # nothing to commit

    ledger.git(
        repo_root, "commit", "-m",
        f"chore(ledger): checkpoint {ledger.now_iso()}",
        "--", *paths,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
