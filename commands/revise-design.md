---
description: Revise a ratified design doc in response to a question — fan out deep research comparing industry best practice against this project's Context Profile (persona / deployment / userbase / scaling), then fold the answer back through /challenge. The autonomous escape hatch when the loop or the user hits a design question.
argument-hint: <design-doc-path-or-id> "<the question>"
allowed-tools: Read, Glob, Grep, Edit, Write, Bash, Agent, Skill, WebSearch, WebFetch, AskUserQuestion
---

# /revise-design — research-backed design revision

A design doc is ratified, but a question has arisen that
the current doc can't answer (the `/autodrive` loop emitted `needs-human` on a
structural design change, or you hit one by hand). This command answers it the
way you would: deep research against industry practice, weighed against *this
client's* reality, then folded back under the challenge gate.

## Inputs

1. The target design doc (`docs/design/PRD.md|HLD.md|ARCH.md|SPEC.md|UI.md`).
2. The **Context Profile** from `docs/design/PRD.md` (§2.2): client persona,
   deployment target, userbase size, scaling horizon. Every recommendation is
   weighed against these — "best practice" for a 10-user internal tool ≠ for a
   10M-user public SaaS.
3. Any existing `docs/research/` docs on the topic (don't redo settled research).

## Process

### Step 1 — frame the question
Restate the question precisely and identify which numbered requirements
(`PRD-R…`, `SPEC-S…`, …) it touches. If the question is vague, ask 1–2
clarifying questions (this is a design act, not the autonomous loop — Q&A is
allowed here).

### Step 2 — deep research
Invoke the `deep-research` skill (or fan out `Agent` researchers) with a brief
that **explicitly carries the Context Profile**:

> Compare industry best practice on <question> for a system whose persona is
> <persona>, deployed to <target>, serving <userbase>, that must scale to
> <horizon>. Contrast 2–4 approaches; for each: where it shines, where it breaks
> at our scale, and what it costs. Cite sources. Do NOT recommend the
> heavyweight option if our Context Profile doesn't warrant it.

Write the result to `docs/research/<YYYY-MM-DD>-<topic>.md` (a research doc, L6).

### Step 3 — propose the design delta
From the research, draft the concrete edit to the design doc: which requirements
change/add/remove, and why, traced to the research findings. Keep it minimal —
change the design, not the prose around it.

### Step 4 — challenge the revision (mandatory)
Run the challenge gate on the revised design doc as **N independent blind rounds
→ adjudicate → fold once** (N = `.harness.yaml challenge.min_passes`): fan out
fresh subagents each running `/challenge --round <k>/<N>`, then the
`challenge-adjudicate` skill folds `CONFIRMED` findings once. The research doc is a
reference; the **PRD remains north star**. Fold accepted findings.
- If the revision contradicts a higher doc (e.g. a SPEC change violating an HLD
  decision), the conflict surfaces — resolve upward or abandon the change.

### Step 5 — ratify + propagate
- On acceptance: bump the doc back to `status: ratified`, and record the change
  (which `…-R/S/D/M/U` IDs moved) so downstream BATCHES/TASKs referencing them
  can be re-challenged.
- Identify every BATCH/TASK whose `design_refs[]` cite a changed requirement and
  list them — they need a re-challenge before `/autodrive` builds them.

## Rules

- **Never** silently rewrite a ratified design doc — the revision always passes
  through Step 4's challenge gate.
- **Context Profile governs.** Flag any recommendation that over-engineers for
  this client's actual persona/scale as a *rejected* option with the reason.
- Research docs are cite-only context (L6); they inform the design but don't
  override the PRD.
- Commit the research doc and the design revision separately (research first, so
  the rationale is durable even if the revision is rejected).

## Output

Report: the question, the approaches compared, the chosen delta + why (in terms
of the Context Profile), the challenge verdict, and the downstream BATCH/TASK
list that now needs re-challenging.
