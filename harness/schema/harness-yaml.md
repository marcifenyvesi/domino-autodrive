# `.harness.yaml` schema

Optional file at the **target repo root**. Overrides harness defaults for that
repo. Every key is optional; omitted keys take the defaults shown.

```yaml
# .harness.yaml — Dynamic Traceback Harness per-repo config

paths:                      # where the doc-tree lives (defaults shown)
  design:   docs/design     # PRD.md HLD.md ARCH.md SPEC.md UI.md
  research: docs/research
  batches:  docs/batches
  ledger:   docs/LEDGER.md
  state:    docs/LEDGER.state.json
  standards: STANDARDS.md

challenge:
  min_passes: 2             # mandatory passes per artifact
  complex_passes: 3         # used when a BATCH has complexity: high
  # convergence + oscillation guards are always on

loop:
  retry_cap: 3              # implement/test retries before revert/block
  no_progress_repeat: 3     # same failure-signature N times -> needs-human
  revert_cycle_cap: 2       # reverted->todo cycles before needs-human
  lock_ttl_minutes: 90      # single-writer lock lease

audit:
  security_per_task: auto   # auto | always | never
                            # auto = only when BATCH.security or a
                            # security-surface file is touched
  security_surface:         # globs that force a per-task security audit
    - "**/auth/**"
    - "**/crypto/**"
    - "**/*secret*"
    - "**/api/**"
  playwright: auto          # auto = webapp UI tasks only | always | never

standards:                  # override STANDARDS.md numbers per language/repo
  max_function_lines: 60
  max_file_lines: 400
  max_complexity: 10
  max_nesting: 4
  recursion: bounded-only   # STANDARDS §1.1/§4 — the only supported value
  stub_markers:             # grepped by the no-stub verify[] check
    - TODO
    - FIXME
    - NotImplementedError
    - "not implemented"
    - XXX
  insecure_markers:         # grepped by the security verify[] check (STANDARDS §8)
    - "shell=True"          # a new match routes to the audit gate (see Notes)
    - "os.system("
    - "eval("
    - "exec("
    - "pickle.loads"
    - "yaml.load("          # bare load; matches safe usage too — justify at the gate
    - "ObjectInputStream"
    - "verify=False"
    - "InsecureSkipVerify"
    - "rejectUnauthorized: false"
    - "dangerouslySetInnerHTML"
    - ".innerHTML ="
    - "mark_safe("
    - "v-html"
    - 'execute(f"'          # string-built SQL heuristic (STANDARDS §8.1)
    - "md5("
    - "sha1("
    - "MODE_ECB"
    - "Math.random("
    - "-----BEGIN"          # private key material
    - "AKIA"                # AWS access key id
    - "ghp_"                # GitHub token
    - "chmod 777"
    - ".skip("              # test-silencing (STANDARDS §5)
    - ".only("
    - "xfail"

parallel:                   # multi-agent fan-out (SPEC §S5); omit to stay single-writer
  max: 4                    # max concurrent task agents (Anthropic 3–4 guidance)
  lease_ttl_minutes: 90     # claim lease TTL in minutes; a claim past this is reap-eligible
  heartbeat_minutes: 30     # how often the loop refreshes a live claim (keep < lease_ttl_minutes)

worktree:                   # per-agent worktree provisioning, run once on creation (SPEC §S5.2)
  link:                     # dirs symlinked into each fresh worktree (shared, never copied)
    - node_modules
  copy: []                  # paths copied into each fresh worktree (e.g. .env, build caches)
  ready: ""                 # one-time setup command in a fresh worktree (arg-array, shell=False)

merge:                      # sequential, verify-gated merge phase (SPEC §S7)
  base: ""                  # integration branch merges land on (default: current branch)
  verify: ""                # per-merge gate command; a red verify rolls back that one merge
  lockfile_regen: ""        # command run ONCE post-merge to reconcile lockfiles (never merged)

init:                       # what /autodrive init seeds into a new target repo
  seed_standards: true      # copy global STANDARDS.md -> repo root (if absent)
  seed_hooks: true          # copy hooks -> .claude/harness/hooks/ + wire settings
  seed_doctree: true        # create empty docs/design/* skeletons
```

## Parallel execution — `parallel:` / `worktree:` / `merge:`

New in the multi-agent engine (SPEC §S5–§S7, PRD R-5/R-6). All three sections are
optional; omit them entirely and `/autodrive` runs the legacy single-writer path
unchanged. The engine reads them via `parallel._harness_block()` (a small
indentation-aware parser — scalars and `- item` block lists only, no anchors).

### `parallel:` — concurrency + lease policy

| key | type | default | meaning |
|---|---|---|---|
| `max` | int | `4` | Maximum task agents that may hold a live claim at once. Read by `parallel.max_parallel()`. The **3–4 cap is deliberate** (Anthropic's orchestration guidance): beyond ~4 concurrent agents, merge/coordination overhead and scope-contention outweigh the throughput gain. Values `≤ 0` fall back to `4`. |
| `lease_ttl_minutes` | int | `90` | Lifetime of a claim's lease. `heartbeat` extends `lease_expiry` to `now + ttl`; once `lease_expiry < now` the claim is reap-eligible (SPEC §S6). Read by `lease._lease_ttl_minutes()`. |
| `heartbeat_minutes` | int | `30` | How often the loop should refresh a live claim's heartbeat. Keep it **well under `lease_ttl_minutes`** so a healthy agent never lets its own lease lapse. The `hold-claim` holder (SPEC §S6.5) reuses this **same key** (default 30) as its heartbeat-refresh cadence — the fleet launches one holder per claim, and it refreshes `heartbeat`/`lease_expiry` every `heartbeat_minutes`. No separate key. |

> SPEC §S10.3 refers to the lease knobs as `loop.lease_ttl_minutes` /
> `loop.heartbeat_minutes`; the implementation groups them with the other
> parallel-engine settings, so the engine reads them under **`parallel:`**.

### `worktree:` — per-agent worktree provisioning (run once on creation)

Each claimed task runs in its own `.worktrees/<id>` tree, provisioned from the
`worktree.link` / `worktree.copy` / `worktree.ready` keys.
`parallel._provision()` prepares a **freshly created** worktree only (never on resume, so a costly build is
not re-run):

| key | type | default | meaning |
|---|---|---|---|
| `link` | list[str] | `[]` | Paths symlinked from the main checkout into each worktree — for large shared, rebuild-free dirs like `node_modules`. |
| `copy` | list[str] | `[]` | Paths copied (files or dirs) into each worktree — for things that must be private per tree (e.g. a local `.env`, seed caches). |
| `ready` | str | `""` | A one-time setup command run in the fresh worktree (e.g. `npm ci`, `uv sync`). Executed as an **argument array with `shell=False`** (STANDARDS §8); empty string = no-op. |

### `merge:` — sequential verify-gated merge phase (SPEC §S7)

| key | type | default | meaning |
|---|---|---|---|
| `base` | str | current branch | Integration branch that finished `task/<id>` branches merge onto. |
| `verify` | str | harness selftests | Gate command run **after each individual merge**; a non-zero exit rolls back only that merge (`reset --hard` to the pre-merge commit) and escalates the branch to `needs-human`. A string is `shlex`-split (`shell=False`). |
| `lockfile_regen` | str | `""` | Command run **once** after a clean full sequence to reconcile lockfiles (which are kept out of agent scope and never merged). Empty = documented no-op naming the manual step. |

### Realistic example

```yaml
# .harness.yaml — a Node webapp running the parallel engine
parallel:
  max: 3
  lease_ttl_minutes: 60
  heartbeat_minutes: 20

worktree:
  link:
    - node_modules          # symlinked — no reinstall per worktree
  copy:
    - .env.local            # copied — each agent gets its own
  ready: "npm ci --prefer-offline"

merge:
  base: integration
  verify: "npm run -s verify"
  lockfile_regen: "npm install --package-lock-only"
```

## Notes

- The harness reads this with a tiny YAML parser in `/autodrive` (or PyYAML if
  present). Keep it flat and simple — no anchors/aliases.
- `standards:` here is the single source of truth for the numeric limits; the
  prose in `STANDARDS.md` should match. Only `stub_markers` /
  `insecure_markers` (plus build + lint + typecheck) actually run in
  `verify[]` — the size/complexity numbers are review-judged unless the target
  repo's own linter enforces them.
- `audit.security_surface`, `standards.stub_markers`, and
  `standards.insecure_markers` are the three lists most worth tuning per
  project. `insecure_markers` hits are not auto-fatal like stub markers: a new
  match routes to the audit gate with the implementer's justification (some
  patterns — `md5(` for a cache key, `eval(` in a test harness — have
  legitimate uses; the gate decides).
