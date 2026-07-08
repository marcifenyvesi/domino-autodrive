# BATCH schema

A **technical, layer-by-layer grouping** of TASKs (data → API → UI → …), chosen
for **failure traceback**, not user value — *not* a user-story EPIC. It is the
unit the `/autodrive` loop advances through. Authored by
[`/spec/create-batch`](../../commands/spec/create-batch.md); the engine parses the
**frontmatter**, humans read the **body**.

- **Directory:** `docs/batches/<NNN>-<layer-slug>/` (e.g. `020-api`). The numeric
  prefix sets the default layer order.
- **Manifest:** `docs/batches/<NNN>-<layer-slug>/BATCH.md`
- **Tasks:** `docs/batches/<NNN>-<layer-slug>/tasks/<TASK-ID>.md` (see
  [`task.md`](task.md)).

## Frontmatter (machine-parsed — keys must be exact)

```yaml
---
batch: 020-api               # MUST equal the directory name
layer: API endpoints         # what this batch implements + why it comes when it does
state: pending               # pending | active | done | blocked
depends_on: [010-data]       # earlier batches that must be `done` first (DAG)
complexity: normal           # normal | high  (high => 3 challenge passes, not 2)
security: false              # true => force the per-task security audit
design_refs: [SPEC-S2, SPEC-S3]   # numbered requirements this batch realizes
tasks: [TASK-API-AUTH, TASK-API-RATE]   # ORDERED TASK IDs the loop advances through
---
```

| Key | Type | Required | Default (engine) | Meaning |
|---|---|---|---|---|
| `batch` | string | yes | dir name | Batch ID; **must equal the directory name**. |
| `layer` | string | yes | — | What this batch implements and why it comes when it does. |
| `state` | enum | yes | `pending` | `pending` \| `active` \| `done` \| `blocked`. |
| `depends_on` | list\<string\> | no | `[]` | Earlier batch IDs that must be `done` first. Must form a DAG. |
| `complexity` | enum | no | `normal` | `normal` \| `high`; `high` raises the challenge gate to 3 passes. |
| `security` | bool | no | `false` | `true` forces the per-task security audit for this batch. |
| `design_refs` | list\<string\> | no | `[]` | Numbered requirement IDs (`PRD-R#`, `HLD-D#`, `ARCH-M#`, `SPEC-S#`, `UI-U#`) this batch realizes. |
| `tasks` | list\<string\> | no | `[]` | **Ordered** TASK IDs. The loop implements them in order, subject to each task's own `depends_on[]`. A task file not listed here is not picked up. |

> The engine applies `batch` (dir name), `state: pending`, and `depends_on: []`
> as defaults via `load_batches` (`engine.py`). `tasks[]` is what links a batch to
> its TASK files, so keep it current and ordered.

## Lifecycle (`state`)

```
pending → active → done
   └─────────────→ blocked
```

`pending` (authored, not started) → `active` (loop is working it) → `done`
(all tasks `done`); `blocked` when a task escalates to `needs-human`. Set a new
batch to `pending`; the loop owns the transitions.

## Body (human-read, not parsed)

A short prose description of the layer, its boundaries, and — once the batch is
`done` — a **`traceback`** block: the commit range, the audit verdict, and the
test baseline for the batch. Left empty until completion.

## Rules

1. `batch` MUST equal the directory name.
2. `depends_on[]` across all batches forms a DAG (no cycles).
3. `design_refs[]` cite IDs that exist in the design docs.
4. `tasks[]` is an ordered list; author the TASKs with `/spec/create-task`.
5. New batch ⇒ `state: pending`.

See also: [`task.md`](task.md) · [`ledger.md`](ledger.md) ·
[`/spec/create-batch`](../../commands/spec/create-batch.md).
