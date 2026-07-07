---
description: Author the SPEC golden doc from the ARCH — testable acceptance statements numbered SPEC-S#.#; ratified via /challenge.
argument-hint: [feature or scope]
allowed-tools: Read, Glob, Grep, Write, Edit(docs/design/**)
---

# /spec/create-spec — author the SPEC doc

The SPEC is the fourth of the golden five (PRD → HLD → ARCH → **SPEC** → UI). It
is the contract layer: the precise, testable acceptance statements that TASK
acceptance criteria `trace[]` to and that implementation is verified against.

## Convention

- File: `docs/design/SPEC.md`.
- Statement IDs: `SPEC-S<n>.<m>` — numbered, individually addressable, testable.
  Downstream TASKs `trace[]` their acceptance criteria to these.

## Inputs

1. `docs/design/ARCH.md` — the `ARCH-M…` modules and interfaces these statements
   pin down.
2. `docs/design/PRD.md` and `docs/design/HLD.md` — the upstream requirements and
   decisions each statement ultimately serves.

## Structure

```markdown
---
status: draft
---
# SPEC

## Contracts
For each module/interface: the behaviour it guarantees, grouped by concern.

## Acceptance statements (numbered, testable)
- SPEC-S1.1: <when X, the system SHALL Y>   (traces ARCH-M…, PRD-R…)
- SPEC-S1.2: ...
- SPEC-S2.1: ...

## Edge cases & error behaviour
The failure paths and boundary conditions the statements above must cover.
```

## Rules

1. Every `SPEC-S<n>.<m>` is a **testable** acceptance statement ("the system
   SHALL …") — precise enough that a test can pass or fail on it, not a vibe.
2. Each statement **traces up** to an `ARCH-M…` (and the `PRD-R…` it serves).
3. Error and boundary behaviour is specified, not just the happy path; flag any
   `ARCH-M…` this SPEC does not yet cover (a gap to resolve before ratifying).
4. Set `status: draft`; it becomes `ratified` only after `/challenge` converges.

## Output

Write `docs/design/SPEC.md`, list the `SPEC-S…` IDs created and what each traces
to, and summarize the contracts and the edge cases covered for review.
