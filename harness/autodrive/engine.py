#!/usr/bin/env python3
"""Autodrive engine — the DETERMINISTIC core of the loop.

The /autodrive *command* (commands/autodrive.md) owns the LLM-driven steps
(challenge, implement-via-subagent, audit). This module owns everything that
must be exact and testable: the single-writer lock, picking the next ready task
from the batch/task DAG, recording state transitions to the ledger, resume
reconciliation, and the no-progress detector.

It is a thin CLI so the markdown command can shell out:

    python3 engine.py next-task               -> JSON {task, batch, scope, ...} | {}
    python3 engine.py set-state --task ID --to STATE [--branch B] [--expect-sha S]
    (also: lock/unlock, resume-check, record-failure, check-progress, reap, ...)

Markdown docs (frontmatter) are the source of truth for task/batch structure;
the ledger is the source of truth for live state transitions. Stdlib only;
uses PyYAML if present, else a minimal frontmatter parser.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hooks"))
import ledger  # noqa: E402

TERMINAL_OK = "done"
TASK_STATES = [
    "todo", "challenged", "in-progress", "implemented",
    "tested", "audited", "done", "blocked", "reverted", "needs-human",
]


# --- frontmatter parsing (markdown docs with a --- yaml block ---) ---
def _parse_frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip("\n")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(block)
        return data if isinstance(data, dict) else {}
    except Exception:
        return _mini_yaml(block)


def _mini_yaml(block: str) -> dict[str, Any]:
    """Tiny YAML subset: scalars, inline [a, b] lists, and block '- item' lists."""
    out: dict[str, Any] = {}
    key: Optional[str] = None
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and key is not None:
            out.setdefault(key, [])
            if isinstance(out[key], list):
                out[key].append(_scalar(line.lstrip()[2:]))
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            key = k.strip()
            v = v.strip()
            if v == "":
                out[key] = []  # provisional; block list may follow
            elif v.startswith("[") and v.endswith("]"):
                inner = v[1:-1].strip()
                out[key] = [_scalar(x) for x in inner.split(",") if x.strip()] if inner else []
            else:
                out[key] = _scalar(v)
    return out


def _scalar(v: str) -> Any:
    v = v.strip().strip('"').strip("'")
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    if v.isdigit():
        return int(v)
    return v


def _write_frontmatter(path: Path, fm: dict[str, Any]) -> None:
    """Rewrite only the frontmatter block, preserving the markdown body."""
    text = path.read_text(encoding="utf-8")
    body = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            body = text[end + 4 :]
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                lines.extend(f"  - {item}" for item in v)
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    path.write_text("\n".join(lines) + body, encoding="utf-8")


# --- batch / task model ---
def batches_dir(repo: Path) -> Path:
    return repo / "docs" / "batches"


def load_batches(repo: Path) -> list[dict[str, Any]]:
    bdir = batches_dir(repo)
    if not bdir.exists():
        return []
    res = []
    for d in sorted(p for p in bdir.iterdir() if p.is_dir()):
        bf = d / "BATCH.md"
        if not bf.exists():
            continue
        fm = _parse_frontmatter(bf.read_text(encoding="utf-8"))
        fm["_dir"] = d
        fm.setdefault("batch", d.name)
        fm.setdefault("state", "pending")
        fm.setdefault("depends_on", [])
        res.append(fm)
    return res


def load_task(repo: Path, batch_dir: Path, task_id: str) -> Optional[dict[str, Any]]:
    f = batch_dir / "tasks" / f"{task_id}.md"
    if not f.exists():
        return None
    fm = _parse_frontmatter(f.read_text(encoding="utf-8"))
    fm["_file"] = f
    fm.setdefault("id", task_id)
    fm.setdefault("state", "todo")
    fm.setdefault("depends_on", [])
    fm.setdefault("scope", [])
    return fm


def all_tasks(repo: Path) -> dict[str, dict[str, Any]]:
    tasks: dict[str, dict[str, Any]] = {}
    for b in load_batches(repo):
        for tid in b.get("tasks", []):
            t = load_task(repo, b["_dir"], tid)
            if t:
                t["batch"] = b["batch"]
                tasks[tid] = t
    return tasks


def _deps_done(deps: list[str], tasks: dict[str, dict[str, Any]]) -> bool:
    return all(tasks.get(d, {}).get("state") == TERMINAL_OK for d in deps)


def next_task(repo: Path) -> Optional[dict[str, Any]]:
    batches = load_batches(repo)
    done_batches = {b["batch"] for b in batches if b.get("state") == "done"}
    tasks = all_tasks(repo)
    for b in batches:
        if b.get("state") == "done":
            continue
        if not all(dep in done_batches for dep in b.get("depends_on", [])):
            continue  # an upstream batch isn't done — skip this layer
        for tid in b.get("tasks", []):
            t = tasks.get(tid)
            if not t or t.get("state") != "todo":
                continue
            if _deps_done(t.get("depends_on", []), tasks):
                return {
                    "task": tid,
                    "batch": b["batch"],
                    "scope": t.get("scope", []),
                    "design_refs": t.get("design_refs", []),
                    "file": str(t["_file"]),
                }
        # batch has todo tasks but none ready (deps pending) -> try a later
        # independent batch only if this one is fully resolved; otherwise stop.
        if any(tasks.get(tid, {}).get("state") not in (TERMINAL_OK,) for tid in b.get("tasks", [])):
            return None
    return None


def set_task_state(repo: Path, task_id: str, to: str) -> None:
    for b in load_batches(repo):
        t = load_task(repo, b["_dir"], task_id)
        if t:
            fm = {k: v for k, v in t.items() if not k.startswith("_")}
            fm["state"] = to
            _write_frontmatter(t["_file"], fm)
            return


# ----- commands -----
def cmd_lock(repo: Path, args) -> int:
    ok = ledger.acquire_lock(repo, args.session)
    if ok:
        ledger.append_event(repo, "-", "lock", f"session {args.session}")
    print(json.dumps({"acquired": ok}))
    return 0 if ok else 1


def cmd_unlock(repo: Path, args) -> int:
    ledger.release_lock(repo, args.session)
    ledger.append_event(repo, "-", "unlock", f"session {args.session}")
    print(json.dumps({"released": True}))
    return 0


def cmd_resume_check(repo: Path, args) -> int:
    at = ledger.load_state(repo).get("active_task")
    if not at:
        print(json.dumps({"action": "none", "reason": "no task in flight"}))
        return 0
    expect = at.get("expect_sha")
    actual = ledger.tree_sha(repo)
    if ledger.code_clean(repo):
        action, reason = "restart", "clean code tree -> restart task from challenged"
    elif expect and actual == expect:
        action, reason = "adopt", f"dirty code matches expect_sha {expect} -> adopt at {at.get('state')}"
    else:
        action, reason = "quarantine", "dirty code does not match expect_sha -> quarantine + needs-human"
    print(json.dumps({
        "action": action, "task": at.get("id"), "state": at.get("state"),
        "branch": at.get("branch"), "reason": reason,
    }))
    return 0


def cmd_next_task(repo: Path, args) -> int:
    import parallel  # noqa: E402  # claim-aware; == next_task with no claims (S4.1)
    nt = parallel.next_task_claim_aware(repo)
    print(json.dumps(nt or {}))
    return 0


def cmd_next_parallel_set(repo: Path, args) -> int:
    import parallel  # noqa: E402
    print(json.dumps(parallel.next_parallel_set(repo, args.n)))
    return 0


def cmd_set_state(repo: Path, args) -> int:
    if args.to not in TASK_STATES:
        print(json.dumps({"error": f"unknown state {args.to}"}))
        return 1
    set_task_state(repo, args.task, args.to)
    tasks = all_tasks(repo)
    t = tasks.get(args.task, {})
    batch = t.get("batch", "?")
    if args.to == "in-progress":
        ledger.set_active_task(
            repo, args.task, batch, args.to, t.get("scope", []),
            branch=args.branch, expect_sha=args.expect_sha,
        )
    elif args.to in (TERMINAL_OK,):
        ledger.clear_active_task(repo)
    else:
        # keep active_task fresh (state + expect_sha) without resetting attempts
        st = ledger.load_state(repo)
        if (st.get("active_task") or {}).get("id") == args.task:
            ledger.set_active_task(
                repo, args.task, batch, args.to, t.get("scope", []),
                branch=args.branch, expect_sha=args.expect_sha,
            )
    detail = f"->{args.to}"
    if args.branch:
        detail += f" branch {args.branch}"
    ledger.append_event(repo, args.task, "transition", detail,
                        sha=args.expect_sha or "-")
    print(json.dumps({"task": args.task, "state": args.to}))
    return 0


def cmd_record_failure(repo: Path, args) -> int:
    st = ledger.load_state(repo)
    at = st.get("active_task") or {}
    if at.get("id") != args.task:
        print(json.dumps({"error": "task not active"}))
        return 1
    at["attempts"] = int(at.get("attempts", 0)) + 1
    repeated = at.get("failure_signature") == args.signature
    at["failure_signature"] = args.signature
    st["active_task"] = at
    ledger.save_state(repo, st)
    ledger.append_event(repo, args.task, "transition",
                        f"implemented->tested FAILED sig={args.signature} attempt={at['attempts']}")
    print(json.dumps({"attempts": at["attempts"], "repeated": repeated}))
    return 0


def cmd_check_progress(repo: Path, args) -> int:
    cfg = _harness_cfg(repo)
    at = ledger.load_state(repo).get("active_task") or {}
    attempts = int(at.get("attempts", 0))
    escalate = attempts >= cfg["no_progress_repeat"]
    if escalate:
        ledger.append_event(repo, args.task, "needs-human",
                            f"no progress after {attempts} attempts")
    print(json.dumps({
        "escalate": escalate, "attempts": attempts,
        "cap": cfg["no_progress_repeat"],
    }))
    return 0


def _harness_cfg(repo: Path) -> dict[str, Any]:
    defaults = {"no_progress_repeat": 3, "retry_cap": 3, "revert_cycle_cap": 2}
    f = repo / ".harness.yaml"
    if f.exists():
        fm = _parse_frontmatter("---\n" + f.read_text(encoding="utf-8") + "\n---\n")
        loop = fm.get("loop") if isinstance(fm.get("loop"), dict) else {}
        for k in defaults:
            if isinstance(loop, dict) and k in loop:
                defaults[k] = loop[k]
    return defaults


# Table-driven CLI: subcommand -> per-arg (flags, kwargs). parallel/lease/merge/status handlers live in those modules (this stays a thin dispatcher).
_REQ = {"required": True}
_CLI_SPEC: dict[str, list[tuple[tuple[str, ...], dict[str, Any]]]] = {
    "lock": [(("--session",), _REQ)],
    "unlock": [(("--session",), _REQ)],
    "scope-audit": [(("--session",), _REQ)],
    "resume-check": [],
    "next-task": [],
    "next-parallel-set": [(("--n",), {"type": int, "default": 1})],
    "set-state": [(("--task",), _REQ), (("--to",), _REQ),
                  (("--branch",), {"default": None}), (("--expect-sha",), {"default": None})],
    "record-failure": [(("--task",), _REQ), (("--signature",), _REQ)],
    "check-progress": [(("--task",), _REQ)],
    "claim": [(("--task",), _REQ), (("--session",), _REQ),
              (("--branch",), {"default": None}), (("--worktree",), {"default": None})],
    "release": [(("--session",), _REQ)],
    "worktree-add": [(("--task",), _REQ)],
    "worktree-remove": [(("--task",), _REQ), (("--force",), {"action": "store_true"})],
    "heartbeat": [(("--session",), _REQ)],
    "hold-claim": [(("--session",), _REQ), (("--task",), _REQ),
                   (("--watch-pid",), {"type": int, "default": None}),
                   (("--heartbeat-minutes",), {"type": int, "default": None})],
    "reap": [],
    "merge-ready": [(("--base",), {"default": None})],
    "merge": [(("--verify",), {"default": None}), (("--base",), {"default": None})],
    "claims": [(("--human",), {"action": "store_true"})],
    "status": [(("--human",), {"action": "store_true"})],
}


def _build_parser() -> argparse.ArgumentParser:
    # --repo via a parent parser: usable before/after the subcommand; SUPPRESS so the unused copy can't clobber the given one.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=argparse.SUPPRESS)
    p = argparse.ArgumentParser(prog="engine", parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, opts in _CLI_SPEC.items():
        sp = sub.add_parser(name, parents=[common])
        for flags, kwargs in opts:
            sp.add_argument(*flags, **kwargs)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_arg = getattr(args, "repo", None)
    repo = Path(repo_arg).resolve() if repo_arg else ledger.find_repo_root()
    if repo is None:
        print(json.dumps({"error": "no repo root"})); return 1
    import parallel  # noqa: E402  (worktree/lease/merge/claims handlers live in modules)
    import lease  # noqa: E402
    import merge, claims, audit  # noqa: E402
    dispatch = {
        "lock": cmd_lock, "unlock": cmd_unlock, "resume-check": cmd_resume_check,
        "next-task": cmd_next_task, "next-parallel-set": cmd_next_parallel_set,
        "set-state": cmd_set_state,
        "record-failure": cmd_record_failure, "check-progress": cmd_check_progress,
        "claim": parallel.cmd_claim, "release": parallel.cmd_release,
        "worktree-add": parallel.cmd_worktree_add,
        "worktree-remove": parallel.cmd_worktree_remove,
        "heartbeat": lease.cmd_heartbeat, "reap": lease.cmd_reap,
        "hold-claim": lease.cmd_hold_claim,  # long-lived: BLOCKS until signalled/parent dies
        "merge-ready": merge.cmd_merge_ready, "merge": merge.cmd_merge,
        "claims": claims.cmd_claims, "status": claims.cmd_claims,
        "scope-audit": audit.cmd_scope_audit,
    }
    return dispatch[args.cmd](repo, args)


if __name__ == "__main__":
    sys.exit(main())
