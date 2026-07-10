---
description: Author a TASK — the markdown implementation unit for the Dynamic Traceback Harness, scoped to one BATCH, with a declared file scope[] and acceptance criteria traced to numbered requirements.
argument-hint: <BATCH-ID> <TASK-ID>
allowed-tools: Read, Glob, Grep, Write, Edit
---

# /spec/create-task — author a TASK (harness / markdown)

> This is the **harness** task author (markdown frontmatter the `/autodrive`
> engine parses). One TASK = one implementation unit the loop branches,
> implements, tests, audits, and commits.

## Convention

- File: `docs/batches/<BATCH-ID>/tasks/<TASK-ID>.md`.
- `TASK-ID`: `TASK-<NAME>` (letters, digits, hyphens), unique across the repo.

## Inputs

1. The parent `BATCH.md` (`$1`) — confirm the layer and pull its `design_refs[]`.
2. The ratified design docs the task realizes — collect the specific **numbered
   requirement IDs** (`SPEC-S2.3`, `UI-U1.4`, `PRD-R7`, …) this task satisfies.
3. Sibling TASKs in the batch (for `depends_on[]` and style).

## Required frontmatter (the engine parses this — keep keys exact)

```yaml
---
id: TASK-API-AUTH
batch: 020-api            # must be an existing batch dir
state: todo               # todo at authoring time
depends_on: [TASK-DATA-USER]   # other TASK IDs (DAG); [] if none
scope:                    # the ONLY files the implementer may create/modify
  - src/api/auth.ts       # the PreToolUse hook hard-denies anything outside this
  - tests/api/auth.test.ts
design_refs: [SPEC-S2.3, PRD-R7]   # numbered requirements (addressable)
---
```

## Body (markdown)

```markdown
# TASK-API-AUTH — <title>

## Acceptance
- A1 (traces SPEC-S2.3): <testable statement>
- A2 (traces PRD-R7): <testable statement>

## Verify
- <runnable command> — expect <result>
- npm run lint && npm run typecheck && npm run build   # STANDARDS smoke checks
- no-stub grep over changed files (run by the loop)
- insecure-pattern grep over changed files (STANDARDS §8; run by the loop)

## Reference files
- <existing files the implementer must read to match conventions>

## Notes
- <gotchas; mirrored to the ledger as they're discovered>
```

## Rules

Constraints the template above can't show (the template's inline comments are
the source of truth for the rest — don't restate them here):

1. Every `acceptance[]` item **traces** to a numbered requirement ID that
   **exists** in the design docs — this drives the ledger's commit→requirement
   traceback.
2. `scope[]` paths are repo-relative POSIX — no `..`, no absolute paths.
3. A test file goes in `scope[]`, but any change to one is **diff-flagged to the
   audit gate**.
4. `depends_on[]` across **all** TASKs (repo-wide, not just this batch) MUST form
   a DAG.
5. Tests follow `STANDARDS.md` §5.

## Output

Write the task file, append its ID to the parent `BATCH.md`'s `tasks[]` (in
implementation order), and report the scope, the requirements it traces, and its
`depends_on[]`.
