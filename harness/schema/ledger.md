# Ledger schema

Two files under `<target-repo>/docs/`, kept consistent by the `/autodrive` loop
and the two hooks. Reference implementation: `harness/hooks/ledger.py`.

## `LEDGER.md` — human-readable forensic log

Append-only. **Never mutated in place.** One event per line:

```
- <UTC-iso> | <task-id> | <kind> <detail> | <detail-2> | <sha-or-dash>
```

The frontier is **derived** from this log + `LEDGER.state.json`; it is never
stored as a mutable prose section here (that was removed).

### Event kinds (closed set)

| kind | meaning |
|---|---|
| `transition` | a task state edge, e.g. `challenged→in-progress` |
| `intent` | write-ahead marker: `about-to-branch`, `about-to-commit <sha>` |
| `finding` | a discovered fact worth recording |
| `gotcha` | a sharp-edge note for future tasks |
| `traceback` | an out-of-scope write the PreToolUse guard denied |
| `needs-human` | the loop froze this task for a human (design reopen / no-progress) |
| `revert` | a capped/failed attempt was `git revert`ed (keeps the failed sha) |
| `lock` / `unlock` | single-writer lock acquired / released |

A failed `implemented→tested` transition records a **failure signature**
(`failing-test-id + diff-hash`) in its detail so the no-progress detector can
spot a repeating stall.

### Example

```
- 2026-06-26T14:03Z | TASK-API-AUTH | transition todo→challenged | challenge#2 convergent (0 net) | -
- 2026-06-26T14:21Z | TASK-API-AUTH | intent about-to-branch task/api-auth | - | -
- 2026-06-26T14:21Z | TASK-API-AUTH | transition challenged→in-progress | branch task/api-auth | -
- 2026-06-26T14:40Z | TASK-API-AUTH | transition in-progress→implemented | 3 files, scope clean | a1b2c3d
- 2026-06-26T14:52Z | TASK-API-AUTH | transition implemented→tested | 12 pass / 0 fail | a1b2c3d
- 2026-06-26T15:02Z | TASK-API-AUTH | gotcha refresh-token rotation precedes logout | traces PRD-R7 | -
```

## `LEDGER.state.json` — machine resume anchor (v2)

The loop trusts **this** on cold restart (not the prose log). `version` is now
`2`: it carries a multi-session **claim registry** (`active_tasks`) alongside the
legacy single-writer fields, which keep working unchanged (SPEC §S1). Schema:

```jsonc
{
  "version": 2,
  "lock": {                        // legacy single-writer lease — null when unlocked;
    "session": "<session-id>",     // still used by the non-parallel /autodrive path
    "expiry":  "2026-07-07T17:00Z"
  },
  "active_tasks": {                // CLAIM REGISTRY — one entry per live session (S1.1)
    "<session-id>": {
      "id":        "TASK-API-AUTH",
      "batch":     "020-api",
      "state":     "in-progress",  // matches the §3 task state machine
      "scope":     ["src/api/auth.ts", "tests/api/auth.test.ts"],  // globs ok
      "branch":    "task/TASK-API-AUTH",
      "worktree":  ".worktrees/TASK-API-AUTH",   // the agent's dedicated tree (S5)
      "lease_expiry": "2026-07-07T17:00Z",       // reap-eligible once this < now (S6)
      "heartbeat":    "2026-07-07T15:30Z",       // last liveness beat
      "pid":        48213,             // optional — reaper death-detection backstop (S6.4)
      "start_time": "Mon Jul  7 15:10:02 2026",  // optional — guards PID reuse (S6.4)
      "expect_sha": "a1b2c3d",         // tree-sha the next transition expects
      "attempts":   1,
      "failure_signature": null        // "<failing-test-id>:<diff-hash>" when stalled
    }
  },
  "active_task": {                 // DERIVED singleton view — see below (S1.2); null here
    "id": "TASK-API-AUTH", "...": "sole active_tasks entry, or null when 0 or ≥2 live"
  },
  "frontier": {
    "active_batch":  "020-api",
    "last_event_ts": "2026-07-07T15:30Z"
  }
}
```

### `active_tasks` — the claim registry

Keyed by **session id**; each value is one task claim. Fields:

| field | meaning |
|---|---|
| `id` | claimed task id |
| `batch` | its batch |
| `state` | current task state (§3 machine) |
| `scope` | the claimed `scope[]` globs — what the **scope guard** allows this session to write |
| `branch` | `task/<id>` working branch |
| `worktree` | the session's `.worktrees/<id>` tree (SPEC §S5) |
| `lease_expiry` | ISO-8601; a claim is reap-eligible once `lease_expiry < now` (§S6) |
| `heartbeat` | ISO-8601 of the last heartbeat; staleness vs the lease is a death signal (§S6.4) |
| `pid` *(optional)* | owner process pid — reaper backstop when the flock probe is inconclusive (§S6.4) |
| `start_time` *(optional)* | owner process start time — pins the pid so a **reused** pid isn't mistaken for the original (§S6.4) |
| `expect_sha` | tree-sha the next transition expects (resume reconciliation) |
| `attempts` | implement/test retry counter |
| `failure_signature` | `"<failing-test-id>:<diff-hash>"` when a no-progress stall is detected |

`claim_task()` writes the load-bearing subset (`id, scope, branch, worktree,
lease_expiry, heartbeat, attempts, failure_signature`); the loop and the reaper
fill in `batch/state/expect_sha/pid/start_time` as the task progresses.

### `active_task` — derived singleton view + v1→v2 migration

`active_task` is **no longer authored directly**; `save_state()` recomputes it on
every write as the **sole `active_tasks` entry when exactly one claim is live,
else `null`** (S1.2). This preserves the single-writer world for legacy readers:
with 0 or 1 claim, `active_scope()` and the PreToolUse scope guard behave exactly
as they did at v1. `active_scope(repo, session=…)` reads a specific session's
claim; with no session it falls back to this singleton view (S1.3).

A **v1 file** (no `active_tasks`, maybe an `active_task`) loads without error and
up-migrates in place: an existing `active_task` becomes one registry entry keyed
by its recorded `session` (or `"legacy"` when none), and `version` is set to `2`
(S1.1). The `/autodrive` loop is still the writer, now via `ledger.claim_task()` /
`ledger.set_active_task()` — the "active-task scope writer".

### `docs/.locks/` — flock coordination directory

Concurrency is coordinated by real OS file locks, **not** SQLite and **not** a
bare `O_EXCL` lockfile:

- **`docs/.locks/state.lock`** — every read-modify-write of `LEDGER.state.json`
  (claim, release, heartbeat, reap) holds `fcntl.flock(LOCK_EX)` on this file for
  the whole RMW, then writes the new state via a temp file + **`os.replace`**
  (atomic rename). So concurrent claims of *different* tasks never lose each
  other's updates, and a reader never sees a half-written file (S2.1).
- **`docs/.locks/<task>.claim`** — one per live claim, opened and **held with
  `flock` for the claim's lifetime**. This is the crux of crash recovery: the OS
  **auto-releases the flock when the owning process dies**, so the reaper detects
  death simply by acquiring the claim's `flock(LOCK_EX|LOCK_NB)` — success means
  the owner exited (S6.4). A bare `O_EXCL` lockfile was rejected because it goes
  **stale on crash** (nothing releases it); SQLite/WAL was rejected because it
  breaks the committed, git-diffable, human-readable resume anchor.

### Lease + heartbeat lifecycle (SPEC §S6)

- `heartbeat(repo, session)` refreshes both `heartbeat` and `lease_expiry`
  (`now + lease_ttl_minutes`) under the state lock; the loop calls it each
  iteration.
- `reap(repo)` reclaims every claim whose `lease_expiry < now` **and** whose owner
  is confirmed dead (layered: flock probe → `pid`+`start_time` → heartbeat
  staleness). Reclaim order: confirm death → remove any stale
  `<worktree>/.git/index.lock` → `git worktree remove --force` → `prune` → reset
  the task to `todo` if its worktree was clean, else move the branch to
  `quarantine/<id>-<sha>` and set the task `needs-human`. A claim **still inside
  its lease is never touched** — one live agent can never reap another (S6.3).

## Resume reconciliation

On restart, with an in-flight `active_task`, compare `ledger.tree_sha()` to
`active_task.expect_sha`:

| tree state | action |
|---|---|
| clean | restart the task from `challenged` |
| dirty, matches `expect_sha` | adopt — jump to the matching step |
| dirty, no match | quarantine the branch, emit `needs-human` |
