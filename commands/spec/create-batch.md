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

## Body (markdown)

```markdown
# <NNN-layer-slug> — <layer title>

<1–3 sentences: what this layer implements, its boundaries, and why it lands in
this order relative to the other batches.>

## Traceback
<!-- left empty until the batch is `done`; then fill: -->
- commit range: <first-sha>..<last-sha>
- audit verdict: <pass | pass-with-notes | fail → how resolved>
- test baseline: <suite result at close>
```

## Rules

Constraints the template comments don't already carry:

1. `depends_on[]` across **all** batches MUST form a DAG (no cycles).
2. `design_refs[]` must cite requirement IDs that **exist** in the design docs.
3. `tasks[]` is *ordered*; `/autodrive` implements them in order, subject to each
   task's own `depends_on[]`.

## Output

Write `docs/batches/<NNN>-<layer-slug>/BATCH.md`, create the `tasks/` subdir, and
report the batch ID, its layer, its `depends_on[]`, and the requirements it
covers. Then author its TASKs with `/spec/create-task`.
