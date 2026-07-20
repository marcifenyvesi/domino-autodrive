# Coding standards

Canonical standards for the Dynamic Traceback Harness. `/autodrive init` seeds a
copy to `<target-repo>/STANDARDS.md`; a repo overrides specific numbers via
`.harness.yaml` (`standards:`). `/autodrive` inlines this file into every
implementer / reviewer / auditor sub-agent prompt (a standalone `STANDARDS.md`
does **not** auto-load — only `CLAUDE.md` does).

**How to read this — one voice, both jobs.** Every rule is a single check,
written as the target state. The implementer makes it true; the reviewer / audit
gate flags the violation and cites the rule. "Flag Feature Envy" just means the
state below is absent — you never need a separate reviewer phrasing.

**Enforcement tiers.** **[gated]** — mechanically checked in `verify[]` (build +
lint + typecheck, plus a grep of the no-stub and `insecure_markers` sets); a new
match is auto-fatal (stubs) or routed to the audit gate (security).
**[gated candidate]** — numeric and lintable; a hard gate once the tooling is
wired. Everything else is **review-judged**, backstopped by the PreToolUse scope
hook and the test diff-flag.

---

## 1. Control flow, sizing & error discipline

Adapted from NASA's Power of Ten, minus the rules that assume no-GC real-time
code. Each is a defect when violated.

1. **Bounded recursion.** No unbounded recursion; any recursion carries an
   explicit depth/size bound.
2. **Bounded loops.** Every retry / poll / backoff loop carries a max-iteration
   or timeout bound. A loop driven by external input never runs unbounded.
3. **Small units.** Function ≤ **60 lines**, file ≤ **400 lines** (full number
   set and overrides in §4).
4. **Assert real invariants.** Validate genuine preconditions and invariants at
   unit boundaries so they document what must hold. Never manufacture assertions
   to hit a count, and never validate states that cannot occur (§2).
5. **Smallest scope.** Declare data at the tightest scope; no needless globals,
   no shared mutable state without a stated reason. Concurrency: await every
   async result or explicitly detach it (stated reason); shared mutable state
   has one owner or a lock; no check-then-act on shared resources; bound
   concurrent work (pool/semaphore, never unbounded spawn).
6. **Check every return.** Handle or explicitly justify every error/return value
   — no silently ignored failures. Errors propagate with context (operation +
   relevant params, minus secrets); never catch-and-discard or
   catch-log-continue on a failure path.
7. **Limit indirection.** Nesting depth ≤ **4**, cyclomatic complexity ≤ **10**
   per function; flatten with guard clauses and extracted helpers.
8. **No unsafe casts / undefined behaviour** without a commented reason — in TS,
   `as any` and non-null `!` on external data need justification.
9. **Clean build.** Compiles/parses and passes lint + typecheck with **no new
   warnings**. **[gated]**

---

## 2. Anti-slop — no typical-AI failure modes

- **No invented APIs, filenames, flags, or imports.** Everything referenced
  exists in the repo or in the **pinned version** of a declared dependency
  (check the lockfile, not memory). Unsure → read first.
- **No pasted code of unknown provenance** — a reproduced external block needs a
  compatible, attributed license.
- **One spelling per symbol** — no identifier drift.
- **Match surrounding conventions** — imports, naming, error format, test style
  of the directory you're editing. Read a neighbour first.
- **No commentary cruft** — no "as an AI", no prose restating the code, no dead
  scaffolding comments, no leftover `console.log`/`print`.
- **No gold-plating** — implement exactly the task's `acceptance[]`, nothing
  speculative (no "Phase 2" capability in a Phase 1 task).
- **No over-engineering** — the simplest thing that satisfies `acceptance[]`. No
  premature abstraction, no speculative error handling / fallbacks / validation
  for states that cannot occur, no feature flags or back-compat shims when the
  code can just change. (Boundary validation belongs at system edges — §8;
  internal invariant assertions — §1.4 — stay. Neither licenses speculative
  checks.)

---

## 3. No stubs / no mocks / no stales  **[gated]**

- **No stubs.** No `TODO`, `FIXME`, `NotImplementedError`, `pass`-only bodies,
  `throw new Error("not implemented")`, or empty handlers shipped as done. A task
  is `done` only when the code does the thing.
- **No mocks in production paths.** Mocks/fakes live in tests only; a real
  integration returning canned data is not done. (Where mocking is legitimate in
  tests — §5.)
- **No stales.** No dead code, commented-out blocks, orphaned files, or leftovers
  from a reverted attempt. Resume from a clean or adopted tree, never a
  half-built one.
- **[gated]** — `verify[]` greps changed files for
  `TODO|FIXME|NotImplementedError|not implemented|XXX` and fails on a new match.
  Tracked TODOs live in a task/batch doc, not code.

---

## 4. Modularization & module design

The size numbers are a **floor on mess, not a definition of good design** — a
module can pass every one and still be a shallow pass-through, itself a defect
(§4.1). Design deep modules; the numbers are the mechanical backstop.

- One module = one responsibility. If a file needs "and" to describe it, split.
- Public surface minimal; export only what callers need.
- Dependencies point one way — no import cycles (`file_dependencies` /
  `depends_on[]` form a DAG).
- Numbers (override in `.harness.yaml` `standards:`): `max_function_lines: 60`,
  `max_file_lines: 400`, `max_complexity: 10`, `max_nesting: 4`,
  `recursion: bounded-only`.

### 4.1. Deep modules — the design vocabulary

Interface-design language (after Ousterhout, *A Philosophy of Software Design*,
and Feathers). Use these terms exactly; they name the quality the numbers can't
measure.

- **Module** — anything with an interface and an implementation: function,
  class, package, or tier-spanning slice. **Interface** — everything a caller
  must know to use it correctly: not just the type signature, but invariants,
  ordering, error modes, and required config. **Seam** (Feathers) — where you can
  alter behaviour without editing in that place; where the interface lives.
- **Deep = small interface, lots of behaviour behind it. Shallow = interface
  nearly as complex as the implementation.** Prefer deep: remove methods,
  simplify params, hide more inside.
- **The deletion test.** Delete the module in your head. Complexity vanishes → it
  was a pass-through, inline it. Complexity reappears across N callers → it earns
  its keep.
- **The interface is the test surface.** If a test must reach *past* the
  interface (poking private state, querying the DB directly), the module is the
  wrong shape — see §5.
- **One adapter = a hypothetical seam; two = a real one.** Don't add
  port/interface indirection unless something actually varies across it
  (typically production + test). One adapter is just indirection (§2).
- **Design for testability:** accept dependencies rather than construct them
  inside; return results rather than mutate in place; keep the surface small — so
  the module tests through its interface without mocks (§5).
- **The testability-alone rule.** A task that adds a module should be answerable by the deletion test in one line; a shallow pass-through introduced solely to expose a seam that nothing actually varies across is a §4.1 defect, not a neutral choice.

### 4.2. Design smells — the Fowler baseline (review-judged)

A review/audit heuristic (Fowler, *Refactoring*, ch. 3), **not** a hard gate.
Each is a **judgement call** ("possible Feature Envy"), never automatic. Two
binding rules: a **documented repo standard overrides** the baseline, and **skip
anything tooling already enforces**. Each reads *what it is → how to fix*:

- **Mysterious Name** — doesn't reveal what it does/holds. → rename; if no honest
  name comes, the design is murky.
- **Duplicated Code** — same logic shape in more than one place. → extract, call
  from both.
- **Feature Envy** — a method reaches into another object's data more than its
  own. → move it onto the data it envies.
- **Data Clumps** — the same few fields/params keep travelling together. → bundle
  into one type.
- **Primitive Obsession** — a primitive/string standing in for a domain concept
  that deserves its own type. → give the concept its own small type.
- **Repeated Switches** — the same `switch`/`if`-cascade on one type recurs. →
  polymorphism, or one shared map.
- **Shotgun Surgery** — one logical change forces scattered edits. → gather what
  changes together into one module.
- **Divergent Change** — one module edited for several unrelated reasons. → split
  so each changes for one reason.
- **Speculative Generality** — abstraction/hooks for needs the spec doesn't have.
  → delete; inline until a real need shows (= §2, no gold-plating).
- **Message Chains** — long `a.b().c().d()` the caller shouldn't depend on. →
  hide the walk behind one method.
- **Middle Man** — a unit that mostly just delegates onward. → cut it, call the
  target directly.
- **Refused Bequest** — a subclass ignoring most of what it inherits. → drop
  inheritance, use composition.

---

## 5. Testing — verify the code, not the test

- Every `acceptance[]` criterion → at least one test asserting it, traced to its
  requirement ID (`PRD-R… / SPEC-S… / UI-U…`).
- **Structured, exact assertions** — not loose `toContain` / `assertTrue(True)`.
- **Test at the interface, not past it.** Assert observable outcomes through the
  public seam. A test that pokes private state or verifies via a side channel
  (querying the DB instead of calling the interface) breaks on behaviour-neutral
  refactors — wrong altitude. A good test reads like a spec and survives
  refactors (§4.1).
- **No tautological tests.** The expected value comes from an *independent*
  source — a known-good literal, a worked example, the SPEC — never recomputed
  the way the code computes it (`expect(add(a,b)).toBe(a+b)`, a hand-derived
  snapshot). A tautology passes by construction and can never disagree with the
  code.
- **Mock only at true system boundaries** — external APIs, the clock, randomness,
  sometimes the DB/filesystem. Never mock your own modules or internal
  collaborators: inject dependencies (§4.1) and test through the real interface.
- **On a failing test, suspect the code under test FIRST** — the default cause of
  red is a real bug. Fix the bug.
- **Do not edit a test to make it pass** unless it is *provably* wrong (wrong
  expected value per the SPEC, not "inconvenient"). Test-file changes are
  gated by the active TDD mode:
  - **`tdd_mode: off` (default)** — any test-file change is **diff-flagged to
    the audit gate** (review-judged); behaviour is unchanged from the prior
    rule.
  - **`tdd_mode: auto`** — after the test brief freezes the test paths, any
    change to a frozen test path is a **hard reject** at `scope_audit`
    (content-sha mismatch); no implementer edit is permitted. The only escape
    hatch for a provably-wrong test is to **re-run the test brief** (the task
    is bounded → `needs-human`), not an implementer edit.
    - **Unfrozen-impl tripwire (SPEC-S13.5.5).** Reaching the impl sub-step
      (`tdd_phase == "impl"`) with **no** frozen tests — a skipped, mis-sequenced,
      or empty `freeze-tests` — is itself a `scope_audit` violation
      (`tdd-impl-without-frozen-tests`) → `needs-human`. The freeze cannot be
      silently no-op'd to disable the content-sha check.
    - **RED-gate limitation (SPEC-S13.3.2, best-effort).** The invalid-red
      rejection (a bare collection error / `ImportError` is not valid red) is
      **best-effort / pattern-based**, not runner-return-code based. A Python
      import/collection error is caught; for an **unrecognized runner** the gate
      degrades to **necessary-only** (exit-nonzero ⇒ red) — do **not** assume the
      import-only rejection is universal.
    - **Seam eligibility (SPEC-S13.9.4).** TDD mode fires **only** for a
      brownfield-fixed-seam task or one carrying a ratified `## Contract` block; a
      greenfield task with neither is **not** `tdd_active` (ordinary path) and its
      exclusion is recorded as a loud claim-time ledger `finding`.
- **Independent and deterministic** — any execution order, no shared mutable
  fixtures, no bare sleeps (poll with timeout), wrap the clock, no live network.
  In an autonomous loop the suite *is* the gate; a flaky test is a defect in the
  gate.
- **Never silence a red test** with `skip` / `xfail` / `.only` / commenting out —
  those markers are grepped (`insecure_markers`) and route to the audit gate.
- A task is not `tested` until the new tests pass **and** the pre-existing suite
  still passes (no regressions).

---

## 6. Git discipline

- One logical change = one commit; conventional-commit prefix.
- Never `git reset --hard` on un-checkpointed work; never `--no-verify`,
  `--no-gpg-sign`, or force-push, unless explicitly instructed.
- Commit only the task's `scope[]` files (+ the ledger, which the loop owns).

---

## 7. UI & UX — no invented arrangements

Sections 1–6 and §8 govern code; §7 governs **any user-facing surface** —
desktop, web, TUI, dashboard. Every rule traces to a canonical primary (§7.10).
Where sources disagree (button placement), the platform-convention rule wins
(§7.0).

### 7.0. The zeroth rule — follow the platform, do not invent

- **Consistency (Nielsen H4) + Jakob's Law:** users spend most of their time on
  *other* apps and expect yours to match. If unsure where a control goes, copy
  the OS shell or the leading app in the category.
- **Don't invent** novel arrangements of sidebars, headers, toolbars, or dialog
  buttons "because it looks cleaner." Diverging needs a **stated reason** in the
  design doc / PR — "cleaner" is not one.

### 7.1. Baseline heuristics — apply, don't recite

The two load-bearing ones, cited by concrete rules below: **Nielsen H4
(consistency & standards)** → §7.0; **Nielsen H5 (error prevention)** →
destructive actions eliminated or confirmation-gated, §7.4. Also hold Nielsen's
10 Heuristics, Shneiderman's 8 Golden Rules, and Rams' 10 Principles (esp. *as
little design as possible*) — but a review flag names a concrete rule below, not
a heuristic in the abstract.

### 7.2. Interaction laws — the actionable thresholds

- **Response time (Miller/Nielsen):** `0.1s` instantaneous (no indicator); `1s`
  uninterrupted-flow ceiling (no indicator; may show the completed result);
  `10s` attention ceiling — beyond it, percent-done progress bar + visible
  interrupt.
- **Loading escalation (NN/g):** `<1s` no indicator (a flashing spinner is worse
  than nothing); `2–10s` module → **spinner**, full page → **skeleton**;
  `>10s` → **determinate progress bar** + estimate + interrupt.
- **Fitts's Law:** primary submit sits **adjacent to the last field**; screen
  edges/corners are infinite mouse targets — reserve for high-frequency mouse
  actions (not touch).
- **Hick–Hyman:** fewer choices help novices, but don't hide power-user options
  behind extra menus — the slope collapses with practice.
- **Miller's 7±2 is not a menu cap.** The lesson is **chunking** (~3–4 chunks,
  Cowan 2001), not the number 7; menu selection is recognition, not recall.
- **Jakob's Law:** users expect your app to work like the ones they know (§7.0).

### 7.3. Accessibility — WCAG 2.2 AA hard limits  **[gated candidate]**

Numeric and lint-testable (axe-core, Lighthouse, Playwright).

- **Text contrast (SC 1.4.3):** `≥ 4.5:1` normal, `≥ 3:1` large (`≥ 18pt` regular
  / `≥ 14pt` bold).
- **Non-text contrast (SC 1.4.11):** `≥ 3:1` for UI component boundaries and
  meaningful state (focused/selected/checked) and meaningful graphics.
- **Target size (SC 2.5.8):** `≥ 24×24 CSS px` per interactive target (narrow
  exemptions: 24px spacing, inline text, essential position). Prefer `44×44` on
  touch.
- **Text-spacing override (SC 1.4.12):** layout survives `line-height ≥ 1.5×`,
  `paragraph ≥ 2×`, `letter-spacing ≥ 0.12×`, `word-spacing ≥ 0.16×` font size.
- **Focus not obscured (SC 2.4.11):** the focused component is never *entirely*
  hidden by author content (sticky headers, cookie bars).
- **Focus appearance (SC 2.4.13):** focus ring perimeter `≥ 2 CSS px`, `≥ 3:1`
  focused-vs-unfocused contrast.
- **Keyboard operable (SC 2.1.1):** every control reachable and operable by
  keyboard; focus always visible; tab order matches visual reading order.
- **Semantic HTML / correct ARIA:** buttons are `<button>`, links are `<a>`, form
  controls are labelled. ARIA is a last resort, not a substitute.

### 7.4. Positioning

**Dialog buttons (LTR)** — depends on host platform (Nielsen H4); never invent
your own order.

| Platform             | Cancel / dismiss | Primary / confirm            | Destructive                              |
| -------------------- | ---------------- | ---------------------------- | ---------------------------------------- |
| macOS / iOS          | **Left**         | **Right** (default, blue)    | Left, tinted red, separated from primary |
| GNOME / Linux        | **Left**         | **Right** (suggested-action) | Left, `destructive-action` red           |
| Web / cross-platform | **Left**         | **Right**                    | Left, error/danger colour                |
| Windows (native)     | **Right**        | **Left**                     | Left, distinct colour                    |

Regardless of platform: primary is **visually distinct** (filled), cancel
secondary (outline/ghost), destructive uses the error role and is **separated
from primary by ≥ one control's width** so "OK" muscle memory can't fire
"Delete."

- **Destructive gating (Nielsen H5):** confirmation, undo, or delayed commit
  (soft-delete + toast). "Are you sure?" alone is the weakest.
- **Form submit (Fitts):** directly below/beside the last field, left-aligned
  with fields — never a disconnected footer.
- **Sidebar / primary nav (LTR):** vertical, on the **left** (every mainstream
  shell does this). Fluent NavigationView: **top nav** for `≤ 5` items, **left
  nav** for `5–10`, palette above 10. Width `240–320px` desktop, `48–64px` rail.
  Holds navigation, not primary actions.
- **Header (LTR):** title/logo left; global actions right; search centred or
  right-of-title; **back-button on the leading (left) edge**. Toolbar height
  `40–56px`; don't stack multiple full-height headers.
- **Toolbar order:** most-frequent leading (left); group with dividers;
  destructive/overflow in a trailing `⋯` menu — never scattered among primaries.
- **F-pattern (NN/g):** a **failure mode to design against**, not a target —
  break the wall with headings, bullets, bold anchors, hierarchy.

### 7.5. Layout & spacing

- **8-point grid** — every spacing/size/offset a multiple of `8px` (or `4px` for
  icon/text alignment). Rejects `13px`, `27px`. Material 3, Fluent, and Apple HIG
  all resolve to 4/8.
- **Spacing scale:** `4, 8, 12, 16, 24, 32, 48, 64, 96` — pick it, no one-offs.
- **Alignment:** every element shares a vertical/horizontal edge. Rogue alignment
  is the top visual signal of AI slop.
- **Whitespace from the outside** — pad the container, not the child; never fake
  spacing by mixing margin-top and margin-bottom.
- **Start with too much whitespace and remove** (Refactoring UI) — the default
  failure is packing too tight.

### 7.6. Typography

- **One UI family** (at most two: UI + monospace). Never three.
- **Modular scale**, base `16px`, ratio `1.125` (dense) or `1.25` (prose). Common
  desktop scale `12, 14, 16, 18, 20, 24, 30, 36, 48, 60` — no arbitrary sizes.
- **Line height** body `1.5–1.6`, headings `1.15–1.3`.
- **Line length** `45–75 chars` (~66 optimum) — cap body text width, don't stretch
  across a wide viewport.
- **Hierarchy via weight + colour, not size alone** (Refactoring UI).
- **All-caps** needs `≥ 0.05em` letter-spacing; mixed-case doesn't.

### 7.7. Colour

- **Design in colour from the start** (Refactoring UI) — "grey then paint" yields
  lifeless UI.
- **Semantic role tokens, not raw hex:** `surface`, `on-surface`, `primary`,
  `on-primary`, `secondary`, `error`, `on-error`, `border`, `focus-ring`
  (Material 3's model).
- **Two neutrals + one accent + semantic states** is enough; more needs a stated
  reason. `60/30/10` distribution is a rule of thumb, not law.
- **Dark mode ≠ invert.** Never pure `#000` for surfaces — dark grey, higher
  surface = lighter (M2 `#121212` + elevation; M3 tonal ≈ `#141218`); desaturate
  accents.
- **Colour is never the only signal** for state — pair with icon, label, or
  position (SC 1.4.1).

### 7.8. Component patterns

- **Empty state (NN/g):** (1) *why* it's empty, (2) a learning cue, (3) a direct
  path to fix (primary action + secondary "learn more"). "No data" alone is a
  defect.
- **Error state:** what happened + why + recovery action. No stack traces to
  users. Inline errors adjacent to the field; global errors at the top.
- **Feedback timing:** per §7.2. Toasts auto-dismiss `4–6s` for success,
  **never** for destructive confirmation (require explicit dismiss).
- **Focus:** the focused element is **always** visibly indicated — never
  `outline: none` without a replacement ring.
- **Loading skeletons** preserve final layout — no reflow when data arrives.

### 7.9. Anti-slop for UI

- **One primary action per surface** — two "primary" buttons = an undecided
  design.
- **Max three layers of chrome** (global nav + tabs + sidebar is already
  crowded); two is better.
- **Labels align to their inputs** (top-left); prose is left-aligned in LTR —
  never centred.
- **Whitespace over borders** — a card doesn't need a border if spacing already
  separates it (Refactoring UI: *emphasise by de-emphasising*).
- **Icons in nav need text labels** unless universal (search/home/settings);
  tooltips aren't labels.
- **Tables for >4 attributes/row, lists for ≤2.** Cards are for browsing, not
  scanning columns.
- **Disabled buttons must say *why*** — never the only feedback for validation.
- **No animation for its own sake.** Transitions `150–250ms`, `ease-out`; respect
  `prefers-reduced-motion`.

### 7.10. Sources (canonical primaries)

- **Nielsen Norman Group** — heuristics, response times, Fitts, Jakob's Law,
  F-pattern, skeletons, empty states: `nngroup.com/articles/`.
- **W3C WAI — WCAG 2.2** (2023 Recommendation): `w3.org/TR/WCAG22/`.
- **Shneiderman** — 8 Golden Rules (*Designing the User Interface*, 6th ed.):
  `cs.umd.edu/~ben/goldenrules.html`.
- **Rams** via **Vitsœ** — 10 Principles: `vitsoe.com/us/about/good-design`.
- **Miller 1956 / Cowan 2001** — chunking: `psychclassics.yorku.ca/Miller/`,
  `pmc.ncbi.nlm.nih.gov/articles/PMC4486516/`.
- **Hick–Hyman** — Proctor & Schneider 2018, *QJEP*.
- **GNOME HIG** `developer.gnome.org/hig/`, **Fluent**
  `learn.microsoft.com/windows/apps/design/`, **Apple HIG**
  `developer.apple.com/design/human-interface-guidelines/`, **Material 3**
  `m3.material.io/`.
- **Refactoring UI** (Wathan/Schoger); **Baymard** — line length; **Bringhurst**
  — *Elements of Typographic Style*.

---

## 8. Security — coding minimums

Targets the *measured* AI-generation failure modes — XSS, log injection,
hardcoded creds, command injection, slopsquatted deps (Veracode 2025; Spracklen
et al., §8.8). **[gated]** here greps `insecure_markers` and **routes a new match
to the audit gate** with the implementer's justification (stub markers, by
contrast, are auto-fatal); prose around the patterns is review-judged plus the
security audit (`.harness.yaml audit.security_surface`).

### 8.0. The zeroth rule — use vetted machinery, do not invent

- **Never hand-roll crypto, auth, session management, sanitizers, or token
  generation** — use the framework's vetted primitive (NIST SSDF PW.4). Security
  analogue of §7.0.
- **Fail closed.** Deny by default; on error take the secure path; catch specific
  exceptions; never leak stack traces or internals to users (OWASP A10:2025).
- **All external input is untrusted until allowlist-validated** — params,
  headers, cookies, files, webhooks, LLM output. Validate on the server;
  client-side checks are UX, not security.

### 8.1. Injection — fix the sink  **[gated]**

- **SQL/NoSQL/LDAP/XPath: parameterized queries or the ORM only.** A string-built
  query is a defect regardless of "sanitization" (CWE-89).
- **Shell: argument arrays, never command strings** — no `shell=True`,
  `os.system`, interpolated backticks (CWE-78).
- **XSS: framework output-encoding.** Raw-HTML sinks (`innerHTML`,
  `dangerouslySetInnerHTML`, `v-html`, `mark_safe`, `| safe`) need a sanitizer +
  a stated reason (CWE-79).
- **Paths: canonicalize, then verify containment** under the base dir for any
  user-influenced path (CWE-22).
- **No eval/exec/deserialization of external data** — `eval`, `exec`,
  `pickle.loads`, `yaml.load` without SafeLoader, `ObjectInputStream`
  (CWE-94/502). XML parsers: DTDs/external entities off (XXE, CWE-611).

### 8.2. Secrets  **[gated]**

- **No secrets in source, VCS, URLs, CLI args, or logs** — env vars or a secret
  manager only. Any key pattern (`AKIA…`, `-----BEGIN … PRIVATE KEY`, `ghp_…`,
  `sk-…`, `password = "…"`) in a diff is a defect, including tests/fixtures (use
  obviously-fake values).
- **Never log tokens, credentials, or PII.** Strip CRLF from user input before it
  reaches a log line — log injection is the highest measured AI failure rate.
- **No world-writable permissions** — `chmod 777` / `0o777` (CWE-732).

### 8.3. Crypto & randomness  **[gated]**

- **Security tokens from a CSPRNG, ≥128 bits** (`secrets`, `crypto.randomBytes`,
  `SecureRandom`). `Math.random()` / Python `random` / `java.util.Random` for
  anything security-relevant is a defect (CWE-330).
- **AEAD only** — AES-GCM or ChaCha20-Poly1305, fresh random nonce per
  encryption. No ECB. No MD5/SHA-1 for any security purpose.
- **Passwords: Argon2id (m=19 MiB, t=2, p=1) or bcrypt cost ≥ 10** — never a
  general-purpose hash (OWASP Password Storage CS).
- **TLS ≥ 1.2 (prefer 1.3); certificate validation never disabled** — no
  `verify=False`, `InsecureSkipVerify`, `rejectUnauthorized: false`, not even
  "temporarily", not even in test code exercising production paths.

### 8.4. AuthN / AuthZ / web surface (review-judged)

- **Authorization on every server-side handler, deny by default**, and check
  resource **ownership** — no reaching another user's object by changing an ID
  (IDOR, CWE-862/639).
- **Framework session management** — session ID ≥ 64 bits entropy; regenerate on
  login/privilege change; cookies `Secure; HttpOnly; SameSite` (prefer `Strict` +
  `__Host-`).
- **JWTs: verify signature against a pinned algorithm** — reject `alg: none` and
  algorithm confusion; validate `exp`/`aud`/`iss`. Decode-without-verify is a
  defect (ASVS ch. 3).
- **CSRF token on every state-changing request** (framework-generated);
  `SameSite` is defense-in-depth, not the control (CWE-352).
- **CORS: never `*` with credentials** — allowlist origins.
- **SSRF: user-influenced outbound requests through a scheme + host allowlist**;
  block internal ranges and `169.254.169.254`; don't follow redirects blindly
  (CWE-918).
- **Redirects from user input: allowlisted or relative-only** (CWE-601). **Bind
  request bodies to an explicit field allowlist** — never `Object.assign(model,
  body)` / `**request.json` into a model (mass assignment, CWE-915).
- **File upload:** extension allowlist (not denylist), server-generated stored
  name, stored outside the webroot, size-capped (CWE-434).

### 8.5. Supply chain — no slopsquatting (review-judged)

- **Before adding a dependency, verify it exists on the official registry and is
  the canonical, maintained package** (publisher, age, downloads). ~20% of
  AI-suggested names are hallucinated and attackers pre-register them. A
  manifest/lockfile change is diff-flagged to the audit gate, never silent.
- **Lockfile committed and honored; versions pinned.** A new dep for what the
  stdlib or an existing dep already covers is a defect — every dep is attack
  surface (§2).

### 8.6. Canned-resolver deny — xstate actor bodies  **[gated]**

Severity contract: **SPEC-S12.8.3**.

- **A canned production actor is auto-fatal** — the same class as a lexical stub
  (`stub_markers` tier). A named xstate actor logic (`fromPromise`, `fromCallback`,
  child-machine) whose body returns/resolves a literal or constant with **no
  external call** (network/db/fs/ipc) has no legitimate use in production code and
  is denied unconditionally.
- **Test/fixture paths are exempt.** A canned resolver in a `*.test.ts`,
  `__tests__/`, or `fixtures/` path is a legitimate test double and MUST pass.
- **Any escape is audit-approved, never implementer-self-annotated.** A bare
  `// @genuine-constant` (or any inline suppression comment) is a `# noqa`-style
  bypass and is **forbidden**. Overrides require an out-of-band audit approval, not
  a source annotation.

### 8.7. LLM boundaries (when the code calls an LLM)

- **Model output is untrusted input** — apply §8.1 sink rules before it reaches
  shell, SQL, eval, HTML, or a path (OWASP LLM05).
- **Authorization lives at the tool/action layer, never in prompt text**; no
  secrets in system prompts (OWASP LLM01/LLM02/LLM06).

### 8.8. Sources (canonical primaries)

- **OWASP** — Top 10:2025 `owasp.org/Top10/2025/`; ASVS 5.0 L1; Cheat Sheet
  Series `cheatsheetseries.owasp.org`; LLM Top 10 (2025).
- **CWE Top 25 (2025)** `cwe.mitre.org/top25/`.
- **NIST SSDF SP 800-218** (PW.4/5/7/8) `csrc.nist.gov/pubs/sp/800/218/final`.
- **Veracode** *2025 GenAI Code Security Report*; **Spracklen et al.** USENIX
  Security 2025 (package hallucination) — the measured AI failure modes here.

---

## 9. Process — challenge gate discipline (advisory)

These rules are **advisory prose**; they shape orchestrator and agent behaviour
but are not mechanical gates. They are canonical here and inlined into every
orchestrator prompt via `/autodrive`.

### 9.1. Throughput-off-gate + floor-unit disclosure

- **Challenge gates are not on the throughput budget.** The number of blind
  rounds is fixed by the floor (`challenge.min_passes` / `complex_passes` when
  the batch is `complexity: high`); the remaining turn budget does not reduce it.
- **Security and launch gates escalate, never compress.** When a batch is
  security- or launch-critical, running fewer rounds than the floor to save turns
  is a defect, not an optimisation.
- **Any intent to run below the floor halts immediately** and routes
  `set-state --to needs-human` before any work proceeds on that task.
- **Deviation reports use floor units, not softening adjectives.** State the
  shortfall as "1 of required ≥2 rounds completed" — never "one thorough round"
  or equivalent hedging language. Floor units are auditable; adjectives are not.
- **Security/launch batches MUST carry `complexity: high`** in `BATCH.md`, so
  the engine selects `complex_passes` and the floor is applied correctly.

### 9.2. Adjudicator ≠ round-runner (warn-only)

- The `challenge-adjudicate` step runs as its own **top-level step**, never
  inline inside a round subagent.
- The orchestrator records a self-declared round-runner vs adjudicator marker via
  `gate-event`. There is **no strict mechanical block** — the ledger has no
  subagent id, so enforcement is not deterministic.
- The `warn` sweep surfaces a same-actor declaration as a non-blocking warning;
  the gate still runs. This is **warn-only** (PRD-R43).
