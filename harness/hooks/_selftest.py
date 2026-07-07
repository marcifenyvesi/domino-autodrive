#!/usr/bin/env python3
"""Self-test for the Phase 0 harness hooks. No external deps.

Creates a throwaway git repo in a temp dir, exercises the ledger library and
both hooks end-to-end, and asserts real behaviour (not mocks). Exits non-zero on
the first failure with a clear message.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ledger  # noqa: E402
import scope_algebra  # noqa: E402
import precommit_scope  # noqa: E402
import scope_guard  # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {extra}")


def run_hook(script: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HERE / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def git(repo: Path, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True)


def _write_v1(root: Path, active_task) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    state = {"version": 1, "lock": None, "active_task": active_task,
             "frontier": {"active_batch": None, "last_event_ts": None}}
    (root / "docs" / "LEDGER.state.json").write_text(json.dumps(state), encoding="utf-8")


def registry_tests(td: Path) -> None:
    print("claim registry + atomic claim (S1/S2):")

    # A1 — v1->v2 migration: an existing active_task with a recorded session
    # becomes one registry entry keyed by that session.
    r1 = td / "mig-sess"; r1.mkdir()
    _write_v1(r1, {"id": "TASK-OLD", "scope": ["a/**"], "session": "sess-old"})
    st = ledger.load_state(r1)
    check("v1->v2 version bumped", st["version"] == 2)
    check("migrated entry keyed by recorded session",
          st["active_tasks"].get("sess-old", {}).get("id") == "TASK-OLD")
    check("derived active_task preserved after migration",
          st["active_task"]["id"] == "TASK-OLD")
    # A1 — no recorded session migrates under the "legacy" key.
    r2 = td / "mig-legacy"; r2.mkdir()
    _write_v1(r2, {"id": "TASK-L", "scope": ["b/**"]})
    check("session-less active_task migrated under 'legacy'",
          ledger.load_state(r2)["active_tasks"].get("legacy", {}).get("id") == "TASK-L")
    # A1 — a v1 file with no active_task migrates to an empty registry.
    r3 = td / "mig-empty"; r3.mkdir()
    _write_v1(r3, None)
    check("empty v1 migrates to empty registry",
          ledger.load_state(r3)["active_tasks"] == {})

    # A2/A3 — derived active_task view + session-scoped active_scope.
    d = td / "derive"; d.mkdir()
    check("claim #1 succeeds", ledger.claim_task(d, "s1", "TASK-1", ["p1/**"]) is True)
    check("1 claim -> active_task is that entry",
          ledger.load_state(d)["active_task"]["id"] == "TASK-1")
    check("active_scope by session s1", ledger.active_scope(d, "s1") == ["p1/**"])
    check("active_scope no-session (1 claim) unchanged",
          ledger.active_scope(d) == ["p1/**"])
    check("claim #2 (other session+task) succeeds",
          ledger.claim_task(d, "s2", "TASK-2", ["p2/**"]) is True)
    check("2 claims -> active_task null", ledger.load_state(d)["active_task"] is None)
    check("2 claims -> active_scope no-session None", ledger.active_scope(d) is None)
    check("active_scope by session s2", ledger.active_scope(d, "s2") == ["p2/**"])
    check("active_scope unknown session -> None", ledger.active_scope(d, "nope") is None)

    # A5 — claim refusal: same task, or a session already holding a claim.
    check("same task refused for a different session",
          ledger.claim_task(d, "s9", "TASK-1", ["q/**"]) is False)
    check("session already holding a claim is refused",
          ledger.claim_task(d, "s1", "TASK-9", ["z/**"]) is False)

    # A7 — release idempotent + derived view recomputes.
    ledger.release_claim(d, "s2")
    check("release drops the entry", "s2" not in ledger.load_state(d)["active_tasks"])
    check("back to 1 claim -> active_task = remaining entry",
          ledger.load_state(d)["active_task"]["id"] == "TASK-1")
    check("claim file exists while held", (d / "docs" / ".locks" / "TASK-1.claim").exists())
    ledger.release_claim(d, "s1")
    check("release last -> active_task null", ledger.load_state(d)["active_task"] is None)
    check("claim file removed on release",
          not (d / "docs" / ".locks" / "TASK-1.claim").exists())
    check("release is idempotent (missing entry, no raise)",
          ledger.release_claim(d, "s1") is None)

    # A6/A8 — N concurrent claimers of the SAME task: exactly one winner.
    race = td / "race"; race.mkdir()
    n, children = 8, []
    for i in range(n):
        pid = os.fork()
        if pid == 0:  # child: attempt the claim, report via exit code
            won = ledger.claim_task(race, f"sess-{i}", "TASK-RACE", ["r/**"])
            os._exit(0 if won else 1)
        children.append(pid)
    winners = 0
    for pid in children:
        _, status = os.waitpid(pid, 0)
        if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
            winners += 1
    check("exactly one concurrent claimer wins", winners == 1, f"winners={winners}")
    rst = ledger.load_state(race)
    check("registry holds exactly one race entry",
          sum(1 for e in rst["active_tasks"].values() if e.get("id") == "TASK-RACE") == 1)


def _iso_offset(minutes: int) -> str:
    """A now_iso()-format UTC timestamp offset by `minutes` (negative = past)."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def _write_lock_state(root: Path, lock, active_task=None, active_tasks=None) -> None:
    """Write LEDGER.state.json directly with a chosen lock/active_task/active_tasks."""
    (root / "docs").mkdir(parents=True, exist_ok=True)
    state = {"version": 2, "lock": lock, "active_task": active_task,
             "active_tasks": active_tasks or {},
             "frontier": {"active_batch": None, "last_event_ts": None}}
    (root / "docs" / "LEDGER.state.json").write_text(json.dumps(state), encoding="utf-8")


def lock_liveness_tests(td: Path) -> None:
    print("lock liveness / orphan reclaim (heartbeat):")

    # ORPHAN reclaimed: held lock, stale heartbeat (30m ago), no active_task, no
    # live claim -> a DIFFERENT session reclaims.
    r = td / "lk-orphan"; r.mkdir()
    _write_lock_state(r, {"session": "dead", "expiry": _iso_offset(60),
                          "heartbeat": _iso_offset(-30)})
    check("orphaned lock (stale heartbeat, no work) reclaimed by other session",
          ledger.acquire_lock(r, "fresh") is True)
    check("reclaim stamps the new holder + heartbeat",
          ledger.load_state(r)["lock"]["session"] == "fresh"
          and ledger.load_state(r)["lock"].get("heartbeat"))

    # NOT reclaimed when working: same stale heartbeat but active_task set.
    r = td / "lk-working"; r.mkdir()
    _write_lock_state(r, {"session": "dead", "expiry": _iso_offset(60),
                          "heartbeat": _iso_offset(-30)},
                      active_task={"id": "TASK-W", "scope": ["x/**"]})
    check("stale heartbeat but active_task set -> different session REFUSED",
          ledger.acquire_lock(r, "fresh") is False)

    # NOT reclaimed with a live claim: stale heartbeat, no active_task, but an
    # active_tasks entry with a future lease_expiry.
    r = td / "lk-claim"; r.mkdir()
    _write_lock_state(r, {"session": "dead", "expiry": _iso_offset(60),
                          "heartbeat": _iso_offset(-30)},
                      active_tasks={"s1": {"id": "TASK-C", "scope": ["y/**"],
                                           "lease_expiry": _iso_offset(45)}})
    check("stale heartbeat but a live claim exists -> REFUSED",
          ledger.acquire_lock(r, "fresh") is False)

    # Missing/None heartbeat on a held (non-expired) lock -> conservative REFUSE.
    r = td / "lk-nohb"; r.mkdir()
    _write_lock_state(r, {"session": "dead", "expiry": _iso_offset(60)})
    check("missing heartbeat on live lock -> REFUSED (conservative)",
          ledger.acquire_lock(r, "fresh") is False)
    r = td / "lk-nonehb"; r.mkdir()
    _write_lock_state(r, {"session": "dead", "expiry": _iso_offset(60),
                          "heartbeat": None})
    check("None heartbeat on live lock -> REFUSED (conservative)",
          ledger.acquire_lock(r, "fresh") is False)

    # TTL-expired lock -> reclaimed (existing behaviour preserved).
    r = td / "lk-ttl"; r.mkdir()
    _write_lock_state(r, {"session": "dead", "expiry": _iso_offset(-5),
                          "heartbeat": _iso_offset(-1)})
    check("TTL-expired lock reclaimed", ledger.acquire_lock(r, "fresh") is True)

    # Fresh lock: a live holder blocks a different session (regression).
    r = td / "lk-fresh"; r.mkdir()
    check("session1 acquires fresh lock", ledger.acquire_lock(r, "s1") is True)
    check("session2 blocked while s1 live", ledger.acquire_lock(r, "s2") is False)

    # refresh_lock bumps the heartbeat forward for the holder.
    _write_lock_state(r, {"session": "s1", "expiry": _iso_offset(60),
                          "heartbeat": _iso_offset(-30)})
    ledger.refresh_lock(r, "s1")
    check("refresh_lock updates the held lock's heartbeat",
          ledger._minutes_since(ledger.load_state(r)["lock"]["heartbeat"]) < 1)
    check("refreshed lock is no longer orphaned",
          ledger.acquire_lock(r, "s2") is False)


def _build_scope_fixture(root: Path) -> None:
    """A small tree mirroring the S3.3 truth-table paths (real files on disk)."""
    for rel in (
        "harness/hooks/ledger.py",
        "harness/hooks/_selftest.py",
        "harness/hooks/scope_algebra.py",
        "harness/autodrive/init.py",
        "docs/design/SPEC.md",
    ):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")


def scope_algebra_tests(td: Path) -> None:
    print("scope algebra (materialized glob-set overlap, S3):")
    fx = td / "scope-fx"; fx.mkdir()
    _build_scope_fixture(fx)
    ov = lambda a, b: scope_algebra.scopes_overlap(fx, a, b)

    # A3 — the S3.3 truth table, encoded against the fixture tree.
    check("disjoint literal files -> False",
          ov(["harness/a.py"], ["harness/b.py"]) is False)
    check("harness/** vs a real nested file -> True",
          ov(["harness/**"], ["harness/hooks/ledger.py"]) is True)
    check("sibling ** dirs are disjoint -> False",
          ov(["harness/hooks/**"], ["harness/autodrive/**"]) is False)
    check("harness/** vs **/_selftest.py share a real file -> True",
          ov(["harness/**"], ["**/_selftest.py"]) is True)
    check("empty scope reserves nothing -> False",
          ov([], ["harness/x.py"]) is False)

    # A2 — symmetry across every truth-table row.
    rows = [(["harness/a.py"], ["harness/b.py"]),
            (["harness/**"], ["harness/hooks/ledger.py"]),
            (["harness/hooks/**"], ["harness/autodrive/**"]),
            (["harness/**"], ["**/_selftest.py"]),
            ([], ["harness/x.py"])]
    check("overlap is symmetric",
          all(ov(a, b) == ov(b, a) for a, b in rows))

    # A1 — a planned, not-yet-created file still reserves its path.
    check("planned new file not on disk",
          not (fx / "harness/hooks/newthing.py").exists())
    check("planned new file reserves its path (reflexive)",
          ov(["harness/hooks/newthing.py"], ["harness/hooks/newthing.py"]) is True)
    check("planned new file overlaps a glob that would cover it",
          ov(["harness/hooks/newthing.py"], ["harness/hooks/**"]) is True)
    check("expand of empty globs is the empty set",
          scope_algebra.expand_scope(fx, []) == set())


def precommit_tests(td: Path) -> None:
    print("precommit_scope hook (S8.1/S8.2/S8.5):")
    repo = td / "pc-repo"; repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("x\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
    (repo / "src").mkdir(); (repo / "lib").mkdir()
    # fixture claim: this repo is the committing worktree; scope = src/**
    ledger.claim_task(repo, "sess-pc", "TASK-PC", ["src/**"],
                      branch="task/pc", worktree=str(repo))

    # 1) in-scope only -> allow
    (repo / "src" / "a.py").write_text("a\n"); git(repo, "add", "src/a.py")
    r = run_hook("precommit_scope.py", {}, repo)
    check("in-scope staged -> allow (exit 0)", r.returncode == 0, r.stderr)

    # 2) out-of-scope staged -> block, names the file
    (repo / "lib" / "b.py").write_text("b\n"); git(repo, "add", "lib/b.py")
    r = run_hook("precommit_scope.py", {}, repo)
    check("out-of-scope staged -> block (non-zero)", r.returncode != 0, r.stderr)
    check("block message names offender", "lib/b.py" in r.stderr, r.stderr)
    git(repo, "reset", "-q", "lib/b.py")

    # 3a) sensitive .env -> block (deny-list)
    (repo / ".env").write_text("SECRET=x\n"); git(repo, "add", "-f", ".env")
    r = run_hook("precommit_scope.py", {}, repo)
    check(".env staged -> block (deny-list)", r.returncode != 0, r.stderr)
    check(".env named in block message", ".env" in r.stderr, r.stderr)
    git(repo, "reset", "-q", ".env")
    # 3b) *.key inside scope still blocks (deny-list beats scope, A5)
    (repo / "src" / "id_rsa.key").write_text("k\n")
    git(repo, "add", "src/id_rsa.key")
    r = run_hook("precommit_scope.py", {}, repo)
    check("in-scope .key staged -> block (deny-list beats scope)",
          r.returncode != 0, r.stderr)
    git(repo, "reset", "-q", "src/id_rsa.key")

    # 4) no claim for this worktree -> fail-open
    ledger.release_claim(repo, "sess-pc")
    (repo / "lib" / "c.py").write_text("c\n"); git(repo, "add", "lib/c.py")
    r = run_hook("precommit_scope.py", {}, repo)
    check("no claim for worktree -> allow (fail-open, exit 0)",
          r.returncode == 0, r.stderr)
    # 4b) a claim for a DIFFERENT worktree does not police this one
    ledger.claim_task(repo, "sess-pc2", "TASK-PC2", ["src/**"],
                      worktree=str(repo / ".worktrees" / "TASK-PC2"))
    r = run_hook("precommit_scope.py", {}, repo)
    check("claim for a different worktree -> allow (exit 0)",
          r.returncode == 0, r.stderr)
    ledger.release_claim(repo, "sess-pc2")

    # 5) check_commit_args: the pre-tool --no-verify/-n guard
    cca = precommit_scope.check_commit_args
    check("--no-verify denied", cca(["git", "commit", "--no-verify"]) != 0)
    check("-n denied", cca(["git", "commit", "-n", "-m", "x"]) != 0)
    check("-nm cluster denied", cca(["git", "commit", "-nm", "x"]) != 0)
    check("plain commit allowed", cca(["git", "commit", "-m", "x"]) == 0)
    check("non-commit git allowed", cca(["git", "status"]) == 0)


def session_guard_tests(td: Path) -> None:
    print("scope_guard session/worktree awareness (S8.3):")

    # --- regression lock: N=1, no session -> byte-identical to the pre-feature
    #     guard (singleton active_scope; active_tasks empty via set_active_task).
    r0 = td / "sg-single"; r0.mkdir()
    git(r0, "init", "-q"); git(r0, "config", "user.email", "t@t")
    git(r0, "config", "user.name", "t")
    (r0 / "README.md").write_text("x\n"); git(r0, "add", "-A")
    git(r0, "commit", "-qm", "init")
    (r0 / "src").mkdir(); (r0 / "lib").mkdir()
    ledger.set_active_task(r0, "TASK-S", "010", "in-progress", ["src/**"])
    r = run_hook("scope_guard.py",
                 {"tool_name": "Edit",
                  "tool_input": {"file_path": str(r0 / "src" / "a.py")},
                  "cwd": str(r0)}, r0)
    check("N=1 in-scope Edit -> allow (regression lock)", r.returncode == 0, r.stderr)
    r = run_hook("scope_guard.py",
                 {"tool_name": "Write",
                  "tool_input": {"file_path": str(r0 / "lib" / "b.py")},
                  "cwd": str(r0)}, r0)
    check("N=1 out-of-scope Write -> deny exit 2 (regression lock)",
          r.returncode == 2, r.stderr)
    # the reusable checker agrees with the guard for the singleton case.
    check("scope_violation(None) True out-of-scope",
          scope_guard.scope_violation(r0, None, "lib/b.py") is True)
    check("scope_violation(None) False in-scope",
          scope_guard.scope_violation(r0, None, "src/a.py") is False)
    check("scope_check singleton clean flag",
          scope_guard.scope_check(r0, None, ["src/a.py"])["clean"] is True)
    check("scope_check singleton names the violation",
          scope_guard.scope_check(r0, None, ["lib/b.py"])["violations"] == ["lib/b.py"])

    # --- two live claims, each in its own worktree: a write is enforced against
    #     the COMMITTING session's scope, not the other session's, not the
    #     (null) singleton. With 2 claims the singleton active_scope is None, so a
    #     DENY here can only come from session-aware resolution.
    main = td / "sg-main"; main.mkdir()
    git(main, "init", "-q"); git(main, "config", "user.email", "t@t")
    git(main, "config", "user.name", "t")
    (main / "README.md").write_text("x\n"); git(main, "add", "-A")
    git(main, "commit", "-qm", "init")
    wtA = main / ".worktrees" / "A"
    wtB = main / ".worktrees" / "B"
    git(main, "worktree", "add", "-q", "-b", "task/a", str(wtA))
    git(main, "worktree", "add", "-q", "-b", "task/b", str(wtB))
    ledger.claim_task(main, "sess-A", "TASK-A", ["a/**"],
                      branch="task/a", worktree=str(wtA))
    ledger.claim_task(main, "sess-B", "TASK-B", ["b/**"],
                      branch="task/b", worktree=str(wtB))
    check("two claims -> singleton active_scope is None",
          ledger.active_scope(main) is None)
    (wtA / "a").mkdir(); (wtA / "b").mkdir()

    # write from A's worktree, into A's scope -> allow
    r = run_hook("scope_guard.py",
                 {"tool_name": "Edit",
                  "tool_input": {"file_path": str(wtA / "a" / "x.py")},
                  "cwd": str(wtA)}, wtA)
    check("A worktree write in A's scope -> allow", r.returncode == 0, r.stderr)
    # write from A's worktree, into B's scope (b/**) -> deny (checked vs A, not B)
    r = run_hook("scope_guard.py",
                 {"tool_name": "Write",
                  "tool_input": {"file_path": str(wtA / "b" / "x.py")},
                  "cwd": str(wtA)}, wtA)
    check("A worktree write in B's scope -> deny exit 2 (session-aware)",
          r.returncode == 2, r.stderr)
    check("deny names TASK-A (not TASK-B, not singleton)",
          "TASK-A" in r.stderr and "TASK-B" not in r.stderr, r.stderr)

    # symmetric: from B's worktree, a write into A's scope is denied against B.
    (wtB / "a").mkdir()
    r = run_hook("scope_guard.py",
                 {"tool_name": "Write",
                  "tool_input": {"file_path": str(wtB / "a" / "y.py")},
                  "cwd": str(wtB)}, wtB)
    check("B worktree write in A's scope -> deny exit 2", r.returncode == 2, r.stderr)
    check("deny names TASK-B", "TASK-B" in r.stderr, r.stderr)

    # the reusable checker resolves per-session scope directly.
    check("scope_check(sess-A) flags b/** path",
          scope_guard.scope_check(main, "sess-A", ["b/x.py"])["clean"] is False)
    check("scope_check(sess-A) clean on a/** path",
          scope_guard.scope_check(main, "sess-A", ["a/x.py"])["clean"] is True)
    check("scope_violation(sess-B) True on a/** path",
          scope_guard.scope_violation(main, "sess-B", "a/y.py") is True)
    # unknown session -> fail-open (no claim resolves)
    check("scope_check(unknown session) fail-open clean",
          scope_guard.scope_check(main, "nope", ["a/x.py"])["clean"] is True)


def path_guard_tests(td: Path) -> None:
    print("scope_guard path->worktree resolution (S11.3):")

    # Two live claims, each owning a different .worktrees/<id>. The worktrees are
    # plain dirs (not real linked worktrees): a subagent shares the ORCHESTRATOR's
    # cwd (the repo root), so resolution must key off the target file's path, not
    # cwd. With 2 claims the singleton active_scope is None, so any DENY here can
    # only come from path->worktree resolution.
    main = td / "pg-main"; main.mkdir()
    git(main, "init", "-q"); git(main, "config", "user.email", "t@t")
    git(main, "config", "user.name", "t")
    (main / "README.md").write_text("x\n"); git(main, "add", "-A")
    git(main, "commit", "-qm", "init")
    wtA = main / ".worktrees" / "A"; wtA.mkdir(parents=True)
    wtB = main / ".worktrees" / "B"; wtB.mkdir(parents=True)
    ledger.claim_task(main, "sess-A", "TASK-A", ["a/**"],
                      branch="task/a", worktree=str(wtA))
    ledger.claim_task(main, "sess-B", "TASK-B", ["b/**"],
                      branch="task/b", worktree=str(wtB))
    check("(a) two claims -> singleton active_scope None",
          ledger.active_scope(main) is None)

    # (a) file under wtA, but cwd = REPO ROOT (not the worktree): resolved by PATH
    #     to A's claim and enforced against A's scope, independent of cwd.
    r = run_hook("scope_guard.py",
                 {"tool_name": "Edit",
                  "tool_input": {"file_path": str(wtA / "a" / "x.py")},
                  "cwd": str(main)}, main)
    check("(a) path under wtA, cwd=root, in A-scope -> allow (exit 0)",
          r.returncode == 0, r.stderr)
    r = run_hook("scope_guard.py",
                 {"tool_name": "Write",
                  "tool_input": {"file_path": str(wtA / "b" / "x.py")},
                  "cwd": str(main)}, main)
    check("(a) path under wtA, cwd=root, out-of-scope -> deny (exit 2)",
          r.returncode == 2, r.stderr)
    check("(a) deny names TASK-A (path-resolved, not cwd/singleton)",
          "TASK-A" in r.stderr and "TASK-B" not in r.stderr, r.stderr)
    # independence from cwd: same file, cwd = the OTHER worktree -> still A by path
    r = run_hook("scope_guard.py",
                 {"tool_name": "Write",
                  "tool_input": {"file_path": str(wtA / "b" / "x.py")},
                  "cwd": str(wtB)}, main)
    check("(a) path under wtA wins even when cwd=wtB -> deny vs TASK-A",
          r.returncode == 2 and "TASK-A" in r.stderr, r.stderr)

    # (b) path under NO registered worktree -> cwd/singleton fallback (today).
    check("(b) resolver: no worktree match -> (None, rel) fallback",
          scope_guard._resolve_by_path(main, "src/z.py") == (None, "src/z.py"))
    r = run_hook("scope_guard.py",
                 {"tool_name": "Write",
                  "tool_input": {"file_path": str(main / "src" / "z.py")},
                  "cwd": str(main)}, main)
    check("(b) path under no worktree -> singleton/none fallback allow (exit 0)",
          r.returncode == 0, r.stderr)

    # (c) nested/ambiguous worktrees -> most specific (longest-prefix) claim wins.
    nest = td / "pg-nest"; nest.mkdir()
    git(nest, "init", "-q"); git(nest, "config", "user.email", "t@t")
    git(nest, "config", "user.name", "t")
    (nest / "README.md").write_text("x\n"); git(nest, "add", "-A")
    git(nest, "commit", "-qm", "init")
    ledger.claim_task(nest, "sess-P", "TASK-P", ["outer/**"],
                      worktree=str(nest / ".worktrees" / "P"))
    ledger.claim_task(nest, "sess-Q", "TASK-Q", ["inner/**"],
                      worktree=str(nest / ".worktrees" / "P" / "nested"))
    sess, inner = scope_guard._resolve_by_path(nest, ".worktrees/P/nested/inner/y.py")
    check("(c) nested worktrees -> longest-prefix (Q) wins", sess == "sess-Q")
    check("(c) inner path re-relativized to Q's worktree", inner == "inner/y.py")
    s2, i2 = scope_guard._resolve_by_path(nest, ".worktrees/P/outer/w.py")
    check("(c) path under outer P only -> P", s2 == "sess-P" and i2 == "outer/w.py")
    check("(c) .worktrees/P-extra does NOT match .worktrees/P (segments)",
          scope_guard._resolve_by_path(nest, ".worktrees/P-extra/z.py")
          == (None, ".worktrees/P-extra/z.py"))

    # (d) N=1 with worktree=None -> byte-identical singleton behaviour: the
    #     None-worktree claim is skipped by the path resolver, decisions unchanged.
    solo = td / "pg-solo"; solo.mkdir()
    git(solo, "init", "-q"); git(solo, "config", "user.email", "t@t")
    git(solo, "config", "user.name", "t")
    (solo / "README.md").write_text("x\n"); git(solo, "add", "-A")
    git(solo, "commit", "-qm", "init")
    (solo / "src").mkdir(); (solo / "lib").mkdir()
    ledger.claim_task(solo, "s1", "TASK-SOLO", ["src/**"], worktree=None)
    check("(d) worktree=None claim skipped by path resolver -> (None, rel)",
          scope_guard._resolve_by_path(solo, "src/a.py") == (None, "src/a.py"))
    r = run_hook("scope_guard.py",
                 {"tool_name": "Edit",
                  "tool_input": {"file_path": str(solo / "src" / "a.py")},
                  "cwd": str(solo)}, solo)
    check("(d) N=1 worktree=None in-scope -> allow (exit 0)",
          r.returncode == 0, r.stderr)
    r = run_hook("scope_guard.py",
                 {"tool_name": "Write",
                  "tool_input": {"file_path": str(solo / "lib" / "b.py")},
                  "cwd": str(solo)}, solo)
    check("(d) N=1 worktree=None out-of-scope -> deny (exit 2)",
          r.returncode == 2, r.stderr)

    # (e) N=0 -> fail-open allow (no claim resolvable).
    zero = td / "pg-zero"; zero.mkdir()
    git(zero, "init", "-q"); git(zero, "config", "user.email", "t@t")
    git(zero, "config", "user.name", "t")
    (zero / "README.md").write_text("x\n"); git(zero, "add", "-A")
    git(zero, "commit", "-qm", "init")
    check("(e) resolver on empty registry -> (None, rel)",
          scope_guard._resolve_by_path(zero, "x/y.py") == (None, "x/y.py"))
    r = run_hook("scope_guard.py",
                 {"tool_name": "Write",
                  "tool_input": {"file_path": str(zero / "anything.py")},
                  "cwd": str(zero)}, zero)
    check("(e) N=0 -> fail-open allow (exit 0)", r.returncode == 0, r.stderr)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "init")

        print("ledger library:")
        check("glob ** spans dirs",
              ledger.path_in_scope("src/api/auth.ts", ["src/**"]))
        check("glob * stays in segment (neg)",
              not ledger.path_in_scope("src/api/auth.ts", ["src/*.ts"]))
        check("exact path matches",
              ledger.path_in_scope("tests/api/auth.test.ts",
                                   ["tests/api/auth.test.ts"]))
        check("always-allowed docs/",
              ledger.is_always_allowed("docs/LEDGER.md"))
        check("not-allowed src/",
              not ledger.is_always_allowed("src/x.ts"))

        check("no active task -> active_scope None",
              ledger.active_scope(repo) is None)
        ledger.set_active_task(repo, "TASK-X", "010-data", "in-progress",
                               ["src/**", "tests/**"], branch="task/x")
        check("active_scope set", ledger.active_scope(repo) == ["src/**", "tests/**"])

        check("lock acquire", ledger.acquire_lock(repo, "sess-1"))
        check("lock blocks other session",
              not ledger.acquire_lock(repo, "sess-2"))
        check("same session re-acquires", ledger.acquire_lock(repo, "sess-1"))
        ledger.release_lock(repo, "sess-1")
        check("lock released after release",
              ledger.acquire_lock(repo, "sess-2"))

        ledger.append_event(repo, "TASK-X", "transition", "todo->challenged")
        ledger.append_event(repo, "TASK-X", "bogus-kind", "should downgrade")
        log = (repo / "docs" / "LEDGER.md").read_text()
        check("event appended", "todo->challenged" in log)
        check("bad kind downgraded to finding", "| finding |" in log)

        sha = ledger.tree_sha(repo)
        check("tree_sha returns a hash", bool(sha) and len(sha or "") >= 8)

        print("scope_guard hook (active task scope = src/** , tests/**):")
        # in-scope edit -> allow (0)
        r = run_hook("scope_guard.py",
                     {"tool_name": "Edit",
                      "tool_input": {"file_path": str(repo / "src" / "a.ts")},
                      "cwd": str(repo)}, repo)
        check("in-scope Edit allowed (exit 0)", r.returncode == 0, r.stderr)
        # out-of-scope edit -> deny (2)
        r = run_hook("scope_guard.py",
                     {"tool_name": "Write",
                      "tool_input": {"file_path": str(repo / "lib" / "b.ts")},
                      "cwd": str(repo)}, repo)
        check("out-of-scope Write denied (exit 2)", r.returncode == 2, r.stderr)
        check("deny reason on stderr", "BLOCKED" in r.stderr)
        # always-allowed path -> allow even though out of scope
        r = run_hook("scope_guard.py",
                     {"tool_name": "Write",
                      "tool_input": {"file_path": str(repo / "docs" / "x.md")},
                      "cwd": str(repo)}, repo)
        check("docs/ allowed despite scope (exit 0)", r.returncode == 0, r.stderr)
        # non-write tool -> allow
        r = run_hook("scope_guard.py",
                     {"tool_name": "Read",
                      "tool_input": {"file_path": str(repo / "lib" / "b.ts")},
                      "cwd": str(repo)}, repo)
        check("non-write tool ignored (exit 0)", r.returncode == 0)
        # no active task -> fail-open
        ledger.clear_active_task(repo)
        r = run_hook("scope_guard.py",
                     {"tool_name": "Write",
                      "tool_input": {"file_path": str(repo / "lib" / "b.ts")},
                      "cwd": str(repo)}, repo)
        check("no active task -> allow (exit 0)", r.returncode == 0)
        # the denied write recorded a traceback event
        check("deny recorded a traceback event",
              "traceback" in (repo / "docs" / "LEDGER.md").read_text())

        print("ledger_commit hook:")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "wip")  # clean tree except future ledger churn
        (repo / "docs" / "LEDGER.md").open("a").write(
            "- 2026-01-01T00:00Z | TASK-X | gotcha test | - | -\n")
        r = run_hook("ledger_commit.py", {"cwd": str(repo)}, repo)
        check("commit hook exits 0", r.returncode == 0, r.stderr)
        last = git(repo, "log", "-1", "--pretty=%s").stdout.strip()
        check("checkpoint commit created", last.startswith("chore(ledger): checkpoint"),
              f"last subject={last!r}")
        # second run with nothing new -> no-op, still 0, no new commit
        before = git(repo, "rev-parse", "HEAD").stdout.strip()
        r = run_hook("ledger_commit.py", {"cwd": str(repo)}, repo)
        after = git(repo, "rev-parse", "HEAD").stdout.strip()
        check("no-op when ledger unchanged", r.returncode == 0 and before == after)

        registry_tests(Path(td))
        lock_liveness_tests(Path(td))
        scope_algebra_tests(Path(td))
        precommit_tests(Path(td))
        session_guard_tests(Path(td))
        path_guard_tests(Path(td))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
