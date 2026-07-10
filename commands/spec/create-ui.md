---
description: Author the UI document — the fifth golden design doc (UI/UX contract) for the Dynamic Traceback Harness, with numbered, testable UI requirements that Playwright gates against.
argument-hint: [feature or screen scope]
allowed-tools: Read, Glob, Grep, Write, Edit(docs/design/**)
---

# /spec/create-ui — author the UI doc

The UI doc is the fifth of the golden five (PRD → HLD → ARCH → SPEC → **UI**). It
is the UI/UX contract: the screens, states, flows, and acceptance behaviour that
the front-end implements and that the **Playwright audit gate**
verifies.

## Boundary (what belongs here — strictly)

- **Belongs here:** the UI/UX contract — screens, states, interaction flows, and
  **browser-observable** requirements (`UI-U#.#`), each with a Playwright
  assertion where it's visible in a browser.
- **Real-world bond:** UI is the **manifestation** end of the V — the same user
  capabilities the PRD stated as intent, now embodied on screen. That makes the
  `PRD-R` link primary and the `SPEC-S` link a supporting binding (mechanics:
  Rule 3).
- **Does NOT belong here:** behaviour asserted below the UI, i.e. API / unit
  (→ SPEC); system-level data / control flows (→ HLD); product intent (→ PRD).
- **Decidable test:** only a browser can observe it (DOM / visual / interaction)
  → `UI-U`. An API / unit test can assert it → `SPEC-S`. It's the user's
  click-path across screens → a UI flow; components exchanging data → an HLD flow.
- **One fact, one doc:** cite the `PRD-R…` / `SPEC-S…` (`trace[]`); never restate
  their text.

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
status: draft            # → ratified only after /challenge converges
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
- UI-U1.1: <when X, the system SHALL show Y>   (manifests PRD-R… ; binds SPEC-S…)
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
2. Every requirement with a browser-observable effect gets a **Playwright
   contract** entry so the audit gate can assert it.
3. Each `UI-U` **manifests** a `PRD-R…` (primary — the user capability it
   realizes) and **binds to** the `SPEC-S…` it consumes (secondary). Exception:
   derived-state requirements (loading / empty / error) manifest no PRD
   capability — they express a `SPEC-S` reality, so trace SPEC-first. Flag any
   `PRD-R…` with a user surface this doc doesn't yet manifest (a gap to resolve
   before ratifying).

## Output

Write `docs/design/UI.md`, list the `UI-U…` IDs created and what each traces to,
and summarize the screens, states, and Playwright-covered requirements for review.
