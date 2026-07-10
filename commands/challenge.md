---
description: Stress-test a target (specs, architecture, audit report, design doc, a diff of AI-authored work, or a whole repo) for internal consistency and against industry-standard prior art, then optionally fold accepted recommendations back into the underlying code/specs. Adaptive — target type, reference systems, and reviewer questions are picked from what's detected. Project wrappers can override defaults.
argument-hint: [<path|glob|git-ref>] | [--report <path>] | [--auto] | [--since <ref>] | [--staged] | [reference systems to add, space-separated]
allowed-tools: Read, Glob, Grep, WebFetch, WebSearch, Write, Edit, Bash, PowerShell, Agent, AskUserQuestion
---

# /challenge — stress-test a target

You are reviewing a target to answer one question:

> **Is this sound enough to keep building on, or are we about to bake in
> mistakes we'll regret in three months?**

Frame all findings against the stated maturity of the target (prototype,
production prep, post-incident review, AI-authored draft, etc.). Don't
manufacture criticism, and don't excuse real flaws because "it's just a
prototype."

This command is **global and adaptive**. Project-scoped wrappers at
`<repo>/.claude/commands/challenge.md` may inject defaults (target paths,
forced target type, baseline reference systems, foldback rules) before
this command runs — honor any defaults they pass.

---

## Modes (chosen during Step 0)

- **default** — target is a path/glob/spec set; find drift against
  references; foldback edits the target files.
- **`--report <path>`** — *audit-foldback mode.* Target IS a report;
  foldback edits the audited code, not the report.
- **`--auto`** — skip Q&A for ambiguous findings; best-guess the
  conservative option and flag with `auto-decided`. See the `--auto`
  section; the safety invariants (below) hold unchanged.
- **diff modes** — `--since <ref>`, `--staged`, a git ref, or a single
  file path resolves the target to a diff (AI-work-check angle). If
  the resolved change set is empty, report "nothing to challenge" and
  stop.

Multiple modes compose (e.g., `--auto --since HEAD~3`).

---

## Safety invariants (single source — referenced everywhere else)

These four hold in **every mode**, including `--auto`. The rest of the
command points here rather than restating them.

- **S1 — Findings doc first.** In a git repo, commit the findings doc
  *before* any foldback edit. It's the durable safety property: if
  anything downstream breaks, the findings survive and `git revert`
  restores.
- **S2 — Code (L4) is never auto-applied.** Any fix that edits code is
  `flagged`, surfaced for the user, never written automatically — not
  even in `--auto`.
- **S3 — L1/L2 edits always require Q&A.** Editing a ratified design doc
  (L1) or Accepted ADR (L2) always pauses for explicit accept, even when
  the fold-direction is unambiguous and even in `--auto` (which flags +
  best-guesses but never writes them).
- **S4 — Per-scope commits.** One file's changes = one commit (or a
  tight logical group), so any single fold reverts cleanly.

---

## Step 0 — Resolve target, type, output path, and reference systems

Parse `$ARGUMENTS`:

- **`--report <path> [extra refs...]`** → audit-foldback mode. Target
  is the report. Extract the audited project root: prefer the report's
  parent directory if it lives inside a repo; otherwise grep the report
  for the first absolute path it cites and walk up to the nearest
  `.git`, `pyproject.toml`, `package.json`, etc.
- **`--since <ref>` / `--staged` / a git ref / single file** → diff
  mode. Resolve via `git diff` and treat the touched files (plus, for
  the bare-default case, the most recent commit on HEAD) as the target.
- **`<path-or-glob> [extra refs...]`** → that's the target. Resolve
  glob now with `Glob`; if zero matches, ask the user to clarify.
- **Bare reference names (no path-like token first)** → auto-detect
  the target (rules below) and treat everything as extra reference
  systems.
- **No arguments** → auto-detect target from cwd in this order:
  1. `tasks/*.md` if present (spec set)
  2. `specs/**/*.md` or `docs/specs/**/*.md`
  3. `SECURITY_AUDIT.md`, `AUDIT.md`, or `reviews/*.md` (latest by
     mtime) → auto-switch to `--report` mode
  4. `ARCHITECTURE.md`, `DESIGN.md`, `RFC*.md`, `PRD*.md`, `HLD*.md`
  5. The current working-tree diff plus the most recent commit on
     HEAD (AI-work-check default — convergence target)
  6. `README.md` plus top-level `.md` files
  7. If none found: report what you searched for and stop with a
     one-line "no review target detected — pass a path, glob, or git
     ref as `$ARGUMENTS`".

**Detect target type** (drives the playbook in the next section):

- **`agent-spec`** — agents, tools, manifests, playbooks, LLM loops,
  MCP, prompts, skills.
- **`security-report`** — vulnerabilities, severities (Critical/High/
  Medium/Low), CVEs, threat models, OWASP, attack surface.
- **`architecture-doc`** — design docs, ADRs, RFCs, system diagrams.
- **`api-spec`** — OpenAPI, GraphQL schemas, RPC contracts.
- **`code-quality`** — style guides, lint configs, refactor plans.
- **`ai-work-diff`** — a diff of recently-authored work being checked
  for drift / creep / gap before merge.
- **`general-docs`** — fall-through bucket.

If ambiguous, pick the most-specific match and note the choice in the
report. `code-quality` and `ai-work-diff` are the **code targets** —
they pull in `STANDARDS.md` (Step 1, and their playbook rows).

**Output path.** Compute today's date with `Get-Date -Format yyyy-MM-dd`
(PowerShell on Windows) or `date +%F` (bash elsewhere). Write to:

- If inside a git repo: `<repo-root>/reviews/<DATE>-challenge.md`
  (or `<repo-root>/docs/challenges/challenge-<DATE>.md` if that path
  already exists in the repo — match local convention).
- Else if inside the target's containing directory: `./reviews/<DATE>-challenge.md`
- Else: `~/.claude/reviews/<DATE>-<sanitized-target-name>-challenge.md`

Create the directory if missing. If a file with the same name exists,
append `-2`, `-3`, etc.

**For `ai-work-diff` mode**, the report may be short enough to print to
chat instead — see Step 7 ("Report" guidance for that mode).

---

## Hierarchy of truth (reference weighting)

When picking what to compare the target against, weight every artifact
by its authority. Higher levels (smaller numbers) win conflicts. This
hierarchy is **principle-driven**: new artifact types slot in by
character.

| Level | Authority | Character | Examples |
|---|---|---|---|
| **L1** | Ratified design intent | "what should be true" docs | `PRD.md`, `HLD.md`, `ARCH-SPEC.md`, `SPEC.md`; **`STANDARDS.md`** (the coding contract — how code must be written) |
| **L2** | Ratified atomic decisions | ADRs marked Accepted | `docs/adrs/adr-*.md` |
| **L3** | Completed task agreements | Tasks referenced by `git log` as `Implements: …` | shipped task entries |
| **L4** | Working code | What builds + passes tests | `src/`, `Sources/`, `tests/`, `Package.swift` |
| **L5** | Pending task plans | Tasks not yet shipped | unshipped task entries |
| **L6** | Supporting context | Plans, notes, prior findings | `ROADMAP.md`, `RESEARCH.md`, `reviews/`, `README.md` |

When unsure where something sits, treat it as L5/L6 (default to lower
authority) and surface a Q&A.

`STANDARDS.md` is **L1-authority for *how* code is written**. Because a
fix for a STANDARDS violation is always a code (L4) edit, such findings
are `flagged` under **S2** — surfaced, never auto-folded.

**Fold-direction rule** — a finding is a misalignment between artifact A
and artifact B:

- A higher than B → B yields to A. Fold edits B.
- Same level → **ambiguous**. Ask the user (or in `--auto`, pick the
  conservative option).
- Direction crosses a safety invariant → **S1–S4 win.** Both L4 (code),
  or a fix needing a code edit → `flagged` (S2). Editing L1/L2 →
  always Q&A (S3).

**Self-judging guard.** If the change *is* an edit to a reference, that
reference cannot be its own judge. Use the prior committed version of
the same file plus the remaining hierarchy.

---

## Reference systems & type playbooks

Each **playbook** below co-locates everything type-specific: the baseline
reference systems, the extra questions Agent A appends, the dimensions
each reference-system agent (B+) covers, and the foldback tiers offered
in Step 6b. Resolve the detected type's playbook once; Steps 2 and 6
point back to it. Add any user-specified reference systems from
`$ARGUMENTS` to the baseline.

**General reference rules (all types):**

- **Local-clone preference:** before WebFetching any reference system,
  check whether a local clone of it is already on this machine — if
  present, the reference agent reads the local source with Glob/Grep/Read.
  Primary sources beat third-party summaries. Fall back to WebFetch only
  if no local clone is found.
- **User-specified system unresolvable:** if a name from `$ARGUMENTS`
  doesn't match a known project after a web search, list nearest matches
  in the report and proceed without it. Do not fabricate a comparison.
- After resolving, write a one-line plan to the user before spawning:
  > "Target: `<path>` (`<type>`, L<N>). Mode: <default | --report |
  > --auto | diff>. Output: `<reviews-path>`. Spawning N agents:
  > internal consistency + <ref1>, <ref2>, ... ."

### Playbook — `agent-spec`

- **References:** MCP (Anthropic), LangGraph, CrewAI, AutoGen, OpenHands,
  OpenAI Agents SDK.
- **Agent A adds:** cross-file refs valid? `.env` shape consistent across
  files? Tool signatures match between definition and call sites?
  Dependency declarations form a valid DAG? Conventions (naming, error
  format, idempotency) followed consistently? Acceptance criteria
  mutually satisfiable? Open questions in conflict or duplicated? Phase
  labels match dependencies? Hard rules in the loop prompt consistent
  with what other tasks expect?
- **Agent B dimensions:** tool layer, agent loop, HITL/approval, state &
  memory, observability, self-extension, multi-model portability.
- **Foldback tiers:** MAJOR consistency only / MAJOR + portability
  renames / All top-5 recommendations / Stop — review only.

### Playbook — `security-report`

- **References:** OWASP Top 10 (current year), OWASP ASVS, MCP security
  guidance (Anthropic), Anthropic responsible tool-use docs, CWE Top 25.
- **Agent A adds:** severity rubric applied consistently? Each finding
  has location + evidence + impact + fix? Any contradictions between
  findings? Recommended fixes mutually compatible? Findings missing
  severity? "We should do X" without owner/effort? Trust-model
  assumptions stated explicitly?
- **Agent B dimensions:** finding-taxonomy alignment, severity
  calibration vs. industry norms, missing categories industry references
  would flag, fix recommendations vs. industry best practices,
  trust-model assumptions vs. industry threat models.
- **Foldback tiers** (audit-foldback): Critical + High only / Critical +
  High + Medium / All findings with concrete fixes / Stop — review only.

### Playbook — `architecture-doc`

- **References:** C4 model, AWS Well-Architected (relevant pillars),
  Google SRE workbook patterns.
- **Agent A adds:** terminology drift across sections? Diagrams
  consistent with prose? Stated constraints honored throughout? Quality
  attributes (latency/throughput/cost) numerically grounded or hand-wavy?
- **Agent B dimensions:** layering, deployment topology, failure-mode
  coverage, observability, scaling story.
- **Foldback tiers:** MAJOR consistency only / MAJOR + portability
  renames / All top-5 recommendations / Stop — review only.

### Playbook — `api-spec`

- **References:** OpenAPI 3.1 spec, JSON:API, Google API design guide,
  Stripe API conventions.
- **Agent A adds:** endpoint naming consistency? Error format
  consistency? Versioning scheme uniform? Auth declared on every
  endpoint? Pagination, sorting, filtering consistent?
- **Agent B dimensions:** resource modeling, error handling, versioning,
  auth, pagination/filtering, async patterns, deprecation policy.
- **Foldback tiers:** MAJOR consistency only / MAJOR + portability
  renames / All top-5 recommendations / Stop — review only.

### Playbook — `code-quality`  *(code target)*

- **References:** the project's own **`STANDARDS.md`** (repo root or
  `.claude/harness/STANDARDS.md`) — the authoritative coding contract,
  L1; then the Google style guide for the target language; then project
  conventions (grep `CONTRIBUTING.md`, lint configs).
- **Agent A adds:** rules contradict each other? Examples follow the
  rules they illustrate? Rationale stated for non-obvious rules? Does the
  guide align with, or contradict, `STANDARDS.md`?
- **Agent B dimensions:** align the guide against the Google style guide
  for the language and note where it diverges from `STANDARDS.md`.
- **Foldback tiers:** MAJOR consistency only / MAJOR + portability
  renames / All top-5 recommendations / Stop — review only.

### Playbook — `ai-work-diff`  *(code target)*

- **References:** none external by default — focus on in-repo references
  (Step 1) **plus `STANDARDS.md`** as the L1 coding contract the diff
  must satisfy. Add external systems only if the user passes them.
- **Agent A adds:** Drift (contradicts a reference)? Creep (adds scope
  references didn't sanction — e.g., a Phase 2 capability delivered as
  Phase 1)? Gap (skips something references required)? Cohesion
  (contradicts or duplicates prior committed code)? Phasing (deferred
  capability now treated as available)? Naming consistency (paths,
  command names, schema fields, module layout match across docs and
  code)? Index hygiene (new artifacts added to indexes that list them)?
  Open questions answered, deferred-with-reason, or silently skipped?
  Self-consistency inside the change itself (versions, dates, phase
  labels, cross-refs)? Behavioural promises (does code match the
  architecture spec's module layout, models, names)? **STANDARDS
  conformance (does the diff violate any rule in `STANDARDS.md` §1–8?
  cite the section).**
- **Agent B dimensions:** external reference agents are usually
  unnecessary — skip unless the user passed reference systems as extras.
- **Foldback tiers:** foldback updates the diff (or references), not a
  separate target — offer the standard MAJOR / structural / stop set.

### Playbook — `general-docs`

- **References:** none by default — internal consistency only unless
  extras passed.
- **Agent A adds:** terminology drift? Stale references (links, paths,
  version numbers)? Contradictions between sections?
- **Agent B dimensions:** none unless the user passes reference systems.
- **Foldback tiers:** the standard MAJOR / structural / stop set.

---

## Step 1 — Discover the in-repo blast radius

Before spawning external-reference agents, walk outward from the target
to find every artifact that **references** it or that it **references**:

- `Grep` for the target's IDs (task IDs, ADR numbers, component names).
- `Read` design docs and ADRs; note where they cite the target.
- For code targets: `git log -- <path>` to find commits and the tasks
  they reference (`Implements: T-NNN.M`).
- For task targets: `git log --grep="T-NNN.M"` to see if shipped
  (promotes L5 → L3).
- **For code targets (`ai-work-diff`, `code-quality`): load
  `STANDARDS.md`.** If `STANDARDS.md` exists at the repo root or
  `.claude/harness/STANDARDS.md`, read it and tag it a **primary
  reference** (L1). It's the coding contract the code must satisfy;
  `/autodrive` enforces it on the implement side, so `/challenge` holds
  code to the same bar.
- For `ai-work-diff`: read every file in the project reference hierarchy
  that has plausible bearing on the touched files. Don't trust recall;
  re-read.

Tag each blast-radius artifact:

- **Primary references** = higher level than target (incl. `STANDARDS.md`
  for code). Authoritative voices the target must agree with.
- **Peers** = same level. Same-level disagreements are ambiguous and
  need Q&A.
- **Secondary references** = lower level. Useful context but don't
  constrain the target.

Cap the blast radius if it gets unwieldy: focus on cross-level pairs
first (highest-yield findings).

---

## Step 2 — Spawn agents in parallel

Send a single message with multiple `Agent` tool calls.

### Agent A — Internal consistency reviewer

**Common spine:**

> Read every file in the target set and the in-repo blast radius from
> Step 1. Produce a consistency audit citing `file:line-or-section`
> for every finding. Each finding: severity (BLOCKER / MAJOR / MINOR
> / NIT), location, description, suggested fix. End with a 3-sentence
> verdict. Aim for ≤400 lines.

Then **append the detected type's "Agent A adds" questions** from its
playbook. For code targets, include the STANDARDS-conformance check and
pass the loaded `STANDARDS.md` in the prompt.

For `ai-work-diff` / code targets: if a fast verification is cheap (lint,
typecheck, focused test file), run it. Failures become high-severity
findings.

### Agents B+ — One per reference system

For each system in the detected type's playbook baseline + user extras,
spawn ONE agent (`ai-work-diff` usually spawns none — see its playbook):

> You are evaluating `<target>` against `<SYSTEM_NAME>`. First refresh
> your understanding of `<SYSTEM_NAME>`'s current architecture/
> conventions/recommended patterns:
> - **If a local clone of `<SYSTEM_NAME>` is available on this machine,
>   read it first** (try common capitalizations) with Glob/Grep/Read.
> - Else do 1–3 web searches and 1–2 WebFetches of canonical docs.
>
> Then read the target files at `<target-paths>`.
>
> Produce a comparison covering the **dimensions for this target type**
> (from the playbook). For each dimension: state what `<SYSTEM_NAME>`
> does, what the target does, and a verdict — **aligned / acceptable
> divergence / problematic divergence**. Cite specific doc URLs for
> `<SYSTEM_NAME>` claims and `file:section` for the target. End with:
> "If we were to migrate this to `<SYSTEM_NAME>` later, the migration
> would be [trivial / moderate / hard] because [reasons]." Aim for
> ≤300 lines.
>
> If `<SYSTEM_NAME>` cannot be located via search, return:
> "Could not identify `<SYSTEM_NAME>`. Closest matches found: X, Y, Z."

Specialize the prompt with that type's **Agent B dimensions** before
sending.

---

## Step 3 — Generate findings (verdict assignment lives here)

When all subagents return, consolidate into a unified finding list.
Each finding has:

- `id` — `F-NN` (stable handle)
- `kind` — drift | creep | gap | cohesion | phasing | naming | index
  | open-q | self-consist | runtime | contradiction | unstated-dep |
  yagni | under-spec | standards-violation
- `source` — the higher-authority artifact involved (incl. level
  L1–L6 or external reference system)
- `target` — the lower-authority artifact that would yield (or the
  design doc that needs extending if direction is up)
- `direction` — which yields to which (per fold-direction rule)
- `severity` — BLOCKER / MAJOR / MINOR / NIT (or High/Medium/Low/Info
  for security reports)
- `confidence` — `clear-cut` / `ambiguous`
- `edit_type` — annotate / add / replace / split / merge / deprecate
  / design-update / code-change
- `verdict` — `auto-foldback` / `needs-decision` / `flagged`
- `evidence` — `file:line` on **both** sides (the offender and the
  reference it offends)
- `rationale` — 1–2 sentences citing the conflict
- `proposed_action` — concrete edit; for code, describe the change
  rather than a patch

**Verdict assignment** (this is the single operational home; it enacts
the safety invariants S1–S4):

- **`auto-foldback`** — only when **all** hold: reference clearly wins
  (target drifted, not the reference); the fix is mechanical (rename,
  path-fix, version-bump, removing a sentence that contradicts an
  explicit out-of-scope, updating a stale index row, annotating a task);
  no semantic decision; doesn't cross a phase boundary, alter intended
  behaviour, or delete non-trivial work.
- **`flagged`** — the fix requires any of: a code edit (**S2** — any L4
  change, incl. every STANDARDS violation), file deletions, schema field
  renames, multi-file refactors, version-control surgery (rebase / amend
  / force-push), dependency downgrades, or removing tests. Listed, never
  auto-applied under any mode.
- **`needs-decision`** — everything else, and editing L1/L2 (**S3**,
  even when direction is clear). When in doubt → `needs-decision`; the
  cost of a wrong auto-foldback (silent regression) beats one extra Q&A.

---

## Step 4 — Optional external research

Run targeted web research only when Steps 1–3 surface a question the
repo can't answer (a dep version that may have shifted, a competitor's
behaviour change, an API update).

**Budget: ~5 searches, ~8 fetches max.** Don't dig beyond budget — we
can run this command again.

For each external item folded back, capture: source URL, what changed
since the target was written, what the implication is.

---

## Step 5 — Write the findings doc

Write to the path computed in Step 0 using the **report structure**
below.

Quote findings from subagents verbatim where they're strong; summarize
where verbose. Resolve subagent contradictions by re-fetching the
canonical doc yourself.

**Commit the findings doc now, before any foldback edit (S1).** Commit
message:

```
docs(challenges): challenge-<DATE> — target <target>; N findings (A auto / Q q&a / F flagged)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

For `ai-work-diff` mode: writing a separate file is optional. If the
findings are small and the convergence loop is the goal, print to chat
instead unless the user asked for a file.

---

## Step 6 — Foldback (user-gated)

After the report is saved, offer to fold accepted recommendations
back. **Behavior depends on mode:**

- **Default mode:** foldback edits the target files.
- **Audit-foldback (`--report <path>`):** foldback edits the
  *audited code* identified in Step 0, not the report. Append a
  `## Foldback log` to the report describing what was changed in the
  audited code.
- **`ai-work-diff` mode:** foldback typically updates the diff (or
  references), not a separate target.

### Step 6a — Apply auto-foldbacks

For findings with `verdict: auto-foldback`:

- `annotate` (task body) — append a `**Challenge update <DATE>:**`
  bullet to the existing **Challenge** section, citing finding ID +
  findings-doc link.
- `add` (new task) — append to the relevant ADR's task file with the
  next available ID; update the Summary table.
- `replace` / `split` / `merge` / `deprecate` — preserve the original
  under a `<details>` block when content is removed; add a dated
  note above the changed section.
- One `Edit` per change site (don't batch unrelated fixes).
- After applying, re-read each touched file briefly to confirm the
  foldback didn't introduce a new drift.

Commit per scope (**S4**), conventional-commit prefix per project's
`CLAUDE.md` (`docs:`, `refactor:`, `fix:`, `chore:`):

```
docs(<scope>): fold challenge findings F-AA[, F-BB] from challenge-<DATE>

- <one-line summary per finding>

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

Never auto-apply `design-update` (S3) or `code-change` (S2) — those go
through Step 6b or get flagged in Step 6c.

### Step 6b — Q&A on ambiguous findings

For each `needs-decision` finding, use `AskUserQuestion`. Format:

```
F-NN: <one-line description of the misalignment>
Direction (per hierarchy): <higher artifact> vs <lower/peer>
Options:
  (a) <option a — describe the concrete edit>
  (b) <option b — describe the concrete edit>
  (c) skip — record as rejected
```

Standard option set when applicable:

1. **Defer to reference** — apply the foldback as proposed.
2. **Accept the change** — update the reference instead (the change
   is the better truth). Editing L1/L2 → still needs explicit accept (S3).
3. **Both wrong — let me describe** — escape hatch for nuance.
4. **Skip** — record as rejected.

**Also offer tiered scope of fixes** when many findings cluster: present
the detected type's **foldback tiers** from its playbook, and ask that
tier question once. Ask individual challenges one at a time (the user's
answers may affect later challenges); for tier-scoped sweeps, ask once
and proceed.

**In `--auto` mode:** skip this Q&A. For each ambiguous finding pick the
most conservative option (the one that does NOT edit a higher-authority
artifact) and flag it `auto-decided` in the findings doc. S2/S3 still
bind — code and L1/L2 are never written.

### Step 6c — Surface flagged findings

`flagged` findings (code edits per S2, schema renames, etc.) are listed
in the findings doc but never auto-applied under any mode. They appear
in the final report so the user can write the fix themselves or hand it
to their implementation loop.

### Step 6d — Foldback log

Append to the findings doc:

```
## Folded back on <YYYY-MM-DD HH:MM>

**Scope chosen:** <user's tier selection if applicable>
**Sub-choices:** <any sub-decisions made>

| Finding | Status | Resolution | Commit |
|---|---|---|---|
| F-01 | auto-folded | annotate T-NNN.M | <hash> |
| F-02 | resolved-via-q&a | option (a) → extend SPEC §X | <hash> |
| F-03 | rejected-by-user | — | — |
| F-04 | flagged-for-user | code-change to <file> | — |

### Deferred
- MINOR/NIT (or Low/Info) items deliberately left for a later pass:
  <list or "none">
```

Commit the log update:

```
docs(challenges): mark fold-back of challenge-<DATE>

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

---

## Step 7 — Final report

One-message summary to the user:

```
/challenge <target> complete.
- Target: <path> (<type>, L<N>)
- Mode: <default | --report | --auto | diff>
- Blast radius: <P> primary refs / <Q> peers / <S> secondary refs
- External references: <N> systems checked
- Findings: <total>
  - <A> auto-folded (commits: <hashes>)
  - <Q> resolved via Q&A
  - <R> rejected by user
  - <F> flagged for user attention (code changes; no commit)
- Top takeaway: <one line>
- Suggested next: <e.g. "address flagged F-04 in the code",
  or "re-run /challenge after the next batch lands", or "commit the
  foldback group">
```

For `ai-work-diff`, also note: any open questions surfaced and not
closed (follow-ups for the next iteration), and whether the
convergence test should pass.

---

## Report structure

```markdown
# challenge review — <TARGET-NAME> — <YYYY-MM-DD>

**Target:** <path>
**Type:** <agent-spec | security-report | architecture-doc | api-spec
| code-quality | ai-work-diff | general-docs>
**Mode:** <default | audit-foldback | auto | diff>
**Target hierarchy level:** L<N>

## Verdict
<one paragraph, then a 1–5 score>

**Score scale:**
- 1/5 — Rework needed before more work.
- 2/5 — Significant gaps but salvageable.
- 3/5 — Reasonable starting point with known weaknesses.
- 4/5 — Strong, minor refinements suggested.
- 5/5 — Production-shaped, just keep going.

## Summary
<3–5 bullet headline takeaways. The user reads this first. Call out
the Q&A queue size and any flagged code changes up front.>

## Blast radius
<what was scanned: primary / peer / secondary references, with counts>

## Top 5 recommendations (prioritized)
1. ...
2. ...
3. ...
4. ...
5. ...

Each: rationale, affected files, effort (S/M/L), priority (NOW /
NEXT / DEFERRABLE).

## What we're getting right (preserve)
<Bulleted list — decisions worth defending if a future contributor
proposes "improving" them.>

## Findings
<every misalignment with the Step 3 fields, grouped by severity>

## Auto-fold queue
<clear-cut findings that will apply without asking>

## Q&A queue
<ambiguous findings that will be raised with the user (or
best-guessed in --auto)>

## Flagged for user attention
<findings requiring code edits or other risky changes; never
auto-applied under any mode>

## Industry comparison
### <Reference system 1>
<from that agent>

### <Reference system 2>
<from that agent>
...

## Open questions to resolve next
<consolidated, deduplicated list of the most important open
questions flagged across all reviewers, prioritized by blocking-ness>

## Sources
<all URLs cited, deduped>

## Provenance
- Reviewer: Claude Code, /challenge command
- Target: <path> (size, file count)
- Mode: <default | audit-foldback | auto | diff>
- Subagents spawned: <list with one-line summaries>
- Reference docs cited: <list of URLs fetched>
- Local clones used (if any): <list>

<!-- Foldback log appended by Step 6d if the user accepts
recommendations. See Step 6d for shape. -->
```

---

## Rules that apply to every phase

(Safety invariants **S1–S4** are defined once at the top and enacted in
Step 3 — they are not restated here.)

- **Never delete existing content.** Annotations are append-only.
  `replace` / `deprecate` preserve original under `<details>` blocks.
  History is data.
- **Always cite.** Every external claim needs a source URL; every
  finding cites `file:line` on **both** sides.
- **Specificity over volume.** Five sharp findings beat fifty fuzzy
  ones. "Tool layer could be cleaner" is useless. "The manifest in
  `task 08:42` lacks the `inputSchema` field MCP requires (see
  [URL]), so any future MCP wrapper will need a translation layer"
  is useful.
- **Frame divergences from industry as *choices*, not *mistakes*,**
  when there is a defensible reason. Only call something a mistake
  when there isn't.
- **State your interpretation.** When `$ARGUMENTS` is ambiguous or
  the target's level isn't obvious, say what you picked and why.
- **State each challenge in its strongest form;** let the user soften
  it if they want.
- **Drop what you can't cite.** If you can't cite, it's a hunch —
  drop it or downgrade to `low` and label `weak-evidence`.
- **Gate, don't rewrite.** This is a quality gate. If you find yourself
  re-authoring the work, pause and surface as `needs-decision`.
  Stylistic preferences are not challenges.
- **Modify nothing during Steps 1–5.** Edits happen only in Step 6
  (foldback), and only after the user picks a non-stop option or the
  finding is unambiguously `auto-foldback`.
- **Git safety:** never `git reset --hard`, `--no-verify`,
  `--no-gpg-sign`, or force-push.
- **Be honest about scope.** If the design is fine for a prototype but
  won't survive 10× growth, say both.
- **Name every file** a cross-cutting fix would touch, so the user can
  do the change in one pass.
- **Audit-foldback specifically:** before applying a security fix,
  verify the cited `file:line` still matches what the report
  described. Code may have moved. If line drift is small, re-locate;
  if the function has been rewritten, stop and re-evaluate with the
  user.

---

## `--auto` mode

Same flow, but Step 6b (Q&A) is replaced with best-guess resolution +
`auto-decided` flag. Every safety invariant **S1–S4** holds unchanged
(findings doc committed first, so `git revert` always restores;
per-scope commits; code never auto-applies; L1/L2 needs explicit
accept). Use when:

- Doing a periodic drift sweep and expecting well-bounded findings.
- A previous run on the same scope produced clean results.

Don't use when:

- A new design doc just landed (volatile state).
- You expect findings to touch L1/L2 — those still pause for Q&A
  regardless of `--auto`, and the user won't enjoy a string of forced
  prompts during what they thought was an unattended run.

---

## Cancellation

- If the user types anything during Steps 5–6 *before* the findings
  doc commit lands (S1), treat as cancel — stop after in-memory
  analysis but before any commit. State: "Cancelled before findings
  doc committed. No changes made."
- If the user types during Q&A: treat that input as the answer to the
  current question, OR (if clearly not an answer) treat as `skip` for
  the current finding and continue.
- "stop" or equivalent at any point → exit the loop, report what was
  done so far.

---

## Stop conditions

- All findings are auto-folded, user-decided, or flagged.
- User types "stop" or equivalent.
- Step 3 generates zero findings → print "no drift detected" and exit.

---

## Convergence test

After a full `/challenge` pass, a second invocation on the same git
state should produce zero findings. If it doesn't, the missing
findings from the first pass are themselves worth flagging — the
command got the work done but the gating logic missed something. Note
this in the report when it happens.

---

## Quality bar before writing the final report

The report should be useful to two readers:

1. **The user this afternoon** — deciding which findings to act on.
2. **A future engineer six months from now** — understanding why the
   design ended up the way it did and what was considered.

If the report wouldn't materially help either of them, iterate before
saving.

---

## Project wrapper pattern

Projects can install a thin wrapper at
`<repo>/.claude/commands/challenge.md` that injects defaults before
this command runs. Wrappers typically override:

- **Target** — force a specific path/glob (e.g., `tasks/*.md`).
- **Target type** — force a type even if auto-detect would pick
  another (e.g., always `agent-spec`).
- **Output path** — force a project-specific location.
- **Baseline reference systems** — replace or extend a playbook's
  reference list (e.g., add a named product as direct prior art).
- **Reviewer questions** — append project-specific consistency
  questions to a playbook's Agent A adds.
- **Foldback constraints** — e.g., "never edit files under
  `vendor/*.py`", "`.env` changes must go through the directive
  playbook, not direct writes".

A wrapper's job is to set defaults and then say "execute the global
`/challenge` command at `~/.claude/commands/challenge.md` applying the
above defaults, overriding any contrary defaults in the global
command". Wrapper defaults always win over global defaults; user
`$ARGUMENTS` always wins over both.
