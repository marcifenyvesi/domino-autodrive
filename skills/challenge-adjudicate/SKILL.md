---
name: challenge-adjudicate
description: Adjudicate independent /challenge rounds into ground truth — one cited verdict per union issue (CONFIRMED / REFUTED / STALE / UNVERIFIABLE-STATIC), conflicts settled against the tree, closing with a single foldback off CONFIRMED issues and a witness-count calibration table.
disable-model-invocation: true
---

# Challenge adjudicate

Companion to `/challenge --round`. It runs **after** ≥2 independent blind challenge
rounds exist for a date. The mode is **verification, not discovery**: every claim a
round already made gets reproduced or refuted against the tree; new findings belong in a
fresh round, not here. This skill never hunts for issues beyond the union set — an
unforeseen bug is another round's job.

It is to `/challenge` what `review-with-fable-comparison` is to `/review-with-fable`: N
independent producers, one adjudicating merge. The rounds are produced elsewhere (fresh
subagents running single-reviewer `/challenge --round k/n`, each blind to its siblings);
this skill consumes their `F-NN` findings and folds back once.

Two deliverables, both under `reviews/`:

- `reviews/<DATE>-challenge-adjudication.md` — one verdict record per union issue, plus
  the calibration table
- the foldback — a single pass off `CONFIRMED` issues only, via `/challenge`'s Step 6
  machinery (below)

## Verdict vocabulary (single source of truth)

Every union issue receives **exactly one** verdict from this table, and every verdict
cites its **reproduction step** — the file read, command run, or DNS/answer that produced
it. A verdict without a cited reproduction step is unwritten.

| Verdict | Meaning | Reproduction step it cites |
|---|---|---|
| `CONFIRMED` | Reproduced against the tree or runtime | the command/read that reproduced it |
| `REFUTED` | The anchor fails to show the claim | the anchor read + what it actually shows |
| `STALE` | Was true at the round's commit, since fixed | the fixing commit hash |
| `UNVERIFIABLE-STATIC` | Needs the live stack (browser/runtime behaviour) | the static portion checked + the runtime step that would settle it |

Evidence classes rank a verdict's strength (they replace any probability talk — a
percentage invented by the model is the judgment layer that fails to reproduce):
`confirmed-by-execution` > `confirmed-by-read` > `plausible-unverified`.

The `/challenge` round docs speak in `F-NN` findings with severity BLOCKER / MAJOR /
MINOR / NIT and fields `direction`, `edit_type`, `evidence` (`file:line` on both sides).
A round doc drops straight into the union matrix without translation — this skill keeps
that schema.

## Steps

### 1. Ingest — locate the rounds, build the union matrix

Glob the round docs for the target date: `reviews/<DATE>-challenge-r*.md`. **≥2 are
required**; with fewer than two, stop and report that adjudication needs at least two
independent rounds.

Build a **union matrix**: one row per underlying defect, columns for per-round presence
and the severity each round assigned. Dedup by the underlying defect, not by finding ID —
two rounds' `F-03` and `F-05` that anchor the same `file:line` with the same claim are
**one** union issue with witness count 2. From each row derive: a stable union issue ID,
the claim, the anchors each witness cited, the **witness count** (how many rounds raised
it), and two flag sets — **declared conflicts** (rounds making incompatible claims on the
same anchor) and **runtime-only claims** (browser/runtime behaviour; typically
single-witness, since static rounds cannot execute them).

**Done when:** every distinct defect across the rounds is exactly one union-matrix row
with its witness count, and every row carries an adjudication tier:
`conflict` → `single-witness` → `double-witness` → `triple-witness+`.

### 2. Adjudicate conflicts first — settle contradictions against the tree

Declared conflicts are proven disagreements: at least one round is wrong on each, so they
carry the highest information value and settle the union-critical count. Resolve each by
**reading the disputed anchor** (or running the command that measures it) and record which
round(s) erred — those errors feed the calibration table in step 4.

This **replaces the caller's old "oscillation → freeze / needs-human" rule.** A
contradiction between rounds is no longer a stop condition; it is a `conflict`-tier issue
settled by the code itself, with the erring round named.

**Done when:** every declared conflict holds one verdict that names the erring round(s)
and cites the read/command that settled it.

### 3. Adjudicate the rest — effort inverse to witness count

Effort runs **inversely to witness count**: a triple-witness+ issue gets a cheap
spot-check (all rounds independently anchored it — historically consistent); a
single-witness issue gets a full adversarial verify — it carries the measured
contradiction risk and has no independent corroboration.

Give each union issue exactly one verdict from the vocabulary above, each with its quoted
reproduction step. Fan out read-only adjudicator subagents in parallel if the union set is
large; each returns `verdict + reproduction step` and re-rates severity from the confirmed
evidence **blind** — before the witnesses' BLOCKER/MAJOR/MINOR/NIT ratings are revealed.
Compare the blind severity to the witnesses' ratings afterward: agreement is recorded; a
blind rating disagreeing with **all** witnesses is flagged `severity-dispute` and both
ratings are kept — flagged, never averaged.

`UNVERIFIABLE-STATIC` discipline: for a runtime/browser claim, verify the static portion
(spec text, gitignore state, fixture wiring) and **name the runtime step** that would
settle the rest — gate that step on the live stack. A static read is recorded as exactly
that; it **never upgrades to runtime confirmation**.

**Done when:** every union issue has exactly one verdict with a quoted (not paraphrased)
reproduction step, and every runtime claim is `UNVERIFIABLE-STATIC` with its runtime step
named.

### 4. Write the adjudication doc + calibration table

Write `reviews/<DATE>-challenge-adjudication.md`: the union matrix, then every verdict
record (each quoting its reproduction step and carrying its blind severity vs witnesses),
then the **calibration table** — REFUTED and STALE rates broken down by **witness count**:

| Witness count | Issues | CONFIRMED | STALE | REFUTED | UNVERIFIABLE-STATIC | False-positive rate |
|---|---|---|---|---|---|---|
| 3+ | .. | .. | .. | .. | .. | REFUTED / (issues − STALE − UNVERIFIABLE) |
| 2 | .. | .. | .. | .. | .. | .. |
| 1 | .. | .. | .. | .. | .. | .. |

The single-witness false-positive rate is the headline number: it is the measured
false-positive rate for single-witness findings, and it prices how much to trust a
single-witness finding in every future round. Close the table with the conflicts resolved
(and which round erred), any severity-disputes, and a per-round erring tally.
`reviews/2026-07-12-challenge-070-adjudication.md` is a worked example of exactly this
doc.

**Done when:** the doc exists with a verdict record per union issue, and the calibration
table breaks REFUTED/STALE down by witness count with the single-witness false-positive
rate stated.

### 5. Foldback — one pass, off CONFIRMED issues only, S1–S4 preserved

Fold back **once**, off `CONFIRMED` issues only (`REFUTED` / `STALE` /
`UNVERIFIABLE-STATIC` never edit the tree). Reuse `/challenge`'s Step 6 machinery rather
than inventing a second foldback path: delegate to

```
/challenge --report reviews/<DATE>-challenge-adjudication.md
```

which treats the adjudication doc as the audit report and folds its CONFIRMED findings
into the audited tree under the same safety invariants. Those four invariants hold here
unchanged:

- **S1 — Adjudication doc committed first.** The findings/adjudication doc is committed
  **before** any foldback edit, so a `git revert` restores the findings if anything
  downstream breaks.
- **S2 — Code (L4) is never auto-applied.** Any CONFIRMED fix that edits code is
  `flagged` and surfaced for the user, never written automatically.
- **S3 — L1/L2 edits gated by Q&A.** Editing a ratified design doc (L1) or Accepted ADR
  (L2) always pauses for explicit accept.
- **S4 — Per-scope commits.** One file's changes = one commit, so any single fold reverts
  cleanly.

**Done when:** the adjudication doc is committed (S1), the single foldback has run off
CONFIRMED issues only through Step 6, and every code/L1/L2 fix was gated per S2/S3 with
per-scope commits (S4).

### 6. Report

Report to the caller: verdict tallies (CONFIRMED / REFUTED / STALE /
UNVERIFIABLE-STATIC), the conflicts resolved and which round erred, the single-witness
false-positive rate, and what folded back vs what was flagged for the user.
