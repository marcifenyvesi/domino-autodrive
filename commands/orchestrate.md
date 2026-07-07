---
description: Orchestrate scope-disjoint TASKs in parallel from one session — fan out worktree-isolated subagents over the claim/scope/worktree/scope-audit/merge machinery. The single-session sibling of `run --parallel`: no CLI fleet, no lease/holder/reaper. Off by default; additive.
argument-hint: [run | status] (default: run)
allowed-tools: Read, Glob, Grep, Edit, Write, Bash, Agent, Skill
---

# /orchestrate — single-session subagent fan-out

Design + rationale: `docs/design/SPEC.md` §S11 (R-15). This is the **single Claude
Code session** variant of the fleet path in `commands/autodrive.md` §C: instead of
N concurrent CLI agents each running the whole loop, **one** orchestrator session
claims scope-disjoint tasks, provisions a worktree per task, and spawns **Task-tool
subagents** (Agent calls) — one per task — that implement inside their own worktree.

```
ENGINE=".claude/harness/autodrive/engine.py"      # seeded by `/autodrive init`
python3 "$ENGINE" <subcommand> ...                  # all return JSON on stdout
```

> **Golden rule of resumability:** trust the *ledger files*, never conversation
> memory. After any restart, re-derive state from `python3 "$ENGINE" status`
> (the `claims` alias, SPEC-S9.2). The committed ledger is authoritative.

This mode reuses the engine's `claim` / scope-guard / `worktree-add` /
`scope-audit` / `merge` machinery verbatim. It does **not** use the
holder / lease / reaper layer (SPEC-S6) — see §No holder below.

---

## Purpose

One orchestrator session drives worktree-isolated subagents over scope-disjoint
tasks. The orchestrator is the **sole ledger writer**: it claims each task *on
behalf of* its subagent, provisions the worktree, spawns the subagent confined to
that worktree, and on the subagent's return runs the authoritative `scope-audit`,
marks the task `done`, releases the claim, and removes the worktree. Because there
is exactly one writer, there are **no claim races** — the atomic-claim primitive is
a safety net here, not load-bearing (contrast §C's N-CLI fleet, where independent
processes race for the same task).

---

## Preconditions

- **Autodrive target seeded.** `.claude/harness/autodrive/engine.py` exists (run
  `/autodrive init` first). The engine is the **frozen external snapshot** —
  see §Back-compat on when this mode's verbs go live.
- **Design ratified.** `docs/design/PRD.md` exists and is not `status: draft`
  (never invent design).
- **Tasks exist** with declared `scope[]` and `verify[]`, in a batch DAG.
- **`parallel.max`** is set in `.harness.yaml` (default 4; Anthropic's 3–4
  worktree guidance — ≥5 hits rate limits and is unreviewable). K never exceeds it.
- **Acquire the lock:** `python3 "$ENGINE" lock --session "$CLAUDE_SESSION_ID"`.
  If `acquired:false`, another loop holds it → STOP ("autodrive already running
  here."). Release with `unlock` at wrap-up.

---

## A. `run` — the orchestrator loop (SPEC-S11.1)

Each **wave**:

1. **Pick a disjoint set.** `python3 "$ENGINE" next-parallel-set --n K`
   (K ≤ `parallel.max`) → up to K ready tasks that are mutually scope-disjoint AND
   disjoint from every live claim, in DAG order honouring `depends_on[]`
   (SPEC-S4.2). Empty → no parallelizable frontier remains → go to the **Merge
   phase**, then to **Wrap-up**.

2. **Claim + provision, per task** (orchestrator writes; the subagent never
   touches the ledger):
   - `python3 "$ENGINE" claim --session <label> --task <id>` — atomically claim
     the task in the shared registry. Use a **per-task session label** (e.g.
     `orch-<id>`) so the later `scope-audit`/`release` target exactly this claim
     (`release` takes `--session` only). One winner per task.
   - `python3 "$ENGINE" worktree-add --task <id>` — creates `.worktrees/<id>` on
     branch `task/<id>` (`link`/`copy`/`ready` provisioning per `.harness.yaml
     worktree:`). `.worktrees/` is gitignored.
   - `python3 "$ENGINE" set-state --task <id> --to in-progress --branch task/<id>`
     — records the active `scope[]` the path-based PreToolUse guard enforces for
     *this* worktree (SPEC-S8.3 / S11.3).

3. **Spawn the K subagents CONCURRENTLY.** In **one** message, issue K Agent
   (Task) calls — one per claimed task — each carrying the **subagent briefing
   template** below (its worktree path, `scope[]`, task-doc path, verify commands).
   Never exceed `parallel.max` live subagents.

4. **On each subagent's return** (per task):
   - **Authoritative boundary FIRST** (SPEC-S8.4, before accepting anything):
     `python3 "$ENGINE" scope-audit --session <label>` re-diffs the worktree's
     branch vs base (staged + untracked) against the claimed `scope[]` and the
     sensitive-path deny-list, rejecting/rolling back any out-of-scope change (or
     marking `needs-human`). **This is the authoritative catch** — never accept a
     subagent's turn without it (see §Enforcement honesty).
   - On a clean audit: `python3 "$ENGINE" set-state --task <id> --to done`.
   - `python3 "$ENGINE" release --session <label>` — drop the claim (registry
     entry + its `docs/.locks/<id>.claim`).
   - `python3 "$ENGINE" worktree-remove --task <id>` — `git worktree remove` +
     `prune` (`--force` only for a deliberately discarded dirty tree; never
     `rm -rf`).

5. **After the wave — Merge phase.** Once the wave's claims are all released,
   integrate the completed branches. Merges are **sequential and verify-gated**
   (SPEC-S7.2):
   - `python3 "$ENGINE" merge-ready [--base <integration-branch>]` → the
     `task/<id>` branches whose task is `done` and not yet merged.
   - `python3 "$ENGINE" merge [--verify "<cmd>"] [--base <integration-branch>]`
     merges them **one at a time**, running the repo verify after each. Disjoint
     scopes make this conflict-free by construction, but the per-merge verify still
     catches **semantic** conflicts a clean textual merge misses (SPEC-S7.4). On a
     git conflict OR a failing verify, `merge` **stops**, leaves already-merged
     branches intact, and emits `needs-human` for the offending branch — it never
     auto-resolves. Escalate that branch; the rest wait for the next merge run.

6. **Loop** back to step 1 until `next-parallel-set` returns no tasks.

**Honour the batch DAG.** Only tasks whose `depends_on[]` are satisfied are ever
returned; when every task in a batch is terminal (`done`/merged), mark the batch
`done` and record its `traceback` (commit range, audit verdict, test baseline) in
`BATCH.md`.

**Wrap-up.** `python3 "$ENGINE" unlock --session "$CLAUDE_SESSION_ID"`. Report:
tasks completed, any `needs-human` (with the cited doc to edit), the next ready
frontier, and any pending merge escalations.

---

## B. Subagent briefing template (SPEC-S11.2)

Paste this into each Agent (Task) call, substituting `<id>`, `<scope-list>`, and
`<task-doc-path>`. It is everything a subagent needs to work in isolation — the
orchestrator has already claimed the task and created the worktree.

```
You are implementing TASK <id> in an ISOLATED git worktree.

WORKTREE (your entire world):  .worktrees/<id>/
BRANCH (already checked out):  task/<id>
TASK DOC:                      <task-doc-path>
YOUR FILE SCOPE (the ONLY files you may create/modify):
  <scope-list>

WHAT TO DO
1. Read the task doc. Implement its acceptance criteria, editing ONLY the
   scope[] files above, ALL inside .worktrees/<id>/.
2. Inline STANDARDS.md applies (it does not auto-load) — follow it.
3. Run the task's verify[] commands INSIDE .worktrees/<id>/. Fix the code
   (not the test) until green.
4. Commit only your scope[] files on branch task/<id>:
     git add <scope-list> && git commit -m "<commit_prefix> <id> — <title>"
5. Report what you did and your verify results. Do NOT release your claim,
   remove the worktree, or merge — the orchestrator owns all ledger writes.

HARD PROHIBITIONS (a breach fails the task at the orchestrator's post-turn audit):
- NEVER `git commit --no-verify` / `git commit -n` — the pre-commit scope hook
  MUST run (SPEC-S8.5). Bypassing it is a defect, not a shortcut.
- NEVER `cd` (or write) outside .worktrees/<id>/. Your cwd stays in the worktree.
- NEVER run any external `git push` or `git fetch` — no network git, ever.
- NEVER `git stash` (the reflog is shared across worktrees, SPEC-S5.4) and never
  touch another task's worktree or files outside your scope[].

The path-based PreToolUse guard hard-denies writes outside your worktree/scope,
and the orchestrator re-audits your whole diff before accepting it — so staying in
bounds is the only way your work lands.
```

---

## No holder (SPEC-S11.4)

This mode does **NOT** launch `hold-claim` and does **not** depend on the
lease / heartbeat / reaper layer (SPEC-S6). There is no long-lived holder process
per task: the orchestrator observes each subagent's completion **directly** (the
Agent call returns) and `release`s that claim itself, in step 4. No `heartbeat`
calls are needed — a claim lives exactly as long as its subagent runs.

- **Orchestrator-death cleanup** falls to the existing backstop, not to a lease:
  if the orchestrator session itself dies mid-wave, its worktrees and claims are
  stale and are cleaned by `python3 "$ENGINE" reap` / `git worktree prune` (the
  same mechanism §C relies on) — but that is a recovery path, not this mode's
  primary mechanism. In the normal case every claim is released and every worktree
  removed by the orchestrator before it exits.

---

## Enforcement honesty

Confinement is enforced in two layers, and it matters which one is authoritative:

- The **path-based PreToolUse guard** (SPEC-S11.3) is a **fast-fail front line**.
  It resolves each write against the claim owning the *target file's* worktree
  (longest-prefix match under `.worktrees/<id>`). But it can **fail open**: if a
  subagent breaches confinement — e.g. `cd`s into the main repo and writes there —
  the target path is under *no* registered worktree, cwd is the main repo, and with
  ≥2 live claims the singleton view is `None`, so the guard cannot attribute the
  write and lets it through.
- The **authoritative catch is the post-turn `scope-audit --session <label>`**
  (SPEC-S8.4), run in step 4 **before** the orchestrator accepts the turn. It
  re-diffs the whole worktree branch against the claimed `scope[]` + deny-list and
  **rejects the task before the change is accepted** — the layer no `--no-verify`
  can evade.

So: **confinement is the subagent's responsibility; the audit is the harness's
safety net.** A confinement breach costs a wasted turn (the audit rejects it), not
a silent out-of-scope commit. Never treat a subagent's self-reported "done" as
truth without the `scope-audit`.

---

## Sole-writer property

The orchestrator is the **only** ledger writer — it claims, sets state, releases,
and merges on behalf of every subagent; subagents only touch code inside their
worktree. Consequently there are **no claim races** in this mode: each task has one
claimant (the orchestrator) at one time. The engine's atomic / flock-serialized
claim primitive is a **safety net** here, not load-bearing — it earns its keep in
the N-CLI fleet (§C) where independent processes contend for the same task, but in
single-session orchestration there is nothing to contend.

---

## Back-compat (SPEC-S11.5, PRD-R15)

This mode is **purely additive**:

- The single-agent `run` (legacy N=1 lock path, `commands/autodrive.md` §B) is
  **unchanged**.
- The N-CLI `run --parallel` fleet (`commands/autodrive.md` §C, with its
  holder/lease/reaper) is **unchanged**.
- `/orchestrate` adds a third, single-session path that reuses the same
  deterministic engine verbs without introducing the process-liveness layer.

**Frozen-orchestrator activation.** The engine is the **frozen external snapshot**
at `.claude/harness/autodrive/engine.py` (`commands/autodrive.md` §C). This mode's
verbs (`next-parallel-set`, path-based scope guard, `scope-audit`) become available
only **after a snapshot refresh** — i.e. after `/autodrive init` re-seeds
`.claude/harness/` from the updated `harness/` source. Until that refresh the
running orchestrator keeps executing the previously-frozen snapshot; the new mode
goes live on the next seeded snapshot.

---

## `status`

`python3 "$ENGINE" status` (the `claims` alias, SPEC-S9) — print the frontier plus
every live claim (session, task, batch, scope, branch, worktree, age) and stop.

---

## Hard rules

- **No questions** except a `needs-human` escalation (which yields, not prompts).
- **Orchestrator writes the ledger; subagents write only code** inside their
  worktree. Never edit a file outside a task's `scope[]` yourself.
- **Never** `--no-verify`, `git reset --hard` on un-checkpointed code, or
  force-push — the same discipline the briefing imposes on subagents applies to you.
- **Always run `scope-audit` before accepting a subagent turn** — a green
  self-report is not acceptance.
- **Trust the ledger, not memory.** Re-derive state via the engine after any
  restart.
- **Finish the work; don't end on a promise.** You are operating autonomously —
  proceed through the loop with tool calls; end a turn only on a real stop
  condition (empty `next-parallel-set`, an emitted `needs-human`, or the turn
  budget).
