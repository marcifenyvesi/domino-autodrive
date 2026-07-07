---
description: Author the PRD golden doc — a Context Profile plus numbered PRD-R# requirements; ratified via /challenge.
argument-hint: [product or feature scope]
allowed-tools: Read, Glob, Grep, Write, Edit(docs/design/**)
---

# /spec/create-prd — author the PRD doc

The PRD is the first of the golden five (**PRD** → HLD → ARCH → SPEC → UI). It
names the product's intent — who it's for, where it runs, and the numbered
requirements everything downstream traces to.

## Convention

- File: `docs/design/PRD.md`.
- Requirement IDs: `PRD-R<n>` — numbered, individually addressable, testable.
  HLD/ARCH/SPEC/UI and every BATCH/TASK `trace[]` back to these.

## Inputs

1. The scope in `$ARGUMENTS` and whatever the user has stated about the product.
2. Any existing project docs, briefs, or research in the repo.

## Structure

```markdown
---
status: draft
---
# PRD

## Context Profile
- Persona: <who uses this>
- Deployment target: <where it runs — CLI / web / mobile / on-prem / …>
- Userbase size: <expected order of magnitude>
- Scaling horizon: <growth the design must survive>

## Goals & non-goals
<what this product is for, and what it explicitly is not>

## Requirements (numbered, testable)
- PRD-R1: <when X, the system SHALL Y>
- PRD-R2: ...
```

## Rules

1. The **Context Profile** is present and concrete — persona, deployment target,
   userbase size, and scaling horizon are all filled in (they steer /challenge
   and /revise-design).
2. Every requirement has a `PRD-R<n>` id and a **testable** statement ("the
   system SHALL …"), not a vibe.
3. Requirements are the sole downstream anchor — no goal or persona detail that a
   requirement does not capture is load-bearing.
4. Set `status: draft`; it becomes `ratified` only after `/challenge` converges.

## Output

Write `docs/design/PRD.md`, list the `PRD-R…` IDs created, and summarize the
Context Profile so the user can sanity-check persona/deployment/scale before
ratifying.
