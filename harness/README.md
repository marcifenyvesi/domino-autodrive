# harness/ — Dynamic Traceback Harness assets

Installable assets for the autonomous-coding harness.

These are the **tooling** (they live here in the harness source repo).
`/autodrive init` seeds them into a *target* project repo, where the actual
docs, ledger, and code get produced.

## Phase 0 contents (the foundation)

| Path | Role |
|---|---|
| `STANDARDS.md` | Coding rules (NASA P10, anti-slop, no stubs/mocks/stales, modular, test-the-code) **plus §7 UI & UX** (platform-convention positioning, WCAG 2.2 AA numeric limits, interaction laws, layout/typography/colour, component patterns) **plus §8 Security coding minimums** (injection sinks, secrets, crypto/randomness numbers, authz/session/CSRF, anti-slopsquatting supply chain, LLM output as untrusted input — grep tier gated via `standards.insecure_markers`) — every rule sourced from a canonical primary. Canonical copy; seeded to `<target>/STANDARDS.md`; inlined into sub-agent prompts. |
| `hooks/ledger.py` | Shared library: `LEDGER.md` + `LEDGER.state.json` read/write, single-writer lock, active-task scope writer, scope matching, git/tree-sha helpers. One implementation of the on-disk grammar. |
| `hooks/scope_guard.py` | **PreToolUse** hook — hard-denies Edit/Write outside the active task's `scope[]`. Restores the lost tool-layer scope gate. |
| `hooks/ledger_commit.py` | **Stop / SessionEnd** hook — commits the two ledger files so a kill leaves a consistent resume anchor. |
| `schema/ledger.md` | `LEDGER.md` grammar + `LEDGER.state.json` JSON schema + resume reconciliation table. |
| `schema/harness-yaml.md` | `.harness.yaml` per-repo override schema. |
| `settings.snippet.json` | The two hooks wired for a target repo's `.claude/settings.json`. |

## Why these are Phase 0

The loop (Phase 1) writes code on its own. Before that is safe, two gates must
already exist: the **scope guard** (so a drifting sub-agent can't widen the blast
radius) and the **ledger commit** (so a rate-limit kill leaves a resumable
anchor). Hence they ship first.

## Phases 1–4 (built)

| Path | Role | Phase |
|---|---|---|
| `autodrive/engine.py` | Deterministic core — lock, next-ready-task (batch/task DAG), state transitions, resume reconciliation, no-progress detector. CLI. | 1 |
| `autodrive/init.py` | Idempotent seeder — installs assets + merges hooks + creates doc-tree. | 1 |
| `../commands/autodrive.md` | The loop — preflight, reconciliation, challenge gate, scope-bounded implement, test, audit, commit, ledger. | 1–2,4 |
| `../commands/revise-design.md` | Design-question → deep research (vs Context Profile) → challenge fold. | 4 |
| `../commands/spec/create-{batch,ui,task}.md` | Markdown doc authors — technical BATCH manifests and scoped TASKs. | 3 |
| `audit/playwright-gate.md` | Webapp UI audit gate driving the UI doc's contract. | 4 |

## Tests

```bash
python3 harness/hooks/_selftest.py      # 114 assertions
python3 harness/autodrive/_selftest.py  # 121 assertions
```

## Not yet field-proven

The deterministic core is unit-tested; a full end-to-end `/autodrive` run against
a real project (the LLM loop driving real code) is the first-real-use shakedown.

## Hooks — contract & local test

`scope_guard.py` reads the PreToolUse JSON on stdin; **exit 0** allows, **exit 2
+ stderr** denies. `ledger_commit.py` always exits 0 (a checkpoint must never
block session stop). Both fail-open on malformed input. Quick local check:

```bash
python3 harness/hooks/_selftest.py
```
