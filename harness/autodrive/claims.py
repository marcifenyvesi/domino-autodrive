#!/usr/bin/env python3
"""Claims / status observability for the parallel autodrive engine (SPEC §S9, UI §U1).

Thin logic module that `engine.py` (a CLI dispatcher near the STANDARDS
`max_file_lines: 400` cap) imports. The `status` subcommand is a pure alias of
`claims` — engine registers ONE handler (`cmd_claims`) under both names.

    claims(repo)
        Live-claim snapshot for observability (S9.1): every unexpired registry
        entry with its session, task, batch, scope, branch, worktree,
        lease_expiry, heartbeat and a derived `age`, plus the `frontier`.

    cmd_claims(repo, args)
        `claims` / `status` CLI handler. JSON is the primary contract and the
        default (S9.1); `--human` renders the aligned table (U1). Exit 0 even
        when empty.

Stdlib only. Mirrors parallel.py's import of `engine`/`ledger`.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hooks"))
import engine  # noqa: E402
import ledger  # noqa: E402


# --------------------------------------------------------------------------- #
# observability: claims / status (SPEC §S9, UI §U1) — the `status` subcommand is
# a pure alias of `claims` (engine registers ONE handler under both names).
# --------------------------------------------------------------------------- #
def _humanize_age(since_iso: Optional[str], now: datetime) -> str:
    """Compact elapsed span since an ISO minute-stamp (`%Y-%m-%dT%H:%MZ`) — the
    derived `age`, computed on read and never persisted (S9.1)."""
    if not since_iso:
        return "?"
    try:
        then = datetime.strptime(since_iso, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "?"
    secs = max(0, int((now - then).total_seconds()))
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h{(secs % 3600) // 60:02d}m"
    return f"{secs // 86400}d{(secs % 86400) // 3600:02d}h"


def claims(repo: Path) -> dict[str, Any]:
    """Live-claim snapshot for observability (S9.1): every unexpired registry entry
    with its session, task, batch, scope, branch, worktree, lease_expiry, heartbeat
    and a derived `age`, plus the `frontier`. An empty registry yields
    `{"claims": [], "frontier": {...}}` — a normal success, never an error."""
    st = ledger.load_state(repo)
    active = st.get("active_tasks") or {}
    frontier = st.get("frontier") or {}
    now = datetime.now(timezone.utc)
    now_stamp = ledger.now_iso()
    task_batch: Optional[dict[str, Any]] = None  # lazily built; batch isn't stored per-entry
    rows: list[dict[str, Any]] = []
    for session, entry in active.items():
        exp = entry.get("lease_expiry")
        if exp and exp < now_stamp:
            continue  # expired lease — no longer a live claim
        task = entry.get("id")
        batch = entry.get("batch")
        if not batch:
            if task_batch is None:
                task_batch = {t: v.get("batch") for t, v in engine.all_tasks(repo).items()}
            batch = task_batch.get(task) or frontier.get("active_batch") or "?"
        rows.append({
            "session": session,
            "task": task,
            "batch": batch,
            "scope": entry.get("scope") or [],
            "branch": entry.get("branch"),
            "worktree": entry.get("worktree"),
            "lease_expiry": exp,
            "heartbeat": entry.get("heartbeat"),
            "age": _humanize_age(entry.get("heartbeat"), now),
        })
    return {"claims": rows, "frontier": frontier}


def _print_claims_table(data: dict[str, Any]) -> None:
    """Human-aligned table (U1.1): one row per live claim, newest heartbeat first,
    with a footer for the active batch + live count. Empty → `no active claims`
    (U1.3) — an explicit empty state, never a blank line."""
    rows = sorted(data.get("claims") or [],
                  key=lambda r: r.get("heartbeat") or "", reverse=True)
    if not rows:
        print("no active claims")
        return
    header = ["SESSION", "TASK", "BATCH", "BRANCH", "WORKTREE", "AGE", "LEASE"]
    keys = ["session", "task", "batch", "branch", "worktree", "age", "lease_expiry"]
    table = [header] + [[str(r.get(k) if r.get(k) is not None else "-") for k in keys]
                        for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(len(header))]
    for row in table:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(header))))
    frontier = data.get("frontier") or {}
    print(f"active batch {frontier.get('active_batch') or '-'} — {len(rows)} live")


def cmd_claims(repo: Path, args) -> int:
    """`claims` / `status` handler. JSON is the primary contract and the default
    (S9.1); `--human` renders the aligned table (U1). Exit 0 even when empty."""
    data = claims(repo)
    if getattr(args, "human", False):
        _print_claims_table(data)
    else:
        print(json.dumps(data))
    return 0
