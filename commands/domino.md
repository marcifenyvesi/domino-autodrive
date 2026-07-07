---
description: Run the full autonomous build pipeline — one prompt in, shipped feature out: research → challenge the research → design gate (challenge the golden docs only if the concept drifts) → author batches/tasks → challenge the tasks → orchestrated parallel autodrive implementation. Runs to the end autonomously.
argument-hint: "<what you want built in this repo>"
allowed-tools: Read, Glob, Grep, Write, Edit, Bash, Agent, WebSearch, WebFetch
---

# /domino — the autonomous build pipeline

You write ONE prompt describing what you want. Domino researches it, pressure-tests
the research and the design, turns intent into challenged task specs, and implements
them with orchestrated parallel subagents — **autonomously, to the end**.

Domino is a conductor: it does not reinvent the harness, it *chains* it. It knows and
reuses the **golden design hierarchy** (`PRD → HLD → ARCH → SPEC → UI`), the
**`/challenge`** gate, the **`/autodrive`** loop, and the **orchestrate** mode
(`commands/orchestrate.md`, worktree-isolated subagents).

**`$ENGINE` — pick the right engine for THIS repo (deterministic test).** THIS repo is the
harness's OWN source repo **iff** `[ -f harness/autodrive/engine.py ]` (a top-level `harness/`
dir with the engine SOURCE, like this harness source repo) **OR** a ready task's `scope[]` includes
`harness/**`. In that ONE case use the **frozen external snapshot** so implementing a harness
task can't brick the running loop:
`$ENGINE = python3 "$HOME/.claude/harness/autodrive/engine.py"`. **Otherwise — every normal
target repo** (its tasks touch its own app code; it only has a *vendored* `.claude/harness/`
copy) — use the **in-repo** engine:
`$ENGINE = python3 "$(git rev-parse --show-toplevel)/.claude/harness/autodrive/engine.py"`.
Merely *having* a `.claude/harness/` copy — even a freshly-synced one — does NOT make a repo
the harness dev repo; do not invoke the frozen-snapshot rule for a normal target.

`$1` = the prompt (what you want built).

---

## Preconditions — STOP if unmet

- **Autodrive target seeded.** `.harness.yaml`, `docs/design/`, `docs/batches/`, the
  ledger, and the hooks exist (`/autodrive init`). Use the engine chosen by the `$ENGINE`
  test above — **in-repo** for a normal target, the **frozen snapshot** ONLY for the harness's
  own source repo. Tasks never scope `.claude/**`; only the harness source repo has tasks that
  scope `harness/**`.
- **The golden skeleton exists.** `docs/design/{PRD,HLD,ARCH,SPEC,UI}.md` are present and
  ratified. Verify concretely — each file's frontmatter is `status: ratified` (not
  `draft`), e.g. `for f in PRD HLD ARCH SPEC UI; do grep -q 'status: ratified'
  "docs/design/$f.md" || echo "DRAFT/MISSING: $f"; done`. Domino does NOT invent design
  from nothing — it needs the skeleton. Any draft/missing → STOP and route to the on-ramp
  (do NOT grill here — domino is autonomous, the interview is a human-driven pre-step): "no
  ratified golden skeleton — run `/grill-to-design <intent>` to build one by interview
  (or `/spec/create-*` by hand), then `/domino`."
- **`$1` (the prompt).** May be empty **only if** ready tasks already exist — then it means
  "implement/resume" (Phase 0 routes it). Empty prompt **and** no ready tasks → STOP and ask
  for the intent. If the skeleton is ratified but `$1` is present and ambiguous against it,
  STOP and route: "sharpen the intent first with `/grill-me`, then re-run `/domino`."

Acquire the lock (`$ENGINE lock --session domino-<slug>`); if held, STOP. Record
`domino start` in the ledger. From here on: **no questions** except the single bounded
escalation in the Autonomy contract below.

---

## Phase 0 — Triage: locate position in the pipeline (idempotency gate)

Domino is **idempotent when the Preconditions are met** — safe to invoke at any pipeline
position (fresh intent, mid-pipeline, or resume). Before any research, inspect repo state and
pick the entry point by the **ordered rules below (first match wins)**. **Never re-author over
existing ready tasks, and never re-challenge converged ones.** The classification is a judgment
domino (the model) makes from the prompt vs the existing plan — it needs no user question; when
genuinely ambiguous it takes the **conservative** branch (treat as *delta* and do the
increment, rather than skip work).

1. **Read the state.** `$ENGINE next-task` + `next-parallel-set --n <parallel.max>` (is there
   ready `todo` work?); all batch/task states in `docs/batches/`
   (todo/challenged/in-progress/done/needs-human/blocked); `$ENGINE resume-check` (in-flight
   task?); existing `docs/research/` + each design doc's `status`.

2. **Choose the entry point — evaluate IN THIS ORDER, first match wins:**
   1. **In-flight task** (`resume-check` says adopt/restart/quarantine) → reconcile it, then
      continue at **Phase 5**.
   2. **Implement/resume prompt** — empty/whitespace `$1`, or an explicit "implement" / "go" /
      "resume" / "continue":
      - ready `todo` tasks exist → **Phase 5** (implement them).
      - none ready but all tasks `done` → **report "all done" and STOP** (terminal, not an error).
      - none ready and some `needs-human`/`blocked` → **report the blocked items and STOP**
        (domino won't auto-resolve a human-gated task).
   3. **Greenfield** — no batches/tasks exist at all (design is still ratified, per
      Preconditions — greenfield means "no *tasks* yet", never "no design") → full pipeline
      from **Phase 1**.
   4. **Conflict** — the (non-empty) prompt CONTRADICTS a committed ready task (changed intent
      for the same feature/scope) → run the **Phase 2** design gate; mark the contradicted
      **task** `needs-human` — this pauses **that task only**, NOT the whole run (only a
      PRD-level contradiction freezes the thread, per the Autonomy contract) — and author its
      replacement as a delta (rule 5).
   5. **Delta** (the default for any non-empty prompt that adds new intent, and the
      conservative choice when unsure) → run Phases 1–4 for the **increment only**: research
      the new area *iff* needed; author NEW batches/tasks (`depends_on` the relevant existing
      ones — and if a new task's `scope[]` overlaps an existing ready task, add a `depends_on`
      edge so they can't parallelize); challenge **only the new tasks**. Then **Phase 5** over
      everything ready. Do NOT touch or re-challenge the existing converged tasks. If, while
      scoping the delta, you find the intent is **already fully realized** by existing
      ready/`done` tasks (no real increment), fall back to rule 2.

3. **No duplication (carried into Phase 3).** When Phase 3 authors, it MUST first verify each
   batch/task doesn't already exist (by id, intent, or scope) and **reuse** an equivalent
   ready task rather than cloning it.

4. Record the chosen entry point + one-line rationale in the ledger (`domino triage →
   <entry>`), then proceed.

> When tasks are already authored, challenged, and ready, the correct back-half tools are
> `/orchestrate` (parallel subagents) or `/autodrive run` directly — Phase 0 routes domino
> to exactly that path (rule 2.i) rather than restarting the pipeline.

---

## Phase 1 — Research (online, verified)

1. Fan out web research on the prompt's domain — multiple search angles, fetch
   **primary/canonical** sources (official docs, specs, source repos) over aggregators,
   extract mechanisms + prior art.
2. Synthesize a cited report → `docs/research/<DATE>-<topic>.md`. Every load-bearing
   finding carries a **source URL** and a "transferable? yes / no / later + why" verdict.
   End with a "recommended minimal extension" and an explicit "defer / out-of-scope" list.
3. **Adversarially verify the research ×2 against independent sources.** This is not a
   built-in "vs web" `/challenge` mode — `/challenge` on a `general-docs` target has no
   external baseline by default. Domino performs the second-source verification itself:
   invoke `/challenge` on the research doc **passing the key domains as explicit reference
   systems** (`/challenge docs/research/<file>.md <source-a> <source-b> …`) and/or run an
   adversarial-verify sub-pass that **re-fetches independent sources** and confirms/refutes
   each load-bearing claim. A premise the second source overturns is a finding, not a
   footnote — autofold corrections into the research doc. Run this twice; converge
   (pass 2 → zero new corrections).
4. Commit the research doc + its challenge findings.

---

## Phase 2 — Design gate (the golden-skeleton investigation)

The design docs are **golden skeletons** — expensive to change, worth changing only when
the *concept itself* has drifted, never for convenience. Stability gradient
(hardest → easiest to justify touching):

```
   PRD   >   HLD   >   ARCH   >   SPEC   >   UI
 (product north star,          (SPEC extends normally      (follows
  stable from day one)          with new implementations)   the surface)
```

1. **Investigate HARD and skeptically.** Read the design against the (now verified)
   research and the prompt intent. Ask: is a design doc **wrong, missing a load-bearing
   requirement, or contradicted by reality** — or does the intent simply need *new*
   requirements/tasks the existing skeleton already accommodates? **Default answer: NO
   change.** Adapt the work to the design; do not bend the design to the work.
2. **Only if a genuine concept drift or gap is found**, change the design — but note
   **who edits what**. `/challenge` never auto-applies an L1 design edit (its
   fold-direction rules gate every PRD/HLD/ARCH/SPEC change behind Q&A, and design-updates
   are never auto-folded). So domino does NOT ask `/challenge` to rewrite a golden doc.
   Instead:
   - **Domino authors the design change directly** (informed by the verified research),
     applying the golden-skeleton bar itself, then runs `/challenge` on the design docs
     **as a consistency validator** — surfacing contradictions/gaps as findings and folding
     any drift **downward** (into tasks / SPEC annotations), never auto-editing a
     higher-authority doc.
   - **Who may author what, autonomously (domino's own gate):** a **SPEC** addition for a
     new capability (a new numbered `S<n>`) is the **normal, expected** path — domino
     authors it. **UI** follows the surface. An **ARCH** change is a high bar — domino may
     author it but MUST write an explicit concept-drift justification in the design/findings
     doc. An **HLD** change is a very high bar (same, with stronger justification). A
     **PRD** (product-concept) change is the bounded escalation → `needs-human` (see the
     Autonomy contract).
   - "Cleaner" / "more convenient" / "would be nice" is NEVER a reason to touch a golden
     doc. Prefer the **smallest** change that restores coherence: extend SPEC before ARCH;
     ARCH before HLD; PRD only if the product intent itself changed (→ escalate).
   - Keep every doc internally consistent and traced upward after the edit; run `/challenge`
     ×2 to confirm the design is coherent (converge → zero findings).
3. If no change is warranted, **say so plainly** and proceed on the existing skeleton.
4. Commit any design change (+ its challenge findings) before authoring tasks.

---

## Phase 3 — Author the batches & tasks

From the prompt intent + research + (possibly updated) design, author what autodrive
needs (`/spec/create-batch`, `/spec/create-task` conventions):

- **No duplication (Phase 0 step 3).** FIRST verify each batch/task you're about to author
  doesn't already exist by id, intent, or scope — **reuse** an equivalent ready task rather
  than clone it. In *delta* mode, author only the increment and give any new task whose
  `scope[]` overlaps an existing ready task a `depends_on` edge to it.
- Decompose into **BATCH**es by technical layer; `depends_on[]` forms a DAG.
- Author **TASK** mds: tight `scope[]` (repo-relative, one blast radius per task),
  `depends_on[]`, `design_refs[]` tracing to real `SPEC-S*` / `PRD-R*` IDs, `verify[]`
  (runnable), acceptance criteria one-per-requirement. **Scope for parallelism**: keep
  disjoint tasks' file sets non-overlapping so they can run concurrently; put shared /
  generated files (lockfiles, barrels, `__init__`) OUT of task scopes. Two tasks that
  share a file MUST have a `depends_on` edge (they cannot parallelize).
  - **Test files are a classic parallelism-killer:** if many tasks each declare a broad
    shared dir like `tests/` in `scope[]`, their scopes all overlap and NONE can co-claim —
    they serialize despite being otherwise independent. Scope each task's tests to **specific
    files** (`tests/test_<feature>.py`), not the whole `tests/` tree, so disjoint tasks keep
    disjoint test files and can run in parallel.
- Confirm the engine parses everything: `$ENGINE next-task` resolves the first ready task.
- Commit the task set. (Watch for repo `.gitignore` rules silently dropping task files.)

---

## Phase 4 — Challenge the tasks

Run **`/challenge` ×2–3** on the task set with autofoldback (target = the task mds;
reference = the design + the shipped code). Catch: drift from the design, coverage gaps
(every requirement owned exactly once), scope overlaps lacking a `depends_on` edge, DAG
cycles, and **infeasibility against the real code** (does the task cite symbols/paths
that actually exist?). Fold findings **into the tasks** — tasks are L5, they yield to the
L1 design; never fold a task problem upward into a golden doc. Iterate until a pass yields
zero findings (convergence). Commit findings + foldback per pass.

---

## Phase 5 — Implement (orchestrated parallel autodrive)

Run the **orchestrate** mode — as parallel as `parallel.max` (default 3–4) allows.

**Availability gate — test ENGINE capability, NOT a repo-local file.** The `/orchestrate`
command is a **global** command (`~/.claude/commands/orchestrate.md`); it is **not** vendored
into target repos (only the engine + hooks are, under `.claude/harness/`). So NEVER gate on a
repo-local `commands/orchestrate.md` — it is absent in every target by design. Instead check
that the engine supports the parallel verbs: if `$ENGINE next-parallel-set --n 1` succeeds
(exit 0), orchestrate mode is available → use it. Only if the engine is the **old
single-writer version** (the verb is missing/errors) does domino **degrade gracefully** to the
serial `/autodrive run` loop — no loss of correctness, only of concurrency. (Even with
orchestrate available, tasks whose `scope[]` overlaps run serially anyway — that is the
scope-gate working, not a degradation.)

When orchestrate is available:

1. `$ENGINE next-parallel-set --n K` → K mutually scope-disjoint ready tasks.
2. Per task: `$ENGINE claim --session <label> --task <id>` (the conductor is the **sole**
   ledger writer → no claim races) then `$ENGINE worktree-add --task <id>`.
3. Spawn the K subagents **concurrently** (one message, K `Agent` calls), each **confined
   to `.worktrees/<id>/` and its `scope[]`**, running the task's `verify[]`, committing on
   `task/<id>`. Brief each with its worktree path, scope, task-doc path, and verify
   commands; forbid `git commit --no-verify`, `cd` outside its worktree, and external
   push/fetch.
4. On each return: `$ENGINE scope-audit --session <label>` (the **authoritative** boundary
   — re-diffs the worktree; a subagent can't `--no-verify` around it). Clean → mark `done`,
   `release`, `worktree-remove`. Out-of-scope or red `verify[]` → fix or `needs-human`,
   **never a silent accept**.
5. After each wave: `$ENGINE merge-ready` → sequential **test-gated** `merge` onto the
   integration branch. A conflict or red verify marks **that branch/task** `needs-human`
   and halts *its* merge, leaving already-merged branches intact; the orchestrate loop
   **continues with the other disjoint tasks** until all are terminal or blocked (it does
   not abort the whole run for one bad branch).
6. Mark a batch `done` when all its tasks are terminal (the engine advances tasks, the
   conductor advances batches). Loop until `next-parallel-set` is empty, honouring the
   batch DAG.

Every task still passes the full **challenge/implement/test/audit** gate. Commit per task;
the git-committed ledger makes the entire run **resumable across kills** — a re-invocation
continues from the last committed task.

---

## Phase 6 — Wrap-up

Final full verification: all selftests green, `$ENGINE next-task` empty, no source file
over the STANDARDS caps, working tree clean. Write a run summary (what shipped, commit
range, any `needs-human` items, deferred follow-ups). Release the lock. If the target was
the harness itself, remind the user the change goes live only on a snapshot refresh.

---

## Autonomy contract

Domino runs to the end without questions — with exactly **one** bounded escalation: if the
Phase-2 design gate concludes a **PRD-level** change (the *product concept itself*) is
required, domino freezes that thread as `needs-human` and continues with everything else.
The product's north star is the one thing it will not silently rewrite; a drifting concept
is exactly when a human should look.

Everything below PRD — HLD/ARCH/SPEC/UI, tasks, code — domino resolves autonomously, but by
**authoring** the change itself under the golden-skeleton bar (Phase 2), NOT by asking
`/challenge` to auto-apply an L1 edit — `/challenge` gates every L1 change behind Q&A, so
domino uses it only to *validate* the design and to fold **task-level** drift. HLD/ARCH edits
are autonomous but require a written concept-drift justification; SPEC/UI additions are the
normal path. (An operator may pre-authorize PRD edits in the invocation for a fully-unattended
concept change.)

**Golden rule:** research before design, challenge before build, isolate before parallel,
verify before done. Domino never invents design from nothing, never bends a golden doc for
convenience, and never accepts out-of-scope work.

## The domino chain (at a glance)

```
prompt ─▶ TRIAGE ┬─ in-flight ──▶ resume ───────────────────────────────────────┐
   (Phase 0,     ├─ implement ──▶ ready? Phase 5 │ all-done / blocked? report+STOP  │
    ordered)     ├─ conflict ───▶ design gate ▸ needs-human(that task) ▸ delta ─────┤
                 ├─ delta ──────▶ research(new) ▸ author+challenge delta ────────────┤
                 └─ greenfield ─▶ research ▸ challenge×2 (adversarial-verify)         │
                                 ▸ design gate ▸ [challenge×2 design, iff drift]      │
                                 ▸ author batches+tasks ▸ challenge×2–3 ─────────────┤
                                                                                     ▼
                                          orchestrate: next-parallel-set ▸ claim ▸
                                          worktree ▸ ∥ subagents ▸ scope-audit ▸ merge ─▶ done
```
Triage (Phase 0) picks where to enter; each tile then falls only when the one before it has
settled. That is the domino. The `/challenge` loops run in phases **1** (research), **2**
(design gate, only on drift), and **4** (tasks); phases **0** (triage), **3** (authoring),
and **5** (implementation) have no challenge loop.
