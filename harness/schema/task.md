# TASK schema

The **implementation unit** the `/autodrive` loop advances through: one TASK =
one thing the loop branches, implements, tests, audits, and commits. Authored by
[`/spec/create-task`](../../commands/spec/create-task.md); the engine parses the
**frontmatter**, humans/agents read the **body**.

- **Location:** `docs/batches/<NNN>-<layer-slug>/tasks/<TASK-ID>.md`
- **Discovered via:** the parent `BATCH.md`'s ordered `tasks[]` — a task file not
  listed there is not picked up by the loop.

## Frontmatter (machine-parsed — keys must be exact)

```yaml
---
id: TASK-API-AUTH               # TASK-<NAME>, unique across the repo
batch: 020-api                  # the batch dir this task belongs to
state: todo                     # lifecycle state (see below); `todo` at authoring
depends_on: [TASK-DATA-USER]    # other TASK IDs; must form a DAG; [] if none
scope:                          # the ONLY files the implementer may create/modify
  - src/api/auth.ts             # PreToolUse hook hard-denies writes outside this
  - tests/api/auth.test.ts
design_refs: [SPEC-S2.3, PRD-R7]  # numbered requirement IDs this task realizes
---
```

| Key | Type | Required | Default (engine) | Meaning |
|---|---|---|---|---|
| `id` | string | yes | file stem | `TASK-<NAME>` (letters/digits/hyphens), unique repo-wide. |
| `batch` | string | yes | — | Batch dir the task belongs to; set from the parent when loaded. |
| `state` | enum | yes | `todo` | Lifecycle state (below). Advanced **only** by `engine set-state`. |
| `depends_on` | list\<string\> | no | `[]` | Other TASK IDs that must be `done` first. Must form a DAG. |
| `scope` | list\<string\> | no | `[]` | Repo-relative POSIX paths the implementer may touch. No `..`, no absolute paths. Enforced by the scope guard + audit. |
| `design_refs` | list\<string\> | no | `[]` | Numbered requirement IDs (`PRD-R#`, `HLD-D#`, `ARCH-M#`, `SPEC-S#.#`, `UI-U#.#`) — the traceback anchors. |

> The engine applies the defaults above via `load_task` (`engine.py`); an omitted
> key is not an error, but `id`, `scope`, and `design_refs` are what make the
> loop and the traceback meaningful, so author them explicitly.

## Lifecycle (`state`)

```
todo → challenged → in-progress → implemented → tested → audited → done
                         |              |           |        |
                         +----(revert)--+-----------+--------+--> reverted --> todo
                         +--> blocked (retry cap / audit ≥ High) --> needs-human
```

`todo` `challenged` `in-progress` `implemented` `tested` `audited` `done`
`reverted` `blocked` `needs-human` — the closed set the engine transitions
between. Author a new task as `todo`; never hand-edit `state` past `todo` (the
loop owns transitions and records each one in the ledger).

## Body (human/agent-read, not parsed)

```markdown
# TASK-API-AUTH — <title>

## Acceptance
- A1 (traces SPEC-S2.3): <testable statement>
- A2 (traces PRD-R7): <testable statement>

## Verify
- <runnable command> — expect <result>
- npm run lint && npm run typecheck && npm run build   # STANDARDS smoke checks

## Reference files
- <existing files the implementer must read to match conventions>

## Notes
- <gotchas; mirrored to the ledger as they're discovered>
```

- **Acceptance** items each *trace* to a `design_refs` ID — this is what makes the
  ledger's `commit → task → acceptance → requirement` walk work.
- **Verify** lists runnable checks (plus the STANDARDS smoke checks the loop adds:
  no-stub grep, insecure-pattern grep, build/lint/typecheck).
- **Test files belong in `scope[]`**, but any test-file change is diff-flagged to
  the audit gate.

## Rules

1. Every acceptance item traces to a real numbered requirement ID.
2. `scope[]` is repo-relative POSIX, tight, no `..`/absolute paths.
3. `depends_on[]` across all TASKs forms a DAG (no cycles).
4. New task ⇒ `state: todo`.

See also: [`batch.md`](batch.md) · [`ledger.md`](ledger.md) ·
[`/spec/create-task`](../../commands/spec/create-task.md).
