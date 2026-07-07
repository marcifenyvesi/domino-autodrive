---
description: Author the HLD golden doc from the PRD — bounded contexts, subsystems, and flows as numbered HLD-D# decisions; ratified via /challenge.
argument-hint: [subsystem or scope]
allowed-tools: Read, Glob, Grep, Write, Edit(docs/design/**)
---

# /spec/create-hld — author the HLD doc

The HLD is the second of the golden five (PRD → **HLD** → ARCH → SPEC → UI). It
stays conceptual: bounded contexts, subsystems, and high-level flows — no
concrete technology choices (those belong in ARCH).

## Convention

- File: `docs/design/HLD.md`.
- Design IDs: `HLD-D<n>` — numbered, individually addressable design decisions.
  ARCH modules and downstream TASKs `trace[]` back to these.

## Inputs

1. `docs/design/PRD.md` — the Context Profile and the `PRD-R…` requirements this
   design realizes.
2. Any existing architecture notes or constraints in the repo.

## Structure

```markdown
---
status: draft
---
# HLD

## Bounded contexts
The subject-matter boundaries and what each owns.

## Subsystems
The conceptual pieces inside the contexts and how they relate.

## Flows
End-to-end conceptual flows (the happy path + the key alternates).

## Design decisions (numbered)
- HLD-D1: <the decision, and which PRD-R… it serves>   (traces PRD-R…)
- HLD-D2: ...
```

## Rules

1. Keep it conceptual — no concrete tech, stores, or protocols (that is ARCH).
2. Every `HLD-D<n>` states a decision and **traces up** to a `PRD-R…` it serves.
3. Every context/subsystem/flow is anchored by at least one `HLD-D<n>`; flag any
   `PRD-R…` this HLD does not yet cover (a gap to resolve before ratifying).
4. Set `status: draft`; it becomes `ratified` only after `/challenge` converges.

## Output

Write `docs/design/HLD.md`, list the `HLD-D…` IDs created and what each traces
to, and summarize the contexts, subsystems, and flows for review.
