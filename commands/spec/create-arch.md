---
description: Author the ARCH golden doc from the HLD — concrete modules, stores, interfaces, and tech as numbered ARCH-M# decisions; ratified via /challenge.
argument-hint: [subsystem or scope]
allowed-tools: Read, Glob, Grep, Write, Edit(docs/design/**)
---

# /spec/create-arch — author the ARCH doc

The ARCH is the third of the golden five (PRD → HLD → **ARCH** → SPEC → UI). It
is where technology choices live: concrete modules, data stores, interfaces, and
the tech that implements the HLD's conceptual design.

## Boundary (what belongs here — strictly)

- **Belongs here:** the concrete realization — named modules (`ARCH-M`), data
  stores, **structural** interfaces (protocol + direction + shape), and the tech
  stack, each with a reason.
- **Does NOT belong here:** conceptual responsibility with no technology (→ HLD);
  a behavioural pass/fail guarantee (→ SPEC).
- **Decidable test:** a shape / signature / protocol → an ARCH interface. A
  pass/fail behaviour a test asserts → a `SPEC-S`, not ARCH.
- **One fact, one doc:** cite the `HLD-D…` a module realizes (`trace[]`); never
  restate the decision's text.

## Convention

- File: `docs/design/ARCH.md`.
- Module IDs: `ARCH-M<n>` — numbered, individually addressable. SPEC statements
  and downstream TASKs `trace[]` back to these.

## Inputs

1. `docs/design/HLD.md` — the `HLD-D…` decisions and the contexts/subsystems this
   ARCH makes concrete.
2. `docs/design/PRD.md` — the Context Profile (deployment target and scaling
   horizon constrain the tech choices).

## Structure

```markdown
---
status: draft            # → ratified only after /challenge converges
---
# ARCH

## Modules (numbered)
For each: name, responsibility, and the HLD subsystem it realizes.
- ARCH-M1: <module — responsibility>   (traces HLD-D…)
- ARCH-M2: ...

## Data stores
Each store, its purpose, and the tech (with a reason tied to the Context Profile).

## Interfaces
The contracts between modules/stores: protocol, direction, and shape.

## Technology choices
The stack, with a one-line justification per choice.
```

## Rules

1. Name concrete tech — every store, interface, and stack choice is a real,
   named technology with a reason (not "a database").
2. Every `ARCH-M<n>` states a module and **traces up** to an `HLD-D…` it realizes.
3. Interfaces reference only modules / stores defined in this doc; flag any
   `HLD-D…` this ARCH doesn't yet realize (a gap to resolve before ratifying).

## Output

Write `docs/design/ARCH.md`, list the `ARCH-M…` IDs created and what each traces
to, and summarize the modules, stores, and interfaces for review.
