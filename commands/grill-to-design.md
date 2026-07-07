---
description: Grill the user into a ratified golden-doc skeleton — the Case-1 on-ramp to /domino. Grounds in existing code (brownfield) or the intent (greenfield), interviews until every field the golden docs require is resolved, then authors and ratifies PRD → HLD → ARCH → SPEC → UI.
argument-hint: "<rough intent — what you want to build>"
allowed-tools: Read, Glob, Grep, Write, Edit, Bash
---

# /grill-to-design — build the golden skeleton by interview

`/domino` refuses to start without a **ratified golden skeleton**
(`docs/design/{PRD,HLD,ARCH,SPEC,UI}.md`, each `status: ratified`). This command
is the on-ramp that produces one, when it does not yet exist, by grilling you
into the decisions the docs need — then authoring and ratifying them.

Use it when the skeleton is **missing or draft**. If a ratified skeleton already
exists and only the *prompt* is fuzzy, you want `/grill-me` instead (sharpen the
prompt, then `/domino`).

`$1` = your rough intent.

This command is **interactive** — it runs the human-driven `/grilling` loop. Never
invoke it from inside an autonomous loop (`/autodrive`, `/domino`, `/orchestrate`).

---

## Step 1 — Ground

Establish what is already true before you ask the human anything (grilling's rule:
*look facts up, put only decisions to me*).

- **Brownfield** (repo already has code): explore it. Harvest the modules, data
  stores, interfaces, and conventions that already exist — these become **facts**
  the interview must not re-ask, and constraints the design must honour.
- **Greenfield** (no code yet): the intent `$1` is your only ground.

**Completion criterion:** you can state, in one paragraph each, what already
exists and what `$1` is asking to add or change.

## Step 2 — Grill toward the slots

Run the `/grilling` loop — one question at a time, your recommended answer on
each, resolving dependencies before the decisions that rest on them. The agenda
is fixed: the interview is **done only when every slot below is resolved** (a
checkable, exhaustive criterion — do not stop at "shared understanding" while a
slot is still open). Look up any slot you can settle from Step 1's facts rather
than asking.

- **Context Profile** (PRD) — client persona, deployment target, userbase size,
  scaling horizon.
- **Product requirements** (PRD `PRD-R#`) — the goals, user stories, and
  acceptance behaviour that define "done" for the user.
- **Bounded contexts & flows** (HLD `HLD-D#`) — the subsystems and the major
  flows between them, staying conceptual.
- **Modules, stores, interfaces, tech** (ARCH `ARCH-M#`) — the concrete
  components and the technology choices that realise the HLD.
- **Testable acceptance** (SPEC `SPEC-S#.#`) — the precise, testable scenarios
  TASK acceptance criteria will `trace[]` to.
- **UI contract** (UI `UI-U#.#`) — screens, states, flows, behaviour **if this
  has a UI**. If it has none, record that decision explicitly so Step 3 marks UI
  not-applicable rather than leaving it open.

## Step 3 — Author

Feed the resolved answers into the golden-doc authors, in dependency order. Each
writes to `docs/design/` with `status: draft`.

1. `/spec/create-prd` — Context Profile + numbered `PRD-R#`.
2. `/spec/create-hld <PRD-ID>` — `HLD-D#`.
3. `/spec/create-arch <HLD-ID>` — `ARCH-M#`.
4. `/spec/create-spec <feature> <ARCH-ID>` — `SPEC-S#.#`.
5. `/spec/create-ui` — `UI-U#.#`, **only if** Step 2 resolved a UI. No UI → write
   a `UI.md` stub marked not-applicable so the skeleton is complete.

**Completion criterion:** all five files exist under `docs/design/`. Every
requirement, decision, module, and acceptance statement traces to an answer the
human gave in Step 2 — nothing invented past the interview.

## Step 4 — Ratify

Run `/challenge` over the skeleton and fold accepted findings back in, until every
doc's frontmatter reads `status: ratified`. Verify concretely:

```bash
for f in PRD HLD ARCH SPEC UI; do grep -q 'status: ratified' \
  "docs/design/$f.md" || echo "NOT RATIFIED: $f"; done
```

## Done — hand off

When the loop above prints nothing, the skeleton is ratified. Tell the user:
**"Golden skeleton ratified — run `/domino <intent>` to build it."** `/domino`'s
preconditions will now pass.
