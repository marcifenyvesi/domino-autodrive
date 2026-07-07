---
description: Author a BATCH manifest — a technical, layer-by-layer grouping of TASKs for the Dynamic Traceback Harness (NOT a user-story EPIC). Used for failure traceback.
argument-hint: <NNN-layer-slug> (e.g. 020-api)
allowed-tools: Read, Glob, Grep, Write, Edit
---

# /spec/create-batch — author a BATCH

A **batch is a technical grouping** that layers the implementation (data → API →
UI → …), chosen for **traceback**, not user value. It is the
unit the `/autodrive` loop advances through. This is *not* a STORY/EPIC.

## Convention

- Directory: `docs/batches/<NNN>-<layer-slug>/` (e.g. `020-api`). The numeric
  prefix sets the default layer order.
- Manifest: `docs/batches/<NNN>-<layer-slug>/BATCH.md`.
- TASKs live under `docs/batches/<NNN>-<layer-slug>/tasks/<TASK-ID>.md`.

## Inputs

1. The ratified design docs under `docs/design/` — identify which **numbered
   requirements** (`PRD-R…`, `HLD-D…`, `ARCH-M…`, `SPEC-S…`, `UI-U…`) this layer
   realizes.
2. Existing batches (for `depends_on[]` and to avoid overlap).

## Required frontmatter (the engine parses this)

```yaml
---
batch: 020-api            # must equal the directory name
layer: API endpoints      # what this batch implements + why it comes when it does
state: pending            # pending | active | done | blocked
depends_on: [010-data]    # earlier batches that must be `done` first (DAG)
complexity: normal        # normal | high  (high => 3x challenge passes)
security: false           # true => force the per-task security audit
design_refs: [SPEC-S2, SPEC-S3]   # numbered requirements this batch realizes
tasks: []                 # ordered TASK IDs — fill in as you author them
---
```

Body: a short prose description of the layer, its boundaries, and the
`traceback` block (left empty until the batch is `done`, then filled with the
commit range + audit verdict + test baseline).

## Rules

1. `batch` MUST equal the directory name.
2. `depends_on[]` across all batches MUST form a DAG (no cycles).
3. `design_refs[]` must cite IDs that exist in the design docs.
4. `tasks[]` is an *ordered* list; `/autodrive` implements them in order subject
   to each task's own `depends_on[]`.
5. Set `state: pending` for a new batch.

## Output

Write `docs/batches/<NNN>-<layer-slug>/BATCH.md`, create the `tasks/` subdir, and
report the batch ID, its layer, its `depends_on[]`, and the requirements it
covers. Then author its TASKs with `/spec/create-task`.
