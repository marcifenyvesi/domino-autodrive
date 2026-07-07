# ADAPTER-WIRING.md — one scope checker, three pre-tool surfaces

**Deliverable scope (SPEC §S8.3 A4).** This document plus the
reusable checker in `scope_guard.py` are the deliverable. The Claude Code
`PreToolUse` guard is the **primary, implemented** surface; the Codex and Gemini
adapters are *documented wiring only* — their per-tool binaries are wired later
against the same function. What matters is that the **scope decision is identical
across all three**: the same `scope_check(...)` call; only the input parsing and
the deny-encoding differ per tool.

## The one checker

```python
# harness/hooks/scope_guard.py
scope_check(repo_root, session, paths) -> {
    "clean": bool,            # True  => allow
    "violations": [rel, ...], # non-empty => deny; the offending repo-rel paths
    "scope": list | None,     # the enforced claim scope (None => no claim/fail-open)
    "task_id": str,
}
scope_violation(repo_root, session, rel_path) -> bool   # boolean convenience
```

- **Session resolution.** `session` is the id of the claim doing the write,
  resolved from its worktree (`cwd → git worktree root → claim.worktree`, reusing
  `precommit_scope.worktree_root`/`resolve_claim`). Passing it enforces THAT
  claim's scope in parallel mode; passing `None` collapses to the singleton
  `active_scope` (0/1-claim behaviour, byte-identical to the pre-feature guard).
- **Decision.** A path violates when it is outside `claim.scope ∪
  ledger.ALWAYS_ALLOWED`. `is_always_allowed` (docs/, reviews/, `.claude/`, …) is
  honoured before scope.
- **Fail-open.** No resolvable claim (`scope is None`) ⇒ `clean: True`. A
  developer's own manual edit is never blocked.

Every surface below calls this ONE function. The adapter is a thin shell: parse
the tool's input shape → `scope_check(...)` → encode allow/deny in the tool's
output shape.

## 1. Claude Code — `PreToolUse` (primary, implemented)

Runs before the permission check; a deny stops the write before it happens
(`PostToolUse` cannot — the write already landed).

- **Input:** hook JSON on **stdin** —
  `{"tool_name": "Edit", "tool_input": {"file_path": "..."}, "cwd": "..."}`
  (`notebook_path` for `NotebookEdit`).
- **Output:** **exit 0 = allow; exit 2 + stderr = deny** (stderr is surfaced to
  the model as the block reason). Equivalent JSON form:
  `{"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "deny", "permissionDecisionReason": "..."}}`.
- **Wiring:** `.claude/settings.json` `hooks.PreToolUse` matcher on
  `Edit|Write|MultiEdit|NotebookEdit` → `python3 harness/hooks/scope_guard.py`.
- **Version note:** at least one Claude Code version has ignored `deny` for
  `Edit` — smoke-test the installed build (echo an out-of-scope Edit payload,
  assert exit 2). Docs: https://code.claude.com/docs/en/hooks

This is exactly what `scope_guard.py::main()` implements today.

## 2. Codex CLI — `PreToolUse` (documented; binary later)

Codex added a Claude-parity `PreToolUse` hook. OpenAI frames it as a *"guardrail
rather than a complete enforcement boundary"* — its primary containment is the OS
sandbox (`sandbox_mode = "workspace-write"` rooted at the worktree). The scope
hook is the same allow/deny decision on top.

- **Input:** hook payload with the tool name + arguments (the edited path) +
  invocation `cwd`.
- **Output:** Claude-parity — **exit 2 to deny** (or the `decision: "deny"` JSON
  form); exit 0 to allow.
- **Wiring:** `config.toml` `[hooks]` → a matcher on the edit tools invoking a
  thin adapter that extracts `file_path` + `cwd`, calls the **same**
  `scope_check(repo, session, [rel])`, and exits 2 on `not clean`.
- Docs: https://developers.openai.com/codex/hooks and
  https://developers.openai.com/codex/concepts/sandboxing

## 3. Gemini CLI — `BeforeTool` (documented; binary later)

Gemini's pre-tool hook is `BeforeTool`, configured with regex matchers.

- **Input:** the tool call (name + args, including the target path) and working
  directory, per the hook payload.
- **Output:** **exit 2** or JSON **`{"decision": "deny"}`** to block; allow
  otherwise. (Note the key is `decision`, not Claude's `permissionDecision`.)
- **Wiring:** `.gemini/settings.json` `hooks.BeforeTool` with a regex matcher on
  the edit/write tools → adapter that maps the payload to `file_path` + `cwd`,
  calls the **same** `scope_check(...)`, and emits `{"decision": "deny"}` /
  exit 2 on a violation.
- Docs: https://github.com/google-gemini/gemini-cli/blob/main/docs/hooks/index.md

## Output-shape summary

| Surface     | Hook          | Config                    | Input      | Deny encoding                                   |
| ----------- | ------------- | ------------------------- | ---------- | ----------------------------------------------- |
| Claude Code | `PreToolUse`  | `.claude/settings.json`   | stdin JSON | exit 2 + stderr / `permissionDecision: "deny"`  |
| Codex CLI   | `PreToolUse`  | `config.toml [hooks]`     | payload    | exit 2 / `decision: "deny"`                     |
| Gemini CLI  | `BeforeTool`  | `.gemini/settings.json`   | payload    | exit 2 / `{"decision": "deny"}`                 |

Only the two outer columns differ per tool. The middle — *is this path in this
session's scope?* — is one function, `scope_check`, shared verbatim.

## Why the tool hooks are not the boundary

All three vendors call these **guardrails, not boundaries**, and git's
`pre-commit` is `--no-verify`-bypassable. The authoritative boundary is the
**harness-side post-turn re-diff audit** (`autodrive/audit.py`) that re-checks the
turn's actual diff against `scope[]` and rolls back/rejects violators — the only
layer no agent can `--no-verify` around. These pre-tool adapters are the fast,
in-the-loop feedback that keeps a well-behaved agent inside its lane; the audit is
the layer that *enforces* it. All of them call the same `scope_check`.
