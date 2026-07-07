#!/usr/bin/env python3
"""`/autodrive init` seeder — install the harness into a target repo.

Idempotent: safe to re-run; never clobbers an existing STANDARDS.md / .harness.yaml
/ design docs. Copies the harness assets, merges the two load-bearing hooks into
.claude/settings.json, and creates the doc-tree + ledger skeleton.

    python3 init.py [--target <repo>] [--check]

--check is a dry run (prints the plan, writes nothing). Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HARNESS_SRC = Path(__file__).resolve().parent.parent  # the harness/ dir
HOOK_CMD = '{py} "$CLAUDE_PROJECT_DIR/.claude/harness/{rel}"'
DEFAULT_PY = "python3"

DESIGN_DOCS = ["PRD", "HLD", "ARCH", "SPEC", "UI"]

GITIGNORE_WORKTREES = ".worktrees/"  # S5.1 — per-task worktrees, never tracked
PRECOMMIT_MARKER = "# >>> autodrive precommit-scope (managed) >>>"
PRECOMMIT_END = "# <<< autodrive precommit-scope (managed) <<<"

STARTER_HARNESS_YAML = """# .harness.yaml — see harness/schema/harness-yaml.md for the full schema
challenge:
  min_passes: 2
  complex_passes: 3
loop:
  retry_cap: 3
  no_progress_repeat: 3
  revert_cycle_cap: 2
audit:
  security_per_task: auto
  playwright: auto
standards:
  max_function_lines: 60
  max_file_lines: 400
  max_complexity: 10
  max_nesting: 4
parallel:
  max: 4
  lease_ttl_minutes: 90
  heartbeat_minutes: 30
worktree:
  # link: [node_modules]   # symlinked into each worktree (example)
  copy: []
  ready: ""
"""


def _plan(msg: str, check: bool) -> None:
    print(("would " if check else "") + msg)


def _hook_block(py: str) -> dict:
    def cmd(rel: str) -> dict:
        return {"type": "command", "command": HOOK_CMD.format(py=py, rel=rel)}

    return {
        "PreToolUse": [{
            "matcher": "Edit|Write|MultiEdit|NotebookEdit",
            "hooks": [cmd("hooks/scope_guard.py")],
        }],
        "Stop": [{"hooks": [cmd("hooks/ledger_commit.py")]}],
        "SessionEnd": [{"hooks": [cmd("hooks/ledger_commit.py")]}],
    }


def _merge_hooks(settings: dict, block: dict) -> bool:
    """Merge our hook entries, de-duped by command string. Returns changed?."""
    changed = False
    hooks = settings.setdefault("hooks", {})
    for event, entries in block.items():
        existing = hooks.setdefault(event, [])
        existing_cmds = {
            h.get("command")
            for e in existing for h in e.get("hooks", [])
        }
        for entry in entries:
            new_cmds = {h.get("command") for h in entry["hooks"]}
            if new_cmds & existing_cmds:
                continue  # already wired
            existing.append(entry)
            changed = True
    return changed


def _ensure_gitignore_worktrees(target: Path, check: bool) -> None:
    """S5.1 — make sure `.worktrees/` is gitignored (idempotent, create if needed)."""
    gi = target / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
    if any(ln.strip() == GITIGNORE_WORKTREES for ln in existing.splitlines()):
        _plan(f"keep existing .gitignore entry {GITIGNORE_WORKTREES}", check)
        return
    _plan(f"add {GITIGNORE_WORKTREES} to .gitignore", check)
    if not check:
        prefix = existing + ("\n" if existing and not existing.endswith("\n") else "")
        gi.write_text(prefix + GITIGNORE_WORKTREES + "\n", encoding="utf-8")


def _precommit_shim(py: str) -> str:
    return (
        "#!/bin/sh\n"
        f"{PRECOMMIT_MARKER}\n"
        "# Installed by autodrive init.py — scope enforcement on every commit.\n"
        f'DIR="${{CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}}"\n'
        f'exec {py} "$DIR/.claude/harness/hooks/precommit_scope.py"\n'
        f"{PRECOMMIT_END}\n"
    )


def _install_precommit(target: Path, check: bool, py: str) -> None:
    """S8.1 — install the scope pre-commit hook. Never clobbers a foreign hook."""
    if not (target / ".git").is_dir():
        _plan("skip pre-commit hook (no .git directory)", check)
        return
    hook = target / ".git" / "hooks" / "pre-commit"
    if hook.exists():
        content = hook.read_text(encoding="utf-8", errors="replace")
        if PRECOMMIT_MARKER in content:
            _plan("keep existing autodrive pre-commit hook", check)
            return
        print(f"warning: {hook} exists and is not autodrive-managed — leaving it "
              "untouched; wire precommit_scope.py into it manually")
        return
    _plan("install .git/hooks/pre-commit (scope enforcement)", check)
    if not check:
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text(_precommit_shim(py), encoding="utf-8")
        hook.chmod(0o755)


def seed(target: Path, check: bool, py: str = DEFAULT_PY) -> int:
    target = target.resolve()
    if not (target / ".git").exists():
        print(f"warning: {target} is not a git repo root (no .git)")

    # 1. copy harness assets -> .claude/harness/
    dst = target / ".claude" / "harness"
    for sub in ("hooks", "autodrive", "schema"):
        s = HARNESS_SRC / sub
        if s.exists():
            _plan(f"copy harness/{sub} -> .claude/harness/{sub}", check)
            if not check:
                shutil.copytree(s, dst / sub, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("_selftest.py", "__pycache__"))
    for f in ("STANDARDS.md", "settings.snippet.json"):
        if (HARNESS_SRC / f).exists():
            _plan(f"copy harness/{f} -> .claude/harness/{f}", check)
            if not check:
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copy2(HARNESS_SRC / f, dst / f)

    # 2. seed STANDARDS.md at repo root (don't clobber)
    std = target / "STANDARDS.md"
    if std.exists():
        _plan("keep existing STANDARDS.md (not overwritten)", check)
    else:
        _plan("seed STANDARDS.md at repo root", check)
        if not check:
            shutil.copy2(HARNESS_SRC / "STANDARDS.md", std)

    # 3. merge hooks into .claude/settings.json
    settings_path = target / ".claude" / "settings.json"
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"warning: {settings_path} is not valid JSON — not touching hooks")
            settings = None
    if settings is not None:
        block = _hook_block(py)
        if check:
            tmp = json.loads(json.dumps(settings))  # copy
            _plan("wire PreToolUse scope-guard + Stop/SessionEnd ledger hooks"
                  if _merge_hooks(tmp, block) else "hooks already wired", check)
        else:
            if _merge_hooks(settings, block):
                settings_path.parent.mkdir(parents=True, exist_ok=True)
                settings_path.write_text(json.dumps(settings, indent=2) + "\n",
                                         encoding="utf-8")
                print("wired hooks into .claude/settings.json")
            else:
                print("hooks already wired")

    # 4. doc-tree + ledger skeleton
    for name in DESIGN_DOCS:
        p = target / "docs" / "design" / f"{name}.md"
        if not p.exists():
            _plan(f"create docs/design/{name}.md (skeleton)", check)
            if not check:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f"---\nstatus: draft\n---\n# {name}\n\n_TODO: author via "
                             f"/spec/create-{name.lower()} and challenge._\n", encoding="utf-8")
    bdir = target / "docs" / "batches"
    if not bdir.exists():
        _plan("create docs/batches/", check)
        if not check:
            bdir.mkdir(parents=True, exist_ok=True)
            (bdir / ".gitkeep").write_text("", encoding="utf-8")
    led = target / "docs" / "LEDGER.md"
    if not led.exists():
        _plan("create docs/LEDGER.md", check)
        if not check:
            led.write_text("# LEDGER — traceback log\n\n", encoding="utf-8")
    state = target / "docs" / "LEDGER.state.json"
    if not state.exists():
        _plan("create docs/LEDGER.state.json", check)
        if not check:
            state.write_text(json.dumps({
                "version": 1, "lock": None, "active_task": None,
                "frontier": {"active_batch": None, "last_event_ts": None},
            }, indent=2) + "\n", encoding="utf-8")

    # 5. starter .harness.yaml
    hy = target / ".harness.yaml"
    if hy.exists():
        _plan("keep existing .harness.yaml", check)
    else:
        _plan("write starter .harness.yaml", check)
        if not check:
            hy.write_text(STARTER_HARNESS_YAML, encoding="utf-8")

    # 6. worktree seeding (S5.1) + pre-commit scope hook (S8.1)
    _ensure_gitignore_worktrees(target, check)
    _install_precommit(target, check, py)

    print("\n" + ("dry run — nothing written." if check else "init complete."))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autodrive-init")
    p.add_argument("--target", default=".")
    p.add_argument("--check", action="store_true")
    p.add_argument("--py", default=DEFAULT_PY)
    a = p.parse_args(argv)
    return seed(Path(a.target), a.check, a.py)


if __name__ == "__main__":
    sys.exit(main())
