---
description: Author the PRD golden doc — a Context Profile plus numbered PRD-R# requirements; ratified via /challenge.
argument-hint: [product or feature scope]
allowed-tools: Read, Glob, Grep, Write, Edit(docs/design/**)
---

# /spec/create-prd — author the PRD doc

The PRD is the first of the golden five (**PRD** → HLD → ARCH → SPEC → UI). It
names the product's intent — who it's for, where it runs, and the numbered
requirements everything downstream traces to.

## Boundary (what belongs here — strictly)

- **Belongs here:** product intent — the Context Profile (who / where / scale)
  and **product-observable, solution-agnostic** requirements (`PRD-R`, black-box:
  "a user can reset their password").
- **Real-world bond:** the UI doc is this PRD's manifestation — the other end of
  the V. A `PRD-R` with a user-facing surface is only *realized* once a `UI-U`
  manifests it (the UI doc flags the uncovered ones).
- **Does NOT belong here:** internal structure, technology, modules, or
  component-level behaviour (→ HLD / ARCH / SPEC). A requirement that names an
  internal part or a testable component behaviour is a `SPEC-S`, not a `PRD-R`.
- **Decidable test:** only a user / operator can observe it as product behaviour
  → `PRD-R`. It names or implies an internal module, interface, or technology →
  it belongs downstream.
- **One fact, one doc:** downstream docs **cite** these `PRD-R` IDs (`trace[]`);
  they never copy the requirement text.

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
status: draft            # → ratified only after /challenge converges
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
   userbase size, and scaling horizon all filled in (they steer /challenge and
   /revise-design).
2. Every requirement has a `PRD-R<n>` id and a **testable** "SHALL" statement,
   not a vibe.
3. Requirements are the sole downstream anchor — no goal or persona detail a
   requirement doesn't capture is load-bearing.

## Output

Write `docs/design/PRD.md`, list the `PRD-R…` IDs created, and summarize the
Context Profile so the user can sanity-check persona/deployment/scale before
ratifying.
