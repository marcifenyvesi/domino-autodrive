---
description: Autonomously implement the next ready TASK in the active BATCH — read the ledger, run the challenge gate, implement via a scope-bounded sub-agent, test, audit, commit, and record every transition. Survives a rate-limit kill by resuming from the git-committed ledger. No questions except the bounded design-ratify escalation.
argument-hint: [init | run [--parallel] | status | resume] (default: run)
allowed-tools: Read, Glob, Grep, Edit, Write, Bash, PowerShell, Agent, Skill, AskUserQuestion
---

# /autodrive — the autonomous loop

This command is the
orchestrator. It owns the LLM-driven steps; the deterministic
steps are delegated to the engine:

```
ENGINE=".claude/harness/autodrive/engine.py"      # seeded by `/autodrive init`
python3 "$ENGINE" <subcommand> ...                  # all return JSON on stdout
```

> **Golden rule of resumability:** trust the *ledger files*, never your
> conversation memory. After any restart, re-derive state from
> `python3 "$ENGINE" status` + `resume-check`. `status` is the now-shipped
> observability subcommand (an alias of `claims`). The transcript may
> be gone; the committed ledger is not.
>
> **`--resume` fast-path:** if you *do* still have the
> session, `claude --resume` reloads the transcript and is a cheap interactive
> recovery — but it is a complement, not the source of truth. The ledger path
> above is what makes a *fully unattended* re-launch (cron/`loop`) work, and it
> is always authoritative when the two disagree. When in doubt, reconcile from
> the ledger.

---

## Modes

- **`init`** — seed this repo for the harness (§A). Run once per project.
- **`run`** (default) — execute the loop until no ready task remains, a
  `needs-human` is emitted, or the turn budget is hit (§B). Single-writer, one
  task at a time (the legacy N=1 path).
- **`run --parallel`** — opt-in fleet mode: N concurrent CLI agents, each in its
  own worktree, sharing the same challenge/implement/test/audit loop (§C). Off
  by default; N=1 behaviour is unchanged.
- **`status`** — print the frontier + every live claim (the `claims` alias)
  and stop.
- **`resume`** — run the reconciliation check (§B step 1b) and report what a
  `run` would do, without doing it.

---

## A. `init`

1. Run `python3 .claude/harness/autodrive/init.py` (the engine ships an
   idempotent seeder). It:
   - copies `harness/` → `.claude/harness/` (engine + hooks + STANDARDS source),
   - seeds `STANDARDS.md` at repo root if absent,
   - merges `harness/settings.snippet.json` into `.claude/settings.json`
     (the PreToolUse scope guard + Stop ledger-commit hooks),
   - creates the doc-tree skeleton (`docs/design/*`, `docs/batches/`,
     empty `docs/LEDGER.md` + `docs/LEDGER.state.json`),
   - writes a starter `.harness.yaml` if absent.
2. Report what was created/skipped. Remind the user the design docs
   (`docs/design/PRD.md …`) are authored by hand (with `/spec/create-*`) and
   challenged before any `run`.

If the engine isn't present yet (fresh clone of the global tools), copy it from
`~/.claude/harness/` (the bootstrap installs it there).

---

## B. `run` — the loop

**Preflight.**
- `python3 "$ENGINE" lock --session "$CLAUDE_SESSION_ID"`. If `acquired:false`,
  another loop holds the lock → STOP with "autodrive already running here."
- Confirm the design is ratified: `docs/design/PRD.md` exists and is not
  `status: draft`. If not → STOP ("design not ratified — author/challenge it
  first"). Never invent design.

**Each iteration:**

1. **Read state.** `python3 "$ENGINE" status` (the `claims` alias). Note
   the active batch, any in-flight task, any live claims, and open `needs-human`.

   **1b. Resume reconciliation** (only if a task is in-flight):
   `python3 "$ENGINE" resume-check` →
   - `restart` → clean code tree; redo the task from `challenged`.
   - `adopt` → dirty code matches the recorded `expect_sha`; continue at the
     task's recorded state.
   - `quarantine` → dirty code doesn't match; move the branch aside
     (`git branch quarantine/<task>-<short-sha>`), emit nothing further, and
     surface to the user — do **not** build on an unknown tree.

2. **Pick work.** `python3 "$ENGINE" next-task` → `{task, batch, scope, …}` or
   `{}`. Empty → all ready work done → go to **Wrap-up**.

3. **Challenge gate**. Run the challenge wrapper on the
   task doc, **≥2 passes** (3 if the batch is `complexity: high`):
   - Use the `challenge` skill / `/challenge` on `docs/batches/<batch>/tasks/<task>.md`.
   - Stop early when a pass yields zero net findings (converged) or only NIT
     re-litigation. If pass N reverses pass N−1 (oscillation), freeze and
     `set-state --to needs-human`; continue with other ready tasks.
   - **Router priority:** prefer fixing the *task*. If the gate concludes a
     **design doc** must change → **bounded self-ratify**: apply
     only annotation-level clarifications that don't touch a numbered
     requirement, a contract, or any `scope[]`; otherwise `set-state --to
     needs-human`, yield this task, continue others.
   - On success: `python3 "$ENGINE" set-state --task <id> --to challenged`.

4. **Branch + implement.**
   - `python3 "$ENGINE" set-state --task <id> --to in-progress --branch task/<id>`
     (this records the active scope the PreToolUse hook enforces, and write-ahead
     `about-to-branch`). Create the branch.
   - Spawn the **implementer** sub-agent (Agent tool). Pass: the task doc, its
     `design_refs[]` resolved to the cited requirement text, the `scope[]`, the
     reference files, **and the full text of `STANDARDS.md` inlined** (it does
     not auto-load). The implementer may only touch `scope[]` files — the hook
     hard-denies the rest; a denial is its signal to STOP and report, not to
     widen scope.
   - Record `expect_sha`: after implement, `set-state … --to implemented
     --expect-sha <python3 "$ENGINE" … >` (capture the code signature so a later
     kill can reconcile).

5. **Test** (STANDARDS §5 — verify the code, not the test).
   - Run the task's `verify[]` (incl. the no-stub grep + insecure-pattern grep
     (`standards.insecure_markers`, STANDARDS §8 — a hit routes to the audit
     gate with justification, not auto-fail) + build + lint + typecheck smoke
     checks).
   - On red: **suspect the code under test first.** Fix the code, retry to the
     cap (`.harness.yaml loop.retry_cap`, default 3).
   - **Test diff-flag:** if any test file changed during implement,
     do NOT accept the green silently — route the test delta to the audit gate.
   - **Manifest diff-flag (STANDARDS §8.5):** if a dependency manifest or
     lockfile changed during implement, route the new/changed dependencies to
     the audit gate (slopsquatting / canonical-package check).
   - Each failed attempt: `python3 "$ENGINE" record-failure --task <id>
     --signature "<failing-test-id>:<diff-hash>"`, then
     `python3 "$ENGINE" check-progress --task <id>`. If `escalate:true`
     (repeated failure signature) → it has emitted `needs-human`; yield.
   - Cap hit with no escalation → `git revert` the attempt, `set-state --to
     reverted` (keeps the failed sha), then back to `todo` for one fresh try.
   - Green → `set-state --to tested`.

6. **Audit**.
   - **Code-quality** every task: `code-review` skill on the diff.
   - **Security** risk-tiered: run the built-in `security-review` only when
     the batch is `security: true` or the diff touches an
     `audit.security_surface` path; always run a per-batch sweep at batch close.
   - **Playwright** for webapp UI tasks: drive the UI doc's contract per
     `.claude/harness/audit/playwright-gate.md`; failures are High findings.
     Reported as *skipped (not configured)* if the repo has no Playwright setup —
     never silently passed.
   - Any finding ≥High → `set-state --to blocked`, emit the finding, yield.
   - Clean → `set-state --to audited`.

7. **Commit + close.**
   - Commit only `scope[]` files: `git add <scope> && git commit -m
     "<commit_prefix> <id> — <title>"` (write-ahead `about-to-commit`).
   - `python3 "$ENGINE" set-state --task <id> --to done` (clears the active task).
   - Append any findings/gotchas: the engine logs transitions; add
     `finding`/`gotcha` lines for anything a future task needs (use the ledger
     library or a Write to `docs/LEDGER.md`, append-only).

8. **Budget check.** If the turn is getting long, stop cleanly (the ledger is
   committed by the Stop hook; the next `/autodrive run` resumes). Otherwise loop.

**Wrap-up.**
- If a batch's tasks are all `done`, mark the batch `done` and record its
  `traceback` (commit range, audit verdict, test baseline) in `BATCH.md`.
- `python3 "$ENGINE" unlock --session "$CLAUDE_SESSION_ID"`.
- Report: tasks completed this run, any `needs-human` (with the cited doc to
  edit), the next ready task, and whether design changes are pending your review.

---

## C. `run --parallel` — the fleet path (opt-in)

The **same** loop, run by N concurrent CLI agents instead of one. **Opt-in
only.** With no `--parallel` flag and a single live session the command runs the
§B path verbatim — the legacy single-writer lock (§B preflight `lock`/`unlock`)
stays the N=1 default and its observable behaviour equals today's. Nothing below
replaces §B; it wraps §B in a supervisor + isolated
worktrees. Concurrency is capped at `.harness.yaml parallel.max` (default 4;
Anthropic's 3–4 worktree guidance — ≥5 hits rate limits and is unreviewable).

The engine (the **frozen external snapshot** at
`.claude/harness/autodrive/engine.py`) still owns every deterministic step; the
orchestrator only adds a supervisor that fans work out and a per-agent loop that
runs inside a dedicated worktree. `claim`/`release` below are the engine's
atomic claim primitive — the flock-serialized registry write/delete
(`docs/.locks/<id>.claim` + the `active_tasks` entry), not a distinct
user-facing subcommand — and every live claim is visible via `status`/`claims`.

**Supervisor — fan-out + reaper.**

1. **Pick a disjoint set.** `python3 "$ENGINE" next-parallel-set --n K`
   (K ≤ `parallel.max`) → up to K ready tasks that are mutually scope-disjoint
   AND disjoint from every live claim, in DAG order, honouring `depends_on[]`.
   Empty → no parallelizable frontier → fall back to §B or go to
   the **Merge phase**.
2. **Claim + provision, per task.** Atomically **claim** each returned task in
   the shared registry (one winner per task; a lost race just drops that task
   and the supervisor moves on), then
   `python3 "$ENGINE" worktree-add --task <id>` — creates `.worktrees/<id>` on
   branch `task/<id>` (creation serialized under the state lock; `link`/`copy`/
   `ready` provisioning per `.harness.yaml worktree:`). `.worktrees/` is
   gitignored.
   **Launch the claim holder** immediately after a winning claim, as
   a background process bound to the agent that will run this task:

   ```bash
   python3 "$ENGINE" hold-claim --session <sid> --task <id> --watch-pid <agent-pid> &
   HOLDER_PID=$!
   ```

   Pass the agent's pid (the fleet shell running the per-agent loop — e.g. `$$`)
   as `--watch-pid`, so the holder dies with the agent process tree. The holder
   is a long-lived process that holds `flock(LOCK_EX)` on the task's
   `docs/.locks/<id>.claim` for the agent's whole lifetime and refreshes the
   claim's heartbeat every `parallel.heartbeat_minutes` (default 30). Record
   `HOLDER_PID` alongside the claim so the release path (per-agent step 6) can
   terminate it. If `--watch-pid` is omitted the holder falls back to watching
   its own parent pid.
3. **Spawn.** One implementer **per claimed task, with cwd = its worktree**.
   Never exceed `parallel.max` live agents.
4. **Reap on a cadence.** `python3 "$ENGINE" reap` reclaims dead/hung agents:
   any claim past its `lease_expiry` is reset to `todo` (clean worktree) or
   quarantined (`quarantine/<id>-<sha>`, task → `needs-human`). `reap` never
   touches a claim still inside its lease, so one live agent never disturbs
   another. Observe the fleet any time with
   `python3 "$ENGINE" claims` (alias `status`).

   With a holder running (step 2), `reap`'s flock-primary crash detection is
   **instant**: its non-blocking flock acquire fails while the agent lives (skip)
   and succeeds the moment the agent crashes (reclaim now, no lease-TTL wait).
   If no holder was launched, the loop still reclaims via the
   heartbeat/lease backstop once the lease expires — slower, but graceful
   degradation with no regression.

**Per-agent iteration** — cwd = `.worktrees/<id>`, session = that agent's
`$CLAUDE_SESSION_ID`:

1. `python3 "$ENGINE" set-state --task <id> --to in-progress --branch task/<id>`
   — records the active scope the PreToolUse scope guard + pre-commit hook
   enforce for *this* worktree (session-resolved).
2. **Run the existing §B challenge → implement → test → audit loop verbatim**,
   scoped to `.worktrees/<id>`. The implementer may touch only `scope[]`; the
   per-worktree hook hard-denies the rest.
3. **Refresh the lease every iteration:** `python3 "$ENGINE" heartbeat --session
   <id>` at the top of each pass — a long implement/test step must not let the
   lease expire under a live agent and get reaped.
4. **Authoritative post-turn boundary — before accepting the commit:**
   `python3 "$ENGINE" scope-audit --session <id>`
   re-diffs the worktree's branch vs base (staged + untracked) against the
   claimed `scope[]` and the sensitive-path deny-list, and rejects/rolls back
   any out-of-scope change (or marks `needs-human`). This is the layer no
   `--no-verify` can evade — never accept a green turn without it.
5. On a clean audit, commit only `scope[]` files on `task/<id>`
   (`<commit_prefix> <id> — <title>`).
6. **Release + tear down:** first stop the claim holder launched at claim time
   (`kill -TERM "$HOLDER_PID"` — SIGTERM, so it releases its flock cleanly),
   then drop the claim (registry entry + its `docs/.locks/<id>.claim`), then
   `python3 "$ENGINE" worktree-remove --task <id>` (`git worktree remove` +
   `prune`; `--force` only for a deliberately discarded dirty tree — never
   `rm -rf`).

**Crash isolation:** killing one agent leaves every other agent's
claim and worktree intact; `reap` reclaims only the dead session's task, and
per-session resume reconciliation (§B step 1b) adopts/restarts/quarantines only
that task. **Agents must never `git stash`** in a worktree — the stash reflog is
a single stack shared across all worktrees, so one stash silently surfaces or
drops another's work.

---

## Merge phase (operator/supervisor, after the fleet drains)

Run once the fleet has no live claims (`claims`/`status` empty) and the
parallelizable frontier is exhausted. Merges are **sequential and verify-gated**:

1. `python3 "$ENGINE" merge-ready [--base <integration-branch>]` → the
   `task/<id>` branches whose task is `done` and not yet merged into the
   integration branch.
2. `python3 "$ENGINE" merge [--verify "<cmd>"] [--base <integration-branch>]`
   merges them **one at a time**, running the repo verify after each merge.
   Disjoint scopes make this conflict-free by construction, but the per-merge
   verify still catches **semantic** conflicts a clean textual merge misses
   (e.g. a rename at call sites vs a new call to the old name).
3. On a **git conflict OR a failing verify**, `merge` **stops**, leaves the
   already-merged branches intact, and emits a `needs-human` ledger event for
   the offending branch — it never auto-resolves. Escalate that branch; the
   remaining ready branches wait for the next merge run.

Shared generated/index files stay **out of agent `scope[]`** (lockfiles,
barrel/`__init__.py`/index files, formatter-owned config); lockfiles are
regenerated once post-merge, not merged.

---

## Hard rules

- **No questions** except the bounded design-ratify escalation (which yields,
  not prompts) and a `quarantine` reconciliation (which surfaces and stops).
- **Never** edit a file outside the active task's `scope[]` yourself — the same
  discipline the hook enforces on the sub-agent applies to you.
- **Never** `git reset --hard` on un-checkpointed code, `--no-verify`, or
  force-push.
- **One commit per task scope.** The ledger is committed separately by the Stop
  hook (or explicitly at step 7).
- **Trust the ledger, not memory.** Always re-derive state via the engine.
- **Finish the work; don't end on a promise.** You are operating autonomously —
  the user is not watching and cannot answer mid-run, so a "Want me to…?" /
  "I'll now run…" ending just stalls the loop. For reversible actions that
  follow from the ratified design, proceed without asking. Before ending a
  turn, check your last message: if it is a plan, a question, or a promise
  about work not yet done ("I'll…", "next I'll…", "let me…"), do that work now
  with tool calls instead. End a turn only on a real stop condition — no ready
  task, an emitted `needs-human`, a `quarantine`, or the turn budget (§B
  step 8).
