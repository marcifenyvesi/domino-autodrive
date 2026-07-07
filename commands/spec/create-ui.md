---
description: Author the UI document — the fifth golden design doc (UI/UX contract) for the Dynamic Traceback Harness, with numbered, testable UI requirements that Playwright gates against.
argument-hint: [feature or screen scope]
allowed-tools: Read, Glob, Grep, Write, Edit
---

# /spec/create-ui — author the UI doc

The UI doc is the fifth of the golden five (PRD → HLD → ARCH → SPEC → **UI**). It
is the UI/UX contract: the screens, states, flows, and acceptance behaviour that
the front-end implements and that the **Playwright audit gate**
verifies.

## Convention

- File: `docs/design/UI.md`.
- Requirement IDs: `UI-U<n>.<m>` — numbered, individually addressable, testable.
  TASKs `trace[]` their acceptance criteria to these.

## Inputs

1. `docs/design/PRD.md` — the Context Profile (persona, deployment target,
   userbase, scaling) and the `PRD-R…` requirements with UI implications.
2. `docs/design/SPEC.md` — the contracts the UI consumes (`SPEC-S…`).
3. Any design references / brand or component conventions in the repo.

## Structure

```markdown
---
status: draft
---
# UI

## Principles
<the UX stance implied by the persona + deployment target>

## Screens & states
For each screen: route, purpose, the states it can be in (loading / empty /
error / populated), and the SPEC contracts it binds to.

## Flows
End-to-end interaction flows (the happy path + the key error paths).

## UI requirements (numbered, testable)
- UI-U1.1: <when X, the system SHALL show Y>   (traces PRD-R…, SPEC-S…)
- UI-U1.2: ...

## Accessibility & responsiveness
<targets: breakpoints, a11y level, keyboard/scr-reader expectations>

## Playwright contract
For each UI-U requirement that is observable in a browser: the selector/role,
the action, and the expected DOM/visual assertion. This is what the audit gate
drives.
```

## Rules

1. Every `UI-U<n>.<m>` is **testable** ("the system SHALL …"), not a vibe.
2. Requirements with a browser-observable effect get a **Playwright contract**
   entry so the audit gate can assert them.
3. Trace each UI requirement up to a `PRD-R…` and/or `SPEC-S…` where it derives
   from one.
4. Set `status: draft`; it becomes `ratified` only after `/challenge` converges.

## Output

Write `docs/design/UI.md`, list the `UI-U…` IDs created and what each traces to,
and flag any PRD requirement with UI implications that the UI doc does not yet
cover (a gap to resolve before ratifying).
