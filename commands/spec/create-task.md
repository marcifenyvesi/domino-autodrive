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

1. Every `acceptance[]` item **traces** to a real numbered requirement ID — this
   is what makes the ledger's commit→requirement traceback work.
2. `scope[]` lists repo-relative POSIX paths (no `..`, no absolute paths). Keep
   it tight: the loop will refuse writes outside it.
3. **Test files belong in `scope[]`** (the implementer writes them), but any
   change to a test file is diff-flagged to the audit gate.
4. `depends_on[]` across all TASKs MUST form a DAG.
5. `state: todo` for a new task.
6. Tests must follow `STANDARDS.md` §5 — one per acceptance criterion, exact
   assertions; on failure the implementer fixes the **code**, not the test.

## Output

Write the task file, append its ID to the parent `BATCH.md`'s `tasks[]` (in
implementation order), and report the scope, the requirements it traces, and its
`depends_on[]`.
