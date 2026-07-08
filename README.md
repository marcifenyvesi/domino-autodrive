```
██████╗  ██████╗ ███╗   ███╗██╗███╗   ██╗ ██████╗
██╔══██╗██╔═══██╗████╗ ████║██║████╗  ██║██╔═══██╗
██║  ██║██║   ██║██╔████╔██║██║██╔██╗ ██║██║   ██║
██║  ██║██║   ██║██║╚██╔╝██║██║██║╚██╗██║██║   ██║
██████╔╝╚██████╔╝██║ ╚═╝ ██║██║██║ ╚████║╚██████╔╝
╚═════╝  ╚═════╝ ╚═╝     ╚═╝╚═╝╚═╝  ╚═══╝ ╚═════╝
```

# domino-autodrive

[![ci](https://github.com/marcifenyvesi/domino-autodrive/actions/workflows/ci.yml/badge.svg)](https://github.com/marcifenyvesi/domino-autodrive/actions/workflows/ci.yml)

**An enforcement layer for autonomous AI coding.** Most AI-coding frameworks help a
model *plan* — turn a prompt into a spec, a spec into a task list. This one governs
what the model *did*: it hard-denies out-of-scope edits at the tool layer, survives a
rate-limit kill by resuming from a git-committed ledger, forces every artifact through
an adversarial review that must *converge*, and traces every commit back to a numbered
requirement.

It is a Claude Code tooling layer — a set of Python engines, `PreToolUse`/`Stop` hooks,
and slash-command prompts — that turns "the agent wrote some code" into "here is the
committed, scope-bounded, adversarially-reviewed, requirement-traced record of exactly
what the agent did and why."

> **Positioning, honestly.** The crowded part of this space is *planning and
> orchestration* — spec→task pipelines and parallel worktree runners (spec-kit, Kiro,
> BMAD, Task Master, claude-flow, and a dozen worktree multiplexers). This project
> deliberately does **not** compete there. It sits one layer down, on *execution
> integrity* — the four guarantees below, which (from surveying that ecosystem) tend
> to be **rare-to-absent as *shipped, enforced* guarantees** rather than planning
> features. That's the
> whole thesis: as models get more autonomous, the scarce thing isn't help *writing*
> code — it's *proof of, and enforcement over,* what autonomous code did.

---

## The four guarantees

| # | Guarantee | Mechanism | Where |
|---|-----------|-----------|-------|
| 1 | **Scope drift is denied.** A drifting sub-agent is denied at the tool layer when it tries to edit outside its task's declared `scope[]`, and any slip is caught by the post-run audit. | `PreToolUse` hook hard-denies the write (exit 2) *before* it lands — the one hook phase that can actually block. Backed by a pre-commit guard and a post-run scope audit that re-diffs the worktree. | [`harness/hooks/scope_guard.py`](harness/hooks/scope_guard.py), [`precommit_scope.py`](harness/hooks/precommit_scope.py), `engine … scope-audit` |
| 2 | **A kill is resumable.** Rate-limit kill, crash, or `Ctrl-C` mid-run leaves a consistent, git-committed anchor to cold-start from — no lost work, no torn state. | Append-only `LEDGER.md` + `LEDGER.state.json` committed on every transition by a `Stop`/`SessionEnd` hook; resume reconciles on-disk `git status` against the last expected tree-SHA (adopt / restart / quarantine). | [`harness/hooks/ledger.py`](harness/hooks/ledger.py), [`ledger_commit.py`](harness/hooks/ledger_commit.py), [`harness/autodrive/engine.py`](harness/autodrive/engine.py) |
| 3 | **Nothing ships un-challenged.** Every research doc, design, and task set is adversarially reviewed ≥2× and must **converge** (a pass with zero new findings) before it advances. | The `/challenge` gate with convergence + oscillation detection, so review can't become a self-modifying token sink. | [`commands/challenge.md`](commands/challenge.md) |
| 4 | **Every commit traces to a requirement.** The ledger walks commit → task → acceptance-criterion → numbered `SPEC-S*` / `PRD-R*` requirement. | Numbered requirement IDs threaded through the doc hierarchy and recorded per transition in the ledger. | [`harness/schema/ledger.md`](harness/schema/ledger.md) |

> **Threat model — a guardrail against drift, not an adversarial sandbox.** The
> scope enforcement is designed to keep a *cooperative* agent inside its lane and
> to catch *accidental* drift — the common, real failure mode. It is **not** a
> containment boundary against an agent actively trying to subvert the harness:
> a few paths are trusted (`docs/`, `.claude/`, `.harness.yaml`), and
> `.harness.yaml` can name commands the engine runs. For untrusted agents, run
> the whole thing under an OS-level sandbox. See [`SECURITY.md`](SECURITY.md).

---

## `domino` — one prompt, shipped feature

`/domino "<what you want built>"` is the conductor that chains the whole pipeline and
runs to the end autonomously:

```
prompt ─▶ research (web, cited) ─▶ challenge the research ×2 (adversarial, 2nd-source)
       ─▶ design gate (touch the golden PRD→HLD→ARCH→SPEC→UI docs ONLY on real drift)
       ─▶ author batches + tasks ─▶ challenge the tasks ×2–3 (converge)
       ─▶ orchestrated parallel autodrive: next-parallel-set ▸ claim ▸ worktree
          ▸ ∥ scope-bounded sub-agents ▸ scope-audit ▸ test-gated merge ─▶ done
```

It does not reinvent the engine — it *composes* the pieces below, picking parallel
`orchestrate` mode when the engine supports it and degrading cleanly to a serial loop
when it doesn't. The single human escalation is a **PRD-level** (product-concept) change;
everything below that it resolves autonomously under a "golden-skeleton" change bar.

See [`commands/domino.md`](commands/domino.md) for the full contract.

---

## Architecture

```
  ┌─────────────────────────── slash commands (prompts) ───────────────────────────┐
  │  /domino   /autodrive   /orchestrate   /challenge   /revise-design   /spec/*     │
  └───────────────┬─────────────────────────────────────────────────────────────────┘
                  │ invoke
  ┌───────────────▼──────────── deterministic engine (Python) ──────────────────────┐
  │  engine.py   next-task DAG · state transitions · resume reconciliation           │
  │  parallel.py next-parallel-set · claim · worktree fan-out                         │
  │  lease.py    heartbeat lease · orphan/dead-holder reclaim                         │
  │  merge.py    test-gated sequential merge onto an integration branch              │
  │  claims.py   atomic scope-disjoint claim registry                                 │
  └───────────────┬─────────────────────────────────────────────────────────────────┘
                  │ enforced by
  ┌───────────────▼──────────── hooks (Claude Code events) ─────────────────────────┐
  │  scope_guard.py     PreToolUse  → hard-deny out-of-scope Edit/Write               │
  │  precommit_scope.py pre-commit  → block out-of-scope / secret-bearing commits     │
  │  ledger_commit.py   Stop/SessionEnd → commit the ledger (durable resume anchor)   │
  └───────────────┬─────────────────────────────────────────────────────────────────┘
                  │ recorded in
  ┌───────────────▼──────────── on-disk state (git-committed) ──────────────────────┐
  │  LEDGER.md  (human traceback log)   LEDGER.state.json  (frontier · locks · SHAs)  │
  └──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Quickstart

Requires **Python 3.11+** (standard library only — no third-party dependencies) and
**git** ≥ 2.5 (worktrees). Designed to run under [Claude Code](https://claude.com/claude-code).

```bash
# 1. Verify the engine + hooks on your machine (235 self-test assertions)
python3 harness/hooks/_selftest.py        # 114 assertions — hooks + scope algebra
python3 harness/autodrive/_selftest.py    # 121 assertions — engine, claims, lease, merge

# 2. Seed the harness into a target project repo
python3 harness/autodrive/init.py /path/to/your/project

# 3. From inside that repo, drive it (in Claude Code)
/domino "add rate-limited ret/backoff to the API client, with tests"
```

`domino` needs a ratified golden-doc skeleton (`PRD → HLD → ARCH → SPEC → UI`) to build
against. If you don't have one yet, the **interview on-ramp** builds it for you —
`/grill-to-design "<intent>"` grills you into a ratified skeleton (grounded in existing
code for brownfield, or the intent for greenfield), then hand off to `/domino`. This is a
deliberately *human-driven* pre-step; the `domino` run itself stays autonomous.

`init.py` is idempotent: it installs the engine + hooks, merges the two hook entries into
the target repo's `.claude/settings.json`, and creates the `docs/` doc-tree. Re-running is
safe.

### Install the commands as a Claude Code plugin

```
/plugin marketplace add marcifenyvesi/domino-autodrive
/plugin install domino-autodrive
```

The plugin installs the slash commands; the Python engine is seeded per-project by
`/autodrive init` (above).

---

## Repository layout

```
harness/
  autodrive/    engine.py, parallel.py, lease.py, merge.py, claims.py, init.py, audit.py
  hooks/        scope_guard.py, precommit_scope.py, ledger_commit.py, ledger.py, scope_algebra.py
  schema/       ledger.md, harness-yaml.md, task.md, batch.md — artifact contracts
  audit/        playwright-gate.md (webapp UI audit gate)
  STANDARDS.md  coding rules (NASA P10, anti-slop) + §7 UI/UX + §8 security minimums
commands/
  domino, autodrive, orchestrate, challenge, revise-design, grill-to-design
  spec/         create-{prd,hld,arch,spec,ui,batch,task} — golden-doc + task authors
skills/         grill-me, grilling — the human-driven interview on-ramp (see grill-to-design)
```

---

## Maturity — read this before relying on it

The **deterministic core is thoroughly unit-tested** (235 assertions, run in CI on every
push). The state machine, scope algebra, claim registry, lease/reap liveness, and
test-gated merge are exercised against real git worktrees.

What is **not** yet field-hardened is the full end-to-end *LLM loop* — an unattended
`/domino` run driving a large real project to completion. Treat this as a **reference
implementation and a working foundation**, not a turnkey product. The interesting
engineering is in the enforcement machinery, and that machinery is real and tested.

Claude Code's plugin/hook API is young and moving; the hooks target the documented
`PreToolUse` deny + `Stop`/`SessionEnd` contracts.

---

## Portability — other CLIs (Codex, Gemini)

The harness is built in two layers, and only one of them is Claude-Code-specific:

- **Tool-neutral core (ports unchanged).** The Python engine (`harness/autodrive/`)
  and the *authoritative* scope-enforcement boundary — the post-turn re-diff in
  [`harness/autodrive/audit.py`](harness/autodrive/audit.py) that re-checks the actual
  git diff against `scope[]` — are standard-library Python over git worktrees. Any
  agent CLI that can run `python3` and drive git uses them as-is; the core guarantees
  don't depend on Claude Code.
- **Claude-Code-specific driver.** The slash-command prompts (`commands/*.md`), the
  sub-agent fan-out, and the `PreToolUse`/`Stop` hook wiring target Claude Code today.

Cross-tool scope enforcement is deliberately designed as **one checker, three surfaces**
— `scope_check()` shared verbatim, with only per-tool input-parsing and deny-encoding
differing. The **Claude Code `PreToolUse` guard is implemented**; **Codex CLI
(`config.toml [hooks]`) and Gemini CLI (`.gemini/settings.json` `BeforeTool`) adapters
are documented but not yet built** — the exact wiring is in
[`harness/hooks/ADAPTER-WIRING.md`](harness/hooks/ADAPTER-WIRING.md). Porting the
*prompts* to another CLI's command/agent model is separate, per-tool authoring work.

---

## How this was built

This is an AI-assisted project, and the boundary is worth stating plainly (it's the honest
signal, and it's the point): the **workflow, architecture, and the enforcement design**
are human — distilled from a hand-run spec-driven process. The **code and prose were
authored by Claude Code** driving this very harness, then pressure-tested through the
`/challenge` gate it ships — it was built by the very method it documents.

---

## License

[MIT](LICENSE) © Márton Fenyvesi.
