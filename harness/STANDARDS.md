# Coding standards

Canonical standards for the Dynamic Traceback Harness. `/autodrive init` seeds a
copy to `<target-repo>/STANDARDS.md`; a target repo may override specific numbers
via `.harness.yaml` (`standards:` block). `/autodrive` inlines this file's text
into every implementer / reviewer / auditor sub-agent prompt (a standalone
`STANDARDS.md` does **not** auto-load — only `CLAUDE.md` does).

> Enforcement reality (accepted trade-off): most rules below
> are **review-judged** — the implementer and the audit gate are told to follow
> them. The mechanical backstops are: the PreToolUse scope hook, the test
> diff-flag, and the `verify[]` smoke checks (no-stub grep + insecure-pattern
> grep + build + lint + typecheck). Rules marked **[gated]** are mechanically
> checked in `verify[]` (for §8: the named pattern strings are grepped; the
> surrounding prose is review-judged). **[gated candidate]** = numeric and
> lintable; promoted to a hard gate when the tooling is wired.

---

## 1. NASA Power of Ten (adapted for application code)

1. **Simple control flow.** No `goto`-equivalents, no unbounded recursion. Any
   recursion must carry an explicit depth/size bound.
2. **Bounded loops.** Every loop must have a statically obvious upper bound. A
   loop that can't be shown to terminate is a defect.
3. **No surprise allocation in hot paths.** Prefer allocating up front; avoid
   per-iteration allocation in tight loops where the language makes it matter.
4. **Small units.** Function ≤ **60 lines**; file ≤ **400 lines** (override per
   repo in `.harness.yaml`). A unit that doesn't fit on a screen hides bugs.
5. **Assert liberally.** Validate preconditions and invariants; assertions are
   not dead code. Aim for ≥2 meaningful assertions per non-trivial function.
6. **Smallest scope.** Declare data at the tightest scope; no needless globals;
   no mutable shared state without a stated reason. Concurrency: every async
   result is awaited or explicitly detached with a stated reason; shared
   mutable state has one owner or a lock; no check-then-act on shared
   resources; concurrent work is bounded (pool/semaphore, never unbounded
   spawn).
7. **Check every return.** Handle or explicitly justify every error/return
   value. No silently ignored failures. Errors propagate with context
   (operation + relevant parameters, minus secrets); never catch-and-discard
   or catch-log-continue on a failure path.
8. **Limit indirection.** Keep nesting depth ≤ **4** and cyclomatic complexity
   ≤ **10** per function. Flatten with guard clauses and extracted helpers.
9. **No undefined behaviour / unsafe casts** without an explicit, commented
   reason.
10. **Clean build.** Code must compile/parse and pass lint + typecheck with **no
    new warnings**. **[gated]** — `verify[]` runs build + lint + typecheck.

---

## 2. Anti-slop (no typical-AI failure modes)

- **No invented APIs, filenames, flags, or imports.** If you reference it, it
  exists in the repo or in the **pinned version** of a declared dependency
  (check the lockfile, not memory). When unsure, read first.
- **No pasted code of unknown provenance.** If a block reproduces an external
  source, its license must be compatible and attributed.
- **No identifier spelling drift.** A symbol is spelled one way everywhere.
- **Match surrounding conventions** — imports, naming, error format, test style
  of the directory you're editing. Read a neighbouring file before writing.
- **No commentary cruft** — no "as an AI", no restating the code in prose, no
  dead scaffolding comments, no `console.log`/`print` debug left behind.
- **No gold-plating** — implement exactly the task's `acceptance[]`, nothing
  speculative ("Phase 2" capabilities don't appear in a Phase 1 task).
- **No over-engineering** — do the simplest thing that satisfies `acceptance[]`.
  A bug fix doesn't need surrounding cleanup; a one-shot change doesn't need a
  helper. No premature abstraction, no half-finished implementations, no
  speculative error handling / fallbacks / runtime validation for states that
  cannot occur, no feature flags or back-compat shims when the code can just
  change. (Defensive validation belongs only at system boundaries — §8. This is
  distinct from §1.5 assertions, which document internal invariants and stay.)

---

## 3. NO STUBS / NO MOCKS / NO STALES  **[gated]**

- **No stubs.** No `TODO`, `FIXME`, `NotImplementedError`, `pass`-only bodies,
  `throw new Error("not implemented")`, or empty handlers shipped as "done."
  A task reaches `done` only when the code actually does the thing.
- **No mocks in production paths.** Mocks/fakes live in tests only. A real
  integration is not "done" when it returns canned data.
- **No stales.** No dead code, no commented-out blocks, no orphaned files, no
  partial leftovers from a reverted attempt. Resume reconciliation must start from a clean or adopted tree, never a half-built one.
- **[gated]** — `verify[]` greps changed files for the marker set
  (`TODO|FIXME|NotImplementedError|not implemented|XXX`) and fails the task if a
  new one appears. (Genuine, tracked TODOs belong in a task/batch doc, not code.)

---

## 4. Modularization

- One module = one responsibility. If a file needs "and" to describe it, split.
- Public surface minimal; export only what callers need.
- Dependencies point one way — no import cycles. (`file_dependencies` /
  `depends_on[]` in a task must form a DAG.)
- Numbers (override in `.harness.yaml` `standards:`):
  `max_function_lines: 60`, `max_file_lines: 400`, `max_complexity: 10`,
  `max_nesting: 4`, `recursion: bounded-only`.

---

## 5. Testing — verify the code, not the test

- Every `acceptance[]` criterion → at least one test asserting it, traced to its
  requirement ID (`PRD-R… / SPEC-S… / UI-U…`).
- Structured, exact assertions — not loose `toContain`/`assertTrue(True)`.
- **On a failing test, suspect the code under test FIRST.** The default cause of
  a red test is a real bug in the implementation. Fix the bug.
- **Do not edit a test to make it pass** unless the test is *provably* wrong
  (wrong expected value per the SPEC, not "inconvenient"). Any test-file change
  in an implementation task is **diff-flagged to the audit gate** — it does not silently bless the green.
- **Tests are independent and deterministic** — any execution order, no shared
  mutable fixtures, no bare sleeps (poll with timeout), wrap the clock, no
  live network. In an autonomous loop the suite *is* the gate; a flaky test
  is a defect in the gate itself.
- **Never silence a red test** with `skip` / `xfail` / `.only` / commenting
  out — those markers are grepped (`insecure_markers`) and route to the audit
  gate like any other flagged pattern.
- A task is not `tested` until the new tests pass **and** the pre-existing suite
  still passes (no regressions).

---

## 6. Git discipline

- One logical change = one commit; conventional-commit prefix.
- Never `git reset --hard` on un-checkpointed work, never `--no-verify`,
  `--no-gpg-sign`, or force-push, unless explicitly instructed.
- Commit only the task's `scope[]` files (+ the ledger, which the loop owns).

---

## 7. UI & UX — no invented arrangements

Sections 1–6 and §8 govern code. This section governs **any user-facing
surface** — desktop apps, web apps, TUIs, dashboards. Every rule here is drawn
from a canonical primary source (Nielsen Norman Group, W3C WAI, Apple HIG,
Google Material 3, Microsoft Fluent, GNOME HIG, Shneiderman's *Designing the
User Interface* 6th ed., Rams via Vitsœ, Refactoring UI). See §7.10 for
citations. Where sources disagree (button placement, primary side) the
platform-convention rule wins — see §7.0.

### 7.0. The zeroth rule — follow the platform, do not invent

- **Nielsen H4 (Consistency and Standards):** Follow platform and industry
  conventions. Users spend most of their time on **other** apps and sites —
  Jakob's Law — so they expect yours to work like the ones they know.
- **If unsure where a control goes, copy the OS shell or the leading app in the
  same category.** Do not invent a novel arrangement of sidebars, headers,
  toolbars, or dialog buttons "because it looks cleaner." Novelty is a bug
  budget; spend it on the product, not the chrome.
- **Diverging from platform convention requires a stated reason** in the design
  doc or PR description. "Cleaner" is not a reason.

### 7.1. Baseline heuristics — read these once, apply always

Treat as a mental checklist during review; do not restate in comments.

- **Nielsen's 10 Usability Heuristics** — visibility of system status, match to
  real world, user control & freedom, **consistency & standards (H4)**,
  **error prevention (H5)** [destructive actions must be eliminated or
  confirmation-gated], recognition over recall, flexibility & efficiency,
  aesthetic & minimalist design, help users recognise/diagnose/recover from
  errors, help & documentation.
- **Shneiderman's 8 Golden Rules (2016 ed.)** — strive for consistency, seek
  universal usability, offer informative feedback, design dialogs to yield
  closure, prevent errors, permit easy reversal, keep users in control, reduce
  short-term memory load.
- **Rams' 10 Principles of Good Design** — useful, understandable, unobtrusive,
  honest, long-lasting, thorough to the last detail, aesthetic, innovative,
  environmentally friendly, **as little design as possible**.

### 7.2. Interaction laws with concrete thresholds

- **Response time (Miller/Nielsen):** **0.1s** feels instantaneous (no
  indicator needed); **1.0s** is the ceiling for uninterrupted flow (no
  indicator; may show a completed result); **10s** is the attention ceiling —
  above that, use a percent-done progress bar **and** a visible interrupt.
- **Loading-indicator escalation (NN/g):**
  - `< 1s` → no indicator; a flashing spinner is worse than nothing.
  - `2–10s`, single module → **spinner** (NN/g reserves looped animations for
    the 2–10s band; 1–2s shows the completed result, no indicator).
  - `2–10s`, full page → **skeleton screen** (wireframe preview of layout).
  - `> 10s` → **determinate progress bar** with duration estimate + interrupt.
- **Fitts's Law:** `T = a + b·log2(2D/w)` — larger targets closer to the
  cursor's current position are faster. Consequences: primary form-submit sits
  **adjacent to the last field**, not tucked into a corner. Screen edges and
  corners are "infinite" mouse targets (the pointer can't overshoot) — reserve
  them for high-frequency mouse actions. **Does not apply on touch** — fingers
  don't get infinite edges.
- **Hick–Hyman Law:** `RT = a + b·log2(n)` for choice reaction time. The slope
  is **not** a fixed constant; it collapses toward zero with practice and with
  high stimulus-response compatibility. Practical rule: reducing choice count
  helps novices in unfamiliar UI, but is not licence to hide power-user options
  behind extra menus.
- **Miller's 7±2 (correctly applied):** Miller 1956 described three unrelated
  task-specific limits and himself called their similarity "probably
  "a pernicious, Pythagorean coincidence." The durable lesson is **chunking**,
  not the number 7. Modern
  working-memory capacity is `~3–4 chunks` (Cowan 2001). **Do not use 7±2 as a
  menu-length cap** — menu selection is recognition, not recall, and NN/g
  explicitly refutes that application.
- **Jakob's Law (Nielsen 2000):** Users spend most of their time on **other**
  sites — they expect yours to work like the ones they already know. See §7.0.

### 7.3. Accessibility — WCAG 2.2 AA hard limits  **[gated candidate]**

These are numeric and lint-testable (axe-core, Lighthouse, Playwright).

- **Text contrast (SC 1.4.3):** `≥ 4.5:1` normal text; `≥ 3:1` large text
  (`≥ 18pt` regular or `≥ 14pt` bold).
- **Non-text contrast (SC 1.4.11):** `≥ 3:1` for UI component boundaries and
  meaningful state (focused/selected/checked); same ratio for meaningful
  graphics.
- **Target size (SC 2.5.8):** minimum `24 × 24 CSS px` per interactive target,
  with narrow exemptions (target spacing — a 24 px circle centred on the
  target intersecting no other target —, inline text targets,
  essential-position controls).
  Prefer `44 × 44 CSS px` on touch surfaces.
- **Text spacing override (SC 1.4.12):** layout must not break when a user
  applies `line-height ≥ 1.5×` font size, `paragraph spacing ≥ 2×` font size,
  `letter-spacing ≥ 0.12×`, `word-spacing ≥ 0.16×`.
- **Focus not obscured (SC 2.4.11, AA):** the focused component must not be
  **entirely** hidden by author-created content (sticky headers, cookie bars,
  etc.).
- **Focus appearance (SC 2.4.13, AAA target — still adopt):** focus ring
  perimeter `≥ 2 CSS px`, `≥ 3:1` contrast between focused vs unfocused
  same-pixel states.
- **Keyboard operable (SC 2.1.1):** every interactive control reachable and
  operable via keyboard; visible focus at all times; logical tab order matching
  visual reading order.
- **Semantic HTML / correct ARIA roles:** buttons are `<button>`, links are
  `<a>`, form controls are labelled. ARIA is a last resort, not a substitute.

### 7.4. Positioning — the section that stops the specific complaint

**Dialog buttons (LTR)** — the rule depends on host platform (Nielsen H4).
Never invent your own order.

| Platform             | Cancel / dismiss | Primary / confirm | Destructive        |
| -------------------- | ---------------- | ----------------- | ------------------ |
| macOS / iOS          | **Left**         | **Right** (default, blue) | Left, tinted red, separated from primary |
| GNOME / Linux        | **Left**         | **Right** (suggested-action) | Left, `destructive-action` red |
| Web / cross-platform | **Left**         | **Right**         | Left, error/danger colour |
| Windows (native)     | **Right**        | **Left**          | Left, distinct colour |

Regardless of platform: the **primary action is visually distinct** (filled),
cancel is secondary (outline / ghost), destructive uses the error colour role
and is **separated from primary by at least one control's width** so the muscle
memory that hits "OK" can't fire "Delete."

**Destructive action gating (Nielsen H5):** any destructive action needs one
of — a confirmation step, an undo affordance, or a delayed commit (soft-delete
+ toast with undo). "Are you sure?" alone is the weakest of the three.

**Form submit (Fitts's Law):** primary submit button sits **directly below or
beside the last field**, left-aligned with the fields (LTR). Never in a
disconnected footer far from the last input.

**Sidebar / primary navigation (LTR):**

- Vertical sidebar on the **left**. Every mainstream shell (macOS Finder,
  Windows Explorer, GNOME Files, Slack, VS Code, Linear, Notion) places
  primary nav on the left.
- **Microsoft Fluent NavigationView:** use **top nav** for `≤ 5` equally-
  important top-level items; use **left nav** for `5–10`. Above 10, either
  chunk into sections or move to a searchable command palette.
- Sidebar **width** — desktop `240–320px`, collapsed rail `48–64px`. Do not
  invent widths outside this band.
- Sidebar contains **navigation**, not primary actions. Primary create/action
  buttons live in the header/toolbar or as an in-content FAB (mobile).

**Header / title bar (LTR):**

- Title / logo on the **left**. Global actions (account, notifications, help,
  primary CTA) on the **right**. Search sits centred or right-of-title.
- **Back-button** on the **leading edge** (left in LTR) — every platform's
  convention. Never on the right.
- Toolbar height desktop `40–56px`. Do not stack multiple full-height headers.

**Toolbar action order:** most-frequent action on the leading edge (left);
group related actions with a divider between groups; put destructive/overflow
in a trailing overflow menu (⋯). Never scatter destructive actions among
primary ones.

**F-pattern (NN/g):** the F-shaped scan pattern emerges when text is a
formatless "wall" and users are scanning, not reading. It's a **failure mode
to design against**, not a target — break the wall with headings, bullets,
bold anchor text, and visual hierarchy so the eye is pulled by content, not
default entropy.

### 7.5. Layout & spacing

- **8-point grid** — every spacing, sizing, and offset value snaps to a
  multiple of `8px` (or `4px` for fine-grained icon and text alignment).
  Rejects `13px`, `27px`, `19px`. Both Material 3 and Fluent use a 4/8 base;
  Apple HIG uses standard spacing tokens that resolve to 4/8 multiples.
- **Spacing scale** (pick one and stick to it):
  `4, 8, 12, 16, 24, 32, 48, 64, 96` (a 1.5× progression above 16). Do not
  invent one-off values.
- **Alignment:** every element aligns to a shared vertical or horizontal edge.
  Rogue alignments are the top visual signal of AI-generated slop.
- **Whitespace comes from the outside** — pad the container, not the child.
  Never mix margin-top and margin-bottom to fake spacing.
- **Refactoring UI:** *start with too much whitespace and remove* — the
  overwhelming default failure mode is packing content too tight.

### 7.6. Typography

- **One family for UI text**, at most two (UI + monospace for code). Never
  ship three font families in one product.
- **Modular scale**, base `16px`, ratio `1.125` (minor second, dense UI) or
  `1.25` (major third, marketing/prose). Reject arbitrary sizes. Common
  desktop scale: `12, 14, 16, 18, 20, 24, 30, 36, 48, 60`.
- **Line height** — body copy `1.5–1.6` × font-size; headings tighter
  (`1.15–1.3`). Apple HIG and Material 3 both land in this range.
- **Line length** — `45–75 characters` per line for readable prose (Bringhurst,
  Baymard). `~66 chars` is the traditional optimum. Do not stretch body text
  across a 1600px viewport without a max-width.
- **Weight for hierarchy, not size alone (Refactoring UI):** emphasize with
  weight + colour; don't bump every heading up two sizes.
- **All-caps text** must get extra letter-spacing (`≥ 0.05em`); mixed-case does
  not.

### 7.7. Colour

- **Design in colour from the start (Refactoring UI):** the "grey then paint"
  approach yields lifeless UI — pick the palette early.
- **Semantic role tokens, not raw hex** — name colours by role: `surface`,
  `on-surface`, `primary`, `on-primary`, `secondary`, `error`, `on-error`,
  `border`, `focus-ring`. This is Material 3's model and it works.
- **Two neutrals + one accent, plus semantic states** is enough to ship. Any
  more requires a stated design reason.
- **60 / 30 / 10** (dominant / secondary / accent) is a reasonable default
  colour distribution — a widely-repeated heuristic without a single canonical
  source; treat as a rule of thumb, not law.
- **Dark mode ≠ invert every colour.** Never use pure `#000` for surfaces —
  Material 2 used `#121212` + lighten-with-elevation overlays; Material 3
  replaced that with tonal surface-container roles (baseline dark surface
  ≈ `#141218`). Either way: dark grey, higher surface = lighter. Reduce
  saturation of accents in dark mode; a colour tuned for white is too vivid
  on dark.
- **Colour is never the only signal** for state — pair with icon, label, or
  position (WCAG SC 1.4.1).

### 7.8. Component pattern rules

- **Empty state (NN/g, three rules):** (1) explain **why** the area is empty
  ("No records for the selected range"); (2) teach a **learning cue** ("Once
  you connect a source, results appear here"); (3) provide a **direct path**
  to fix it — a primary "Create" button and a secondary "Learn more" link.
  An empty state that just says "No data" is a defect.
- **Error state:** state **what happened**, **why** (as far as the user needs
  to know), and **the recovery action**. No stack traces to end users. Inline
  errors sit adjacent to the offending field; global errors sit at the top of
  the surface.
- **Feedback timing** (recap of §7.2): `< 100ms` = no indicator; `1s` result
  shown; `2–10s` spinner (module) or skeleton (page); `> 10s` progress bar +
  interrupt. Toasts auto-dismiss `4–6s` for success, `never` for destructive
  confirmation (require explicit user dismiss).
- **Focus:** the currently-focused element is **always** visibly indicated.
  Never `outline: none` without a replacement ring.
- **Loading skeletons** must preserve final layout — no reflow when data
  arrives.

### 7.9. Anti-slop for UI (the specific complaints)

- **Do not scatter primary actions.** One primary action per surface. If a page
  has two "primary" buttons the design is undecided — pick one.
- **Do not stack redundant navigation.** Global nav, page tabs, section
  breadcrumb, sub-tabs, and a sidebar filter panel is four layers of chrome
  hiding the content. Three is the tolerance ceiling; two is better.
- **Do not centre-align form labels or long-form text.** Labels align to their
  inputs (typically top-left); prose is left-aligned in LTR.
- **Do not use borders where spacing works.** Refactoring UI: *emphasise by
  de-emphasising* — a card doesn't need a border if the whitespace already
  separates it from neighbours.
- **Do not put icons without text labels** in primary navigation unless the
  icon is universal (search, home, settings). Tooltips are not a substitute
  for a label.
- **Do not render tables where a list works, or lists where a table works.**
  Rows of >4 attributes → table. Rows of ≤2 attributes → list. Cards are for
  browsing, not for scanning columns of data.
- **Do not use disabled buttons as the only feedback for form validation** —
  always tell the user *why* the button is disabled.
- **Do not animate for animation's sake.** Transitions `150–250ms`, easing
  `ease-out` or a specified curve; disable on `prefers-reduced-motion`.

### 7.10. Sources (canonical primaries)

- **Nielsen Norman Group** — heuristics, response times, Fitts, Jakob's Law,
  F-pattern, skeleton screens, empty states.
  `nngroup.com/articles/ten-usability-heuristics/`,
  `nngroup.com/articles/response-times-3-important-limits/`,
  `nngroup.com/articles/fitts-law/`,
  `nngroup.com/articles/f-shaped-pattern-reading-web-content/`,
  `nngroup.com/articles/skeleton-screens/`,
  `nngroup.com/articles/empty-state-interface-design/`.
- **W3C WAI — WCAG 2.2** (October 2023 Recommendation): `w3.org/TR/WCAG22/`.
- **Shneiderman** — 8 Golden Rules: `cs.umd.edu/~ben/goldenrules.html`
  (aligned with *Designing the User Interface*, 6th ed., 2016, §3.3.4).
- **Rams** via **Vitsœ** — 10 Principles: `vitsoe.com/us/about/good-design`.
- **Miller 1956** and **Cowan 2001/2015** (chunking, correct interpretation):
  `psychclassics.yorku.ca/Miller/`,
  `pmc.ncbi.nlm.nih.gov/articles/PMC4486516/`.
- **Hick–Hyman** — Proctor & Schneider 2018, *QJEP*.
- **GNOME HIG** — dialogs, sidebars, headers:
  `developer.gnome.org/hig/patterns/`.
- **Microsoft Learn / Fluent** — dialogs, NavigationView:
  `learn.microsoft.com/en-us/windows/apps/develop/ui/controls/`.
- **Apple HIG** — sidebars, toolbars, alerts, layout, colour, typography:
  `developer.apple.com/design/human-interface-guidelines/`.
- **Google Material 3** — dialogs, navigation drawer/rail, colour roles,
  typography, spacing tokens: `m3.material.io/`.
- **Refactoring UI** (Wathan/Schoger) — colour palette, line height, labels,
  visual hierarchy: `refactoringui.com/previews/`.
- **Baymard Institute** — line length: `baymard.com/blog/line-length-readability`.
- **Bringhurst**, *The Elements of Typographic Style*: `webtypography.net/2.1.2`.

---

## 8. Security — coding minimums

These rules target the *measured* AI-generation failure modes — XSS, log
injection, hardcoded credentials, command injection, slopsquatted
dependencies (Veracode 2025; Spracklen et al. — see §8.7). Grep-tier rules
are **[gated]**: the loop greps changed files for the `insecure_markers` set
(`.harness.yaml standards:`) with the same grep mechanism as the no-stub
check but a **different disposition** — a new match **routes to the audit
gate** with the implementer's justification (the gate decides; stub markers,
by contrast, are auto-fatal). Only the named pattern strings are grepped; the
surrounding prose is review-judged, backstopped by the security audit
(`.harness.yaml audit.security_surface`).

### 8.0. The zeroth rule — use vetted security machinery, do not invent

- **Never hand-roll crypto, auth, session management, sanitizers, or token
  generation** — use the platform/framework's vetted primitive (NIST SSDF
  PW.4). The security analogue of §7.0.
- **Fail closed.** Deny by default; on error, take the secure path. Catch
  specific exceptions; never expose stack traces or internals to end users
  (OWASP A10:2025).
- **All external input is untrusted until allowlist-validated** — params,
  headers, cookies, files, webhook payloads, LLM output. Validate on the
  server; client-side checks are UX, not security.

### 8.1. Injection — fix the sink  **[gated]**

- **SQL/NoSQL/LDAP/XPath: parameterized queries or the ORM only.** A
  string-built query is a defect regardless of "sanitization" (CWE-89).
- **Shell: argument arrays, never command strings.** No `shell=True`,
  `os.system`, backticks with interpolated input (CWE-78).
- **XSS: context-appropriate output encoding via the framework.** Raw-HTML
  sinks (`innerHTML`, `dangerouslySetInnerHTML`, `v-html`, `mark_safe`,
  `| safe`) require a sanitizer + a stated reason (CWE-79).
- **Paths: canonicalize, then verify containment** under the intended base
  directory for any user-influenced path (CWE-22).
- **No eval/exec/deserialization of external data** — `eval`, `exec`,
  `pickle.loads`, `yaml.load` without SafeLoader, `ObjectInputStream`
  (CWE-94/502). XML parsers: DTDs and external entities disabled — many are
  insecure by default (XXE, CWE-611).

### 8.2. Secrets  **[gated]**

- **No secrets in source, VCS, URLs, CLI args, or logs** — environment vars or
  a secret manager only. Anything matching a key pattern (`AKIA…`,
  `-----BEGIN … PRIVATE KEY`, `ghp_…`, `sk-…`, `password = "…"`) in a diff is
  a defect, including in tests and fixtures (use obviously-fake values).
- **Never log tokens, credentials, or PII.** Sanitize user input (strip CRLF)
  before it reaches a log line — log injection is the single highest measured
  AI failure rate.
- **No world-writable permissions** — `chmod 777` / `0o777` is a defect
  (CWE-732).

### 8.3. Crypto & randomness  **[gated]**

- **Security tokens come from a CSPRNG, ≥128 bits** (`secrets`,
  `crypto.randomBytes`, `SecureRandom`). `Math.random()` / Python `random` /
  `java.util.Random` for anything security-relevant is a defect (CWE-330).
- **AEAD only:** AES-GCM or ChaCha20-Poly1305, fresh random nonce per
  encryption. No ECB mode. No MD5/SHA-1 for any security purpose.
- **Passwords: Argon2id (m=19 MiB, t=2, p=1) or bcrypt cost ≥ 10** — never a
  general-purpose hash, salted or not (OWASP Password Storage CS).
- **TLS ≥ 1.2 (prefer 1.3); certificate validation is never disabled** — no
  `verify=False`, `InsecureSkipVerify`, `rejectUnauthorized: false` — not even
  "temporarily", not even in test code exercising production paths.

### 8.4. AuthN / AuthZ / web surface (review-judged)

- **Authorization on every server-side handler, deny by default**, and check
  resource **ownership** — an authenticated user must not reach another
  user's object by changing an ID (IDOR, CWE-862/639).
- **Framework session management.** Session ID ≥ 64 bits entropy; regenerate
  on login/privilege change; cookies `Secure; HttpOnly; SameSite=Lax|Strict`
  (prefer `Strict` + the `__Host-` prefix).
- **JWTs: verify the signature against a pinned algorithm** — reject
  `alg: none` and algorithm confusion — and validate `exp`/`aud`/`iss`.
  Decode-without-verify is a defect (ASVS ch. 3).
- **CSRF token on every state-changing request** (framework-generated);
  `SameSite` is defense-in-depth, not the control (CWE-352).
- **CORS: never `*` with credentials** — allowlist origins explicitly.
- **SSRF: user-influenced outbound requests go through a scheme + host
  allowlist**; block internal ranges and cloud metadata endpoints
  (`169.254.169.254`); don't follow redirects blindly (CWE-918).
- **Redirect targets from user input are allowlisted or relative-path-only**
  (CWE-601); **bind request bodies to an explicit field allowlist** — never
  `Object.assign(model, body)` / `**request.json` into a model (mass
  assignment, CWE-915).
- **File upload: extension allowlist** (not denylist), server-generated stored
  filename, stored outside the webroot, size limit enforced (CWE-434).

### 8.5. Supply chain — no slopsquatting (review-judged)

- **Before adding a dependency, verify it exists on the official registry and
  is the canonical, maintained package** (publisher, age, downloads). Up to
  ~20% of AI-suggested package names are hallucinated and attackers
  pre-register the recurring ones. Treat a manifest/lockfile change like a
  test-file change: it is diff-flagged to the audit gate, never slipped in
  silently.
- **Lockfile committed and honored; versions pinned.** Adding a dependency for
  functionality the stdlib or an existing dep already covers is a defect —
  every dep is attack surface (see §2).

### 8.6. LLM boundaries (when the code itself calls an LLM)

- **Model output is untrusted input.** Apply the same sink rules (§8.1)
  before it reaches shell, SQL, eval, HTML, or a file path (OWASP LLM05).
- **Authorization lives at the tool/action layer, never in prompt text**; no
  secrets in system prompts (OWASP LLM01/LLM02/LLM06).

### 8.7. Sources (canonical primaries)

- **OWASP** — Top 10:2025 `owasp.org/Top10/2025/`; ASVS 5.0 Level 1; Cheat
  Sheet Series (Password Storage, Session Management, TLS, Cryptographic
  Storage, File Upload, Injection Prevention) `cheatsheetseries.owasp.org`;
  LLM Top 10 (2025).
- **CWE Top 25 (2025)**: `cwe.mitre.org/top25/`.
- **NIST SSDF SP 800-218** (PW.4/5/7/8): `csrc.nist.gov/pubs/sp/800/218/final`.
- **Veracode**, *2025 GenAI Code Security Report*; **Spracklen et al.**,
  USENIX Security 2025 (package hallucination; Socket/Trend Micro write-ups) —
  the measured AI failure modes this section targets.
