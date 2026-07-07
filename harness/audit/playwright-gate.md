# Playwright audit gate

The webapp-UI half of the audit step in `/autodrive` (§B step 6). It verifies a
TASK's UI behaviour against the **Playwright contract** in `docs/design/UI.md`
(authored by `/spec/create-ui`). A failure is a **High** finding and blocks the
task at `audited`.

## When it runs

Only for tasks that touch the UI layer — detected by either:
- the task's `scope[]` includes front-end paths (components/pages/routes), or
- the parent `BATCH.md` is the UI layer, or
- `.harness.yaml` `audit.playwright: always`.

`audit.playwright: never` disables it (e.g. a pure-backend repo).

## What it checks

For each `UI-U<n>.<m>` requirement the task's `acceptance[]` traces to, the UI
doc's Playwright contract supplies: the selector/role, the action, and the
expected DOM/visual assertion. The gate:

1. Builds/serves the app (project's dev/preview command — discovered from
   `package.json` or `.harness.yaml`).
2. Drives each contract entry with Playwright.
3. Asserts the expected post-condition (visible element, text, URL, ARIA state).
4. Maps each result back to its `UI-U…` ID so a failure is traceable to the
   requirement, not just "a test broke."

## How the loop invokes it

The `/autodrive` audit step spawns an auditor sub-agent (or runs the project's
`playwright test` if the repo already has specs):

> Drive the Playwright contract in `docs/design/UI.md` for the requirements
> `<UI-U… list>` this task implements. Report per-requirement pass/fail with the
> selector + observed vs expected. Treat any fail as a High finding.

If the repo has no Playwright setup yet, the gate is reported as **skipped (not
configured)** — it never silently passes. Add Playwright (Phase 4 of adopting
the harness in that repo) to turn the gate on.

## Relationship to the test step

- **Test step (§B step 5):** the task's own `verify[]` — unit/integration, run
  every task, "verify the code not the test."
- **Playwright gate (this doc, §B step 6):** end-to-end browser assertions of
  the *UI contract*, run only for UI tasks, as part of the audit.

They are complementary: a UI task passes its unit tests *and* the Playwright
contract before reaching `done`.
