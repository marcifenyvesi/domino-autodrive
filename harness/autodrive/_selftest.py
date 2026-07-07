#!/usr/bin/env python3
"""Self-test for the autodrive engine. Real temp git repo, no mocks.

Proves the deterministic core: frontmatter round-trip, batch/task DAG ordering,
state transitions wiring the active-task scope, resume reconciliation
(restart/adopt/quarantine), and the no-progress detector.
"""
import fcntl
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hooks"))
import audit  # noqa: E402
import claims as claims_mod  # noqa: E402
import engine  # noqa: E402
import ledger  # noqa: E402
import lease  # noqa: E402
import merge  # noqa: E402
import parallel  # noqa: E402
import scope_algebra  # noqa: E402

PASS = FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  ok   {name}")
    else:
        FAIL += 1; print(f"  FAIL {name} {extra}")


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True)


def eng(repo, *a):
    # cwd is pinned to the temp repo too: if --repo handling ever regresses, the
    # engine's find_repo_root() fallback lands HERE, never in the real cwd. (A
    # prior --repo bug let a broken run scribble a ledger into the source repo.)
    r = subprocess.run([sys.executable, str(HERE / "engine.py"), "--repo", str(repo), *a],
                       capture_output=True, text=True, cwd=str(repo))
    try:
        return r.returncode, json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return r.returncode, {"_raw": r.stdout, "_err": r.stderr}


def write_batch(repo, name, layer, state, depends_on, tasks):
    d = repo / "docs" / "batches" / name
    (d / "tasks").mkdir(parents=True, exist_ok=True)
    dep = "[" + ", ".join(depends_on) + "]"
    tl = "[" + ", ".join(tasks) + "]"
    (d / "BATCH.md").write_text(
        f"---\nbatch: {name}\nlayer: {layer}\nstate: {state}\n"
        f"depends_on: {dep}\ntasks: {tl}\n---\n# {name}\n", encoding="utf-8")
    return d


def write_task(d, tid, state, depends_on, scope):
    dep = "[" + ", ".join(depends_on) + "]"
    sc = "\n".join(f"  - {s}" for s in scope)
    (d / "tasks" / f"{tid}.md").write_text(
        f"---\nid: {tid}\nstate: {state}\ndepends_on: {dep}\nscope:\n{sc}\n"
        f"design_refs: [SPEC-S1.1]\n---\n# {tid}\n", encoding="utf-8")


def parallel_tests():
    """SPEC §S4: claim-aware next-task + next-parallel-set. Fresh fixture repo so
    the live-claim registry is exercised without disturbing the legacy cases."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")

        # 010-data done -> 020-api (A, C dep-free & disjoint; B depends on A).
        write_batch(repo, "010-data", "data", "done", [], ["TASK-DATA"])
        d2 = write_batch(repo, "020-api", "api", "pending", ["010-data"],
                         ["TASK-A", "TASK-C", "TASK-B"])
        dd = repo / "docs" / "batches" / "010-data"
        write_task(dd, "TASK-DATA", "done", [], ["src/data.ts"])
        write_task(d2, "TASK-A", "todo", [], ["src/api/a.ts"])
        write_task(d2, "TASK-C", "todo", [], ["src/api/c.ts"])
        write_task(d2, "TASK-B", "todo", ["TASK-A"], ["src/api/b.ts"])

        print("claim-aware next-task (S4.1):")
        legacy = engine.next_task(repo)
        claim_aware = parallel.next_task_claim_aware(repo)
        check("no claims: claim-aware output byte-identical to legacy next_task",
              json.dumps(claim_aware) == json.dumps(legacy), (legacy, claim_aware))
        check("no claims: picks ready TASK-A", claim_aware.get("task") == "TASK-A", claim_aware)

        ok = ledger.claim_task(repo, "sess-other", "TASK-X", ["src/api/a.ts"])
        check("external overlapping claim registered", ok is True)
        skipped = parallel.next_task_claim_aware(repo)
        check("overlapping claim skips TASK-A, returns disjoint TASK-C",
              skipped.get("task") == "TASK-C", skipped)
        check("legacy next_task unchanged (still TASK-A)",
              engine.next_task(repo).get("task") == "TASK-A")

        print("next-parallel-set (S4.2/S4.3):")
        ids = [t["task"] for t in parallel.next_parallel_set(repo, 5)["tasks"]]
        check("parallel-set excludes claimed-overlap A + dep-blocked B (only C)",
              ids == ["TASK-C"], ids)

        ledger.release_claim(repo, "sess-other")
        pset = parallel.next_parallel_set(repo, 5)
        ids = [t["task"] for t in pset["tasks"]]
        check("no claims: mutually-disjoint A+C returned, dep-blocked B gated",
              ids == ["TASK-A", "TASK-C"], ids)
        check("parallel-set items carry the full shape",
              all(set(t) >= {"task", "batch", "scope", "design_refs", "file"}
                  for t in pset["tasks"]))
        check("returned set is mutually scope-disjoint (S4.2/R-2)",
              scope_algebra.scopes_overlap(
                  repo, pset["tasks"][0]["scope"], pset["tasks"][1]["scope"]) is False)
        check("parallel-set caps at K", len(parallel.next_parallel_set(repo, 1)["tasks"]) == 1)

        # --- F-B fix: parallel walk fans PAST a temporarily-blocked batch to reach
        #     later INDEPENDENT ready work; serial next_task deliberately stops there ---
        with tempfile.TemporaryDirectory() as td2:
            r2 = Path(td2) / "proj"; r2.mkdir()
            git(r2, "init", "-q"); git(r2, "config", "user.email", "t@t")
            git(r2, "config", "user.name", "t")
            (r2 / "README.md").write_text("x\n")
            git(r2, "add", "-A"); git(r2, "commit", "-qm", "init")
            # 020-blocked (deps=[]) has one todo task blocked on a not-done task in
            # the LATER 030-indep batch -> zero ready tasks in 020-blocked.
            b_blk = write_batch(r2, "020-blocked", "blk", "pending", [], ["TASK-BLK"])
            b_ind = write_batch(r2, "030-indep", "ind", "pending", [],
                                ["TASK-IND1", "TASK-IND2"])
            write_task(b_blk, "TASK-BLK", "todo", ["TASK-IND1"], ["src/blk.ts"])
            write_task(b_ind, "TASK-IND1", "todo", [], ["src/ind1.ts"])
            write_task(b_ind, "TASK-IND2", "todo", [], ["src/ind2.ts"])
            fan = [t["task"] for t in parallel.next_parallel_set(r2, 5)["tasks"]]
            check("F-B: parallel-set fans PAST blocked 020-blocked to independent "
                  "030-indep tasks", fan == ["TASK-IND1", "TASK-IND2"], fan)
            check("F-B: serial next_task still stops at the blocked batch (None)",
                  engine.next_task(r2) is None, engine.next_task(r2))


def claim_release_tests():
    """Corrective fix: `claim`/`release` CLI verbs as thin atomic wrappers over
    ledger.claim_task/release_claim (ARCH §10, PRD-R1). Fresh fixture repo."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        d = write_batch(repo, "040-claim", "claim", "pending", [],
                        ["TASK-A", "TASK-C", "TASK-D"])
        write_task(d, "TASK-A", "todo", [], ["src/api/a.ts"])
        write_task(d, "TASK-C", "todo", [], ["src/api/c.ts"])
        write_task(d, "TASK-D", "todo", [], ["src/api/a.ts"])  # scope overlaps A

        print("cmd_claim on a free task (PRD-R1):")
        rc, out = eng(repo, "claim", "--task", "TASK-A", "--session", "s1")
        check("claim succeeds, exit 0", rc == 0 and out.get("claimed") is True, (rc, out))
        check("task appears in active_tasks registry",
              ledger.load_state(repo)["active_tasks"].get("s1", {}).get("id") == "TASK-A")
        check("claimed task frontmatter -> in-progress",
              engine.load_task(repo, d, "TASK-A")["state"] == "in-progress")
        check("claim carries branch+worktree defaults",
              out.get("branch") == "task/TASK-A"
              and out.get("worktree") == ".worktrees/TASK-A", out)

        print("same task, different session loses the race (atomic, PRD-R1):")
        rc2, out2 = eng(repo, "claim", "--task", "TASK-A", "--session", "s2")
        check("duplicate claim refused, non-zero exit",
              rc2 != 0 and out2.get("claimed") is False, (rc2, out2))
        check("s2 not added to registry",
              "s2" not in ledger.load_state(repo)["active_tasks"])

        print("scope-overlapping claim refused (S2/R-2):")
        rc3, out3 = eng(repo, "claim", "--task", "TASK-D", "--session", "s3")
        check("overlapping-scope claim refused, non-zero exit",
              rc3 != 0 and out3.get("claimed") is False, (rc3, out3))
        check("s3 not added to registry",
              "s3" not in ledger.load_state(repo)["active_tasks"])

        print("cmd_release removes the entry (S2.4):")
        rc4, out4 = eng(repo, "release", "--session", "s1")
        check("release reports released:true, exit 0",
              rc4 == 0 and out4.get("released") is True, (rc4, out4))
        check("registry entry gone after release",
              "s1" not in ledger.load_state(repo)["active_tasks"])
        # freed scope is now claimable by the previously-blocked D
        rc5, out5 = eng(repo, "claim", "--task", "TASK-D", "--session", "s3")
        check("freed scope now claimable", rc5 == 0 and out5.get("claimed") is True, (rc5, out5))
        ledger.release_claim(repo, "s3")


def claims_tests():
    """SPEC §S9 / UI §U1: `claims` (alias `status`) observability command."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")

        print("claims empty registry (S9.1):")
        empty = claims_mod.claims(repo)
        check("empty registry -> claims == []", empty.get("claims") == [], empty)
        check("empty registry still carries frontier", "frontier" in empty, empty)
        rc, out = eng(repo, "status")
        check("status alias: valid JSON, exit 0 on empty registry",
              rc == 0 and out.get("claims") == [], (rc, out))
        rc, out = eng(repo, "claims")
        check("claims: valid JSON, exit 0 on empty registry",
              rc == 0 and out.get("claims") == [], (rc, out))

        print("claims with 2 live claims (S9.1/PRD-R10):")
        ledger.claim_task(repo, "sess-a", "TASK-A", ["src/a.ts"],
                          branch="task/a", worktree=".worktrees/TASK-A")
        ledger.claim_task(repo, "sess-b", "TASK-B", ["src/b.ts"],
                          branch="task/b", worktree=".worktrees/TASK-B")
        data = claims_mod.claims(repo)
        rows = {r["session"]: r for r in data["claims"]}
        check("both live claims listed", set(rows) == {"sess-a", "sess-b"}, list(rows))
        fields = {"session", "task", "batch", "scope", "branch",
                  "worktree", "lease_expiry", "heartbeat", "age"}
        check("each claim carries all S9.1 fields incl. derived age",
              all(fields <= set(r) for r in data["claims"]), data["claims"])
        check("task/branch/worktree round-trip",
              rows["sess-a"]["task"] == "TASK-A"
              and rows["sess-a"]["branch"] == "task/a"
              and rows["sess-a"]["worktree"] == ".worktrees/TASK-A", rows["sess-a"])
        check("age is derived (not persisted in registry)",
              isinstance(rows["sess-a"]["age"], str)
              and "age" not in (ledger.load_state(repo)["active_tasks"]["sess-a"]),
              rows["sess-a"].get("age"))

        print("status is a pure alias of claims (S9.2):")
        rc_s, out_s = eng(repo, "status")
        rc_c, out_c = eng(repo, "claims")
        check("status and claims produce identical JSON",
              rc_s == 0 and rc_c == 0 and json.dumps(out_s) == json.dumps(out_c),
              (out_s, out_c))
        check("both list the 2 live claims",
              len(out_c.get("claims", [])) == 2, out_c)


def worktree_tests():
    """SPEC §S5: worktree add/provision/remove on a throwaway real git repo."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / ".gitignore").write_text(".worktrees/\n")  # seeded by init.py normally
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")

        print("worktree add (S5.1):")
        res = parallel.worktree_add(repo, "TASK-A")
        wt = repo / ".worktrees" / "TASK-A"
        check("worktree dir created", wt.is_dir() and res.get("created") is True, res)
        check("on branch task/TASK-A", res.get("branch") == "task/TASK-A")
        check(".git inside worktree is a FILE not dir (S5.4)",
              (wt / ".git").is_file())
        check("git rev-parse --git-dir resolves inside worktree (S5.4)",
              parallel.git_dir(wt) is not None, parallel.git_dir(wt))

        print("worktree add resume (S5.1):")
        again = parallel.worktree_add(repo, "TASK-A")
        check("existing worktree reused, not re-created",
              again.get("reused") is True and again.get("created") is False, again)

        print("worktree remove + prune (S5.3):")
        rm = parallel.worktree_remove(repo, "TASK-A")
        check("worktree removed", rm.get("removed") is True and not wt.exists(), rm)
        pr = git(repo, "worktree", "list", "--porcelain").stdout
        check("pruned from git worktree list", "TASK-A" not in pr, pr)

    print("submodule refusal (S5.4):")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        (repo / ".gitmodules").write_text("[submodule \"x\"]\n  path = x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        res = parallel.worktree_add(repo, "TASK-Z")
        check("submodules present -> worktree_add REFUSES",
              "error" in res and not (repo / ".worktrees" / "TASK-Z").exists(), res)

    print("provisioning link/copy + parallel.max (S5.2/S5.4):")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        (repo / ".harness.yaml").write_text(
            "parallel:\n  max: 3\n"
            "worktree:\n  link:\n    - node_modules\n  copy:\n    - .env\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        (repo / "node_modules").mkdir()
        (repo / "node_modules" / "dep.js").write_text("//dep\n")
        (repo / ".env").write_text("SECRET=fake\n")  # fake fixture value, not a real secret
        check("parallel.max read from .harness.yaml", parallel.max_parallel(repo) == 3)
        res = parallel.worktree_add(repo, "TASK-P")
        wt = repo / ".worktrees" / "TASK-P"
        check("link: entry symlinked into worktree",
              (wt / "node_modules").is_symlink(), res)
        check("copy: entry copied into worktree",
              (wt / ".env").is_file() and not (wt / ".env").is_symlink())
        parallel.worktree_remove(repo, "TASK-P", force=True)

    print("stale-base guard on branch reuse (worktree_add):")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / ".gitignore").write_text(".worktrees/\n")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        # Advance the base: commit A (an earlier point), then commit B (the tip).
        (repo / "a.txt").write_text("a\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "A")
        sha_a = git(repo, "rev-parse", "HEAD").stdout.strip()
        (repo / "b.txt").write_text("b\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "B")
        sha_b = git(repo, "rev-parse", "HEAD").stdout.strip()

        # (1) Reuse a CLEAN stale branch (pinned to A, behind base B) -> reset to B.
        git(repo, "branch", "task/T", sha_a)
        res = parallel.worktree_add(repo, "T")
        head_t = git(repo, "-C", str(repo / ".worktrees" / "T"),
                     "rev-parse", "HEAD").stdout.strip()
        check("stale clean branch reset to integration base B",
              head_t == sha_b and res.get("reset_to_base") is True, (res, head_t, sha_b))
        check("guard reports base sha + reused + not dirty",
              res.get("base") == sha_b and res.get("reused") is True
              and res.get("stale_base_dirty") is False, res)
        parallel.worktree_remove(repo, "T", force=True)

        # (2) Reuse a branch carrying a UNIQUE commit ahead of base -> reuse as-is.
        git(repo, "branch", "task/T2", sha_b)
        git(repo, "worktree", "add", "-q", str(repo / ".worktrees" / "T2"), "task/T2")
        (repo / ".worktrees" / "T2" / "wip.txt").write_text("real work\n")
        git(repo / ".worktrees" / "T2", "add", "-A")
        git(repo / ".worktrees" / "T2", "commit", "-qm", "in-progress work")
        sha_uniq = git(repo, "rev-parse", "task/T2").stdout.strip()
        res2 = parallel.worktree_add(repo, "T2")
        head_t2 = git(repo, "-C", str(repo / ".worktrees" / "T2"),
                      "rev-parse", "HEAD").stdout.strip()
        check("branch with unique work reused, NOT reset",
              head_t2 == sha_uniq and res2.get("reset_to_base") is False
              and res2.get("reused") is True, (res2, head_t2, sha_uniq))
        parallel.worktree_remove(repo, "T2", force=True)

        # (3) A DIRTY stale worktree (pinned to A) is flagged, NOT reset.
        git(repo, "branch", "task/T3", sha_a)
        git(repo, "worktree", "add", "-q", str(repo / ".worktrees" / "T3"), "task/T3")
        (repo / ".worktrees" / "T3" / "uncommitted.txt").write_text("wip\n")
        res3 = parallel.worktree_add(repo, "T3")
        head_t3 = git(repo, "-C", str(repo / ".worktrees" / "T3"),
                      "rev-parse", "HEAD").stdout.strip()
        check("dirty stale worktree NOT reset, work preserved",
              head_t3 == sha_a and res3.get("reset_to_base") is False
              and (repo / ".worktrees" / "T3" / "uncommitted.txt").exists(), res3)
        check("dirty stale worktree surfaces stale_base_dirty flag",
              res3.get("stale_base_dirty") is True, res3)
        parallel.worktree_remove(repo, "T3", force=True)


def _expire(repo, session, pid=None):
    """Force a session's claim past its lease (and optionally set a dead pid)."""
    st = ledger.load_state(repo)
    e = st["active_tasks"][session]
    e["lease_expiry"] = "2000-01-01T00:00Z"
    e["heartbeat"] = "2000-01-01T00:00Z"
    if pid is not None:
        e["pid"] = pid
    ledger.save_state(repo, st)


def lease_tests():
    """SPEC §S6: heartbeat, layered death detection, reaper isolation + reclaim."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / ".gitignore").write_text(".worktrees/\n")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        d = write_batch(repo, "030-reap", "reap", "pending", [],
                        ["TASK-R", "TASK-Q", "TASK-L"])
        for tid in ("TASK-R", "TASK-Q", "TASK-L"):
            write_task(d, tid, "in-progress", [], [f"src/{tid}.ts"])

        print("heartbeat extends lease (S6.1):")
        ledger.claim_task(repo, "sess-hb", "TASK-R", ["src/TASK-R.ts"])
        _expire(repo, "sess-hb")  # drive lease into the past first
        old = ledger.load_state(repo)["active_tasks"]["sess-hb"]["lease_expiry"]
        res = lease.heartbeat(repo, "sess-hb")
        new = ledger.load_state(repo)["active_tasks"]["sess-hb"]["lease_expiry"]
        check("heartbeat refreshed", res.get("refreshed") is True, res)
        check("lease_expiry extended past the stale value", new > old, (old, new))
        check("heartbeat on unknown session -> refreshed False",
              lease.heartbeat(repo, "nobody").get("refreshed") is False)
        ledger.release_claim(repo, "sess-hb")

        print("flock death detection (S6.4a):")
        cf = ledger._claim_path(repo, "TASK-F")
        cf.write_text(f"{os.getpid()}\n", encoding="utf-8")
        check("unheld claim file is reclaimable", lease._flock_free(cf) is True)
        fd = os.open(str(cf), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        check("held claim file is NOT reclaimable", lease._flock_free(cf) is False)
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd); cf.unlink()

        print("reap reclaims expired+dead -> todo, claim removed (S6.2/A4):")
        parallel.worktree_add(repo, "TASK-R")
        ledger.claim_task(repo, "sess-dead", "TASK-R", ["src/TASK-R.ts"],
                          branch="task/TASK-R", worktree=".worktrees/TASK-R")
        _expire(repo, "sess-dead", pid=2147480000)  # expired lease + dead pid
        out = lease.reap(repo)
        check("reap acted on the expired claim",
              [r["task"] for r in out["reaped"]] == ["TASK-R"], out)
        check("clean worktree -> task reset to todo",
              engine.load_task(repo, d, "TASK-R")["state"] == "todo")
        check("claim entry removed",
              "sess-dead" not in (ledger.load_state(repo)["active_tasks"] or {}))
        check("claim file removed", not ledger._claim_path(repo, "TASK-R").exists())
        check("worktree pruned",
              not (repo / ".worktrees" / "TASK-R").exists()
              and "TASK-R" not in git(repo, "worktree", "list", "--porcelain").stdout)

        print("reap quarantines a dirty worktree (S6.2/A7):")
        parallel.worktree_add(repo, "TASK-Q")
        (repo / ".worktrees" / "TASK-Q" / "wip.txt").write_text("uncommitted\n")
        ledger.claim_task(repo, "sess-q", "TASK-Q", ["src/TASK-Q.ts"],
                          branch="task/TASK-Q", worktree=".worktrees/TASK-Q")
        _expire(repo, "sess-q")
        lease.reap(repo)
        check("dirty worktree -> task needs-human",
              engine.load_task(repo, d, "TASK-Q")["state"] == "needs-human")
        branches = git(repo, "branch", "--list", "quarantine/TASK-Q-*").stdout
        check("branch moved to quarantine/<id>-<sha>", "quarantine/TASK-Q-" in branches, branches)
        check("dirty claim entry removed",
              "sess-q" not in (ledger.load_state(repo)["active_tasks"] or {}))

        print("reap isolation: live claim untouched (S6.3/A5):")
        ledger.claim_task(repo, "sess-live", "TASK-L", ["src/TASK-L.ts"])
        out = lease.reap(repo)
        check("live claim not reaped", out["reaped"] == [] and out["skipped_live"] >= 1, out)
        check("live claim still registered",
              "sess-live" in ledger.load_state(repo)["active_tasks"])
        check("live task state unchanged (in-progress)",
              engine.load_task(repo, d, "TASK-L")["state"] == "in-progress")


def _expire_lease_only(repo, session):
    """Push a session's lease into the past while leaving the heartbeat fresh — so
    reap must fall through to the flock/backstop, not short-circuit on staleness."""
    st = ledger.load_state(repo)
    st["active_tasks"][session]["lease_expiry"] = "2000-01-01T00:00Z"
    ledger.save_state(repo, st)


def _wait_lock_taken(repo, task, timeout=5.0):
    """Wait until the holder subprocess has grabbed the claim flock (flock not free)."""
    cf = ledger._claim_path(repo, task)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not lease._flock_free(cf):
            return True
        time.sleep(0.05)
    return False


def _wait_exit(proc, timeout=5.0):
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def holder_tests():
    """SPEC §S6.5: the long-lived `hold-claim` holder makes the flock primary real.
    Spawns the holder as a REAL subprocess against a tempdir fixture + claim."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / ".gitignore").write_text(".worktrees/\n")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        d = write_batch(repo, "050-hold", "hold", "pending", [], ["TASK-H"])
        write_task(d, "TASK-H", "in-progress", [], ["src/TASK-H.ts"])
        ledger.claim_task(repo, "sess-h", "TASK-H", ["src/TASK-H.ts"],
                          branch="task/TASK-H", worktree=".worktrees/TASK-H")

        def spawn():
            return subprocess.Popen(
                [sys.executable, str(HERE / "engine.py"), "--repo", str(repo),
                 "hold-claim", "--session", "sess-h", "--task", "TASK-H",
                 "--watch-pid", str(os.getpid())],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        print("holder alive -> reap skips the live claim (S6.5/A4-live):")
        proc = spawn()
        try:
            check("holder acquired the claim flock", _wait_lock_taken(repo, "TASK-H"))
            _expire_lease_only(repo, "sess-h")  # lease past, heartbeat fresh; holder alive
            out = lease.reap(repo)
            check("live holder -> claim NOT reaped (flock held)",
                  [r["task"] for r in out["reaped"]] == [], out)
            check("claim entry still registered under the holder",
                  "sess-h" in (ledger.load_state(repo)["active_tasks"] or {}))
        finally:
            proc.terminate(); _wait_exit(proc)

        print("holder crash -> reap reclaims immediately, no lease wait (S6.5/A4-crash):")
        ledger.claim_task(repo, "sess-h", "TASK-H", ["src/TASK-H.ts"],
                          branch="task/TASK-H", worktree=".worktrees/TASK-H")
        engine.set_task_state(repo, "TASK-H", "in-progress")
        proc = spawn()
        try:
            check("holder re-acquired the flock", _wait_lock_taken(repo, "TASK-H"))
            proc.kill()  # SIGKILL: simulate a crash (no clean shutdown)
            check("crashed holder exited", _wait_exit(proc))
        finally:
            _wait_exit(proc)
        _expire_lease_only(repo, "sess-h")  # heartbeat still fresh; only the freed flock drives reclaim
        out = lease.reap(repo)
        check("crashed holder -> reap reclaims immediately",
              [r["task"] for r in out["reaped"]] == ["TASK-H"], out)
        check("claim entry removed after crash-reclaim",
              "sess-h" not in (ledger.load_state(repo)["active_tasks"] or {}))

        print("SIGTERM -> holder exits 0 and releases the flock (S6.5/A3):")
        engine.set_task_state(repo, "TASK-H", "todo")
        ledger.claim_task(repo, "sess-h", "TASK-H", ["src/TASK-H.ts"],
                          branch="task/TASK-H", worktree=".worktrees/TASK-H")
        engine.set_task_state(repo, "TASK-H", "in-progress")
        proc = spawn()
        try:
            check("holder holds flock before SIGTERM", _wait_lock_taken(repo, "TASK-H"))
            proc.send_signal(signal.SIGTERM)
            check("holder exited after SIGTERM", _wait_exit(proc))
            check("clean shutdown exit code 0", proc.returncode == 0, proc.returncode)
        finally:
            _wait_exit(proc)
        _expire_lease_only(repo, "sess-h")  # heartbeat fresh; freed flock drives reclaim
        out = lease.reap(repo)
        check("released flock -> reap reclaims after clean shutdown",
              [r["task"] for r in out["reaped"]] == ["TASK-H"], out)

        print("no holder -> reap degrades to heartbeat/lease backstop (S6.5/A5):")
        engine.set_task_state(repo, "TASK-H", "todo")
        ledger.claim_task(repo, "sess-h", "TASK-H", ["src/TASK-H.ts"],
                          branch="task/TASK-H", worktree=".worktrees/TASK-H")
        engine.set_task_state(repo, "TASK-H", "in-progress")
        _expire(repo, "sess-h", pid=2147480000)  # expired lease + dead pid, no holder
        out = lease.reap(repo)
        check("no-holder expired+dead claim still reaped (no regression)",
              [r["task"] for r in out["reaped"]] == ["TASK-H"], out)


def _mk_branch(repo, base, branch, path, content, msg):
    """Cut `branch` from `base`, write `path`, commit, return to `base`."""
    git(repo, "checkout", "-q", "-b", branch, base)
    (repo / path).write_text(content)
    git(repo, "add", "-A"); git(repo, "commit", "-qm", msg)
    git(repo, "checkout", "-q", base)


def merge_tests():
    """SPEC §S7: sequential, verify-gated merge phase on a throwaway git repo."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "a.txt").write_text("A0\n")
        (repo / "b.txt").write_text("B0\n")
        (repo / "shared.txt").write_text("orig\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        base = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()

        # A task doc-tree so merge_ready can read task states.
        d = write_batch(repo, "090-merge", "merge", "pending", [],
                        ["TASK-A", "TASK-B", "TASK-N"])
        write_task(d, "TASK-A", "done", [], ["a.txt"])
        write_task(d, "TASK-B", "done", [], ["b.txt"])
        write_task(d, "TASK-N", "todo", [], ["c.txt"])  # not done -> not ready
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "batch")

        # two done branches editing DIFFERENT files (disjoint) + one not-done.
        _mk_branch(repo, base, "task/TASK-A", "a.txt", "A1\n", "A edits a")
        _mk_branch(repo, base, "task/TASK-B", "b.txt", "B1\n", "B edits b")
        _mk_branch(repo, base, "task/TASK-N", "c.txt", "C1\n", "N edits c")

        print("merge-ready (S7.1):")
        ready = merge.merge_ready(repo, base)["branches"]
        check("lists only done+unmerged branches (A, B; not todo N)",
              ready == ["task/TASK-A", "task/TASK-B"], ready)

        print("disjoint sequence merges clean, verify gates each (S7.2/S7.3):")
        out = merge.merge_sequence(repo, verify_cmd="true", base=base)
        check("sequence did not stop", out["stopped"] is False, out)
        check("both branches merged",
              [r["status"] for r in out["results"]] == ["merged", "merged"], out)
        check("TASK-A now ancestor of integration (merged)",
              merge._is_merged(repo, "task/TASK-A", base))
        check("TASK-B now ancestor of integration (merged)",
              merge._is_merged(repo, "task/TASK-B", base))
        check("nothing left ready after a clean sweep",
              merge.merge_ready(repo, base)["branches"] == [])
        check("lockfile regen hook reported once post-merge",
              out.get("lockfile_regen", {}).get("ran") is False, out.get("lockfile_regen"))

    print("conflicting hunks: stop, escalate, keep merged intact (S7.2/A4):")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "shared.txt").write_text("orig\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        base = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        d = write_batch(repo, "091-conflict", "merge", "pending", [], ["TASK-X", "TASK-Y"])
        write_task(d, "TASK-X", "done", [], ["shared.txt"])
        write_task(d, "TASK-Y", "done", [], ["shared.txt"])
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "batch")
        _mk_branch(repo, base, "task/TASK-X", "shared.txt", "X-change\n", "X")
        _mk_branch(repo, base, "task/TASK-Y", "shared.txt", "Y-change\n", "Y")

        out = merge.merge_sequence(repo, verify_cmd="true", base=base)
        check("sequence stopped on the conflict", out["stopped"] is True, out)
        check("first merged, second conflicted",
              [r["status"] for r in out["results"]] == ["merged", "conflict"], out)
        check("already-merged TASK-X left intact",
              merge._is_merged(repo, "task/TASK-X", base))
        check("conflicting TASK-Y NOT merged",
              not merge._is_merged(repo, "task/TASK-Y", base))
        check("merge fully aborted: no unmerged index entries, no markers",
              not git(repo, "ls-files", "-u").stdout.strip()
              and "<<<<<<" not in (repo / "shared.txt").read_text(),
              git(repo, "ls-files", "-u").stdout)
        check("needs-human emitted for the offender",
              "needs-human" in (repo / "docs" / "LEDGER.md").read_text())

    print("clean merge, RED verify -> roll back offending merge (S7.4/A4/A5):")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "a.txt").write_text("A0\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        base = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        d = write_batch(repo, "092-red", "merge", "pending", [], ["TASK-R"])
        write_task(d, "TASK-R", "done", [], ["a.txt"])
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "batch")
        pre = git(repo, "rev-parse", "HEAD").stdout.strip()
        _mk_branch(repo, base, "task/TASK-R", "a.txt", "A1\n", "R edits a")

        out = merge.merge_sequence(repo, verify_cmd="false", base=base)
        check("verify-failed status recorded (clean text, red build)",
              out["results"][0]["status"] == "verify-failed", out)
        check("sequence stopped", out["stopped"] is True)
        check("offending merge rolled back to last good commit",
              git(repo, "rev-parse", "HEAD").stdout.strip() == pre)
        check("TASK-R NOT merged after red verify",
              not merge._is_merged(repo, "task/TASK-R", base))
        check("needs-human emitted for the red verify",
              "needs-human" in (repo / "docs" / "LEDGER.md").read_text())

    print("shared generated/index files flagged (S7.4):")
    hits = merge.shared_generated_hits(
        ["src/app.py", "uv.lock", "pkg/__init__.py", "frontend/package-lock.json",
         "README.md", ".prettierrc.json"])
    check("lockfiles/barrel/formatter-config flagged, plain source not",
          hits == ["uv.lock", "pkg/__init__.py", "frontend/package-lock.json",
                   ".prettierrc.json"], hits)


def scope_audit_tests():
    """SPEC §S8.4 / PRD-R13: the bypass-proof post-turn re-diff audit. Real temp
    git repo + a real task worktree; changes re-derived from git, not a hook."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / ".gitignore").write_text(".worktrees/\n")
        (repo / "src.txt").write_text("x\n")  # so src/ exists for scope globbing
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")

        print("scope-audit unknown session (S8.2 fail-open):")
        out = audit.scope_audit(repo, "ghost")
        check("no claim -> clean:true, no violations",
              out == {"clean": True, "violations": []}, out)
        rc, j = eng(repo, "scope-audit", "--session", "ghost")
        check("CLI unknown session -> clean, exit 0", rc == 0 and j.get("clean") is True, (rc, j))

        # A real worktree on branch task/TASK-A, claimed with scope src/**.
        parallel.worktree_add(repo, "TASK-A")
        wt = repo / ".worktrees" / "TASK-A"
        ledger.claim_task(repo, "sess-a", "TASK-A", ["src/**"],
                          branch="task/TASK-A", worktree=".worktrees/TASK-A")

        print("in-scope-only worktree (S8.4 -> clean):")
        (wt / "src").mkdir()
        (wt / "src" / "feature.py").write_text("# in scope\n")
        git(wt, "add", "-A"); git(wt, "commit", "-qm", "in-scope work")
        out = audit.scope_audit(repo, "sess-a")
        check("in-scope commit -> clean:true", out == {"clean": True, "violations": []}, out)
        rc, j = eng(repo, "scope-audit", "--session", "sess-a")
        check("CLI in-scope -> exit 0", rc == 0 and j.get("clean") is True, (rc, j))

        print("out-of-scope file (S8.4/A2 -> reject):")
        (wt / "sneaky.py").write_text("# outside src/\n")  # untracked, out of scope
        out = audit.scope_audit(repo, "sess-a")
        check("out-of-scope path -> clean:false naming it",
              out["clean"] is False and "sneaky.py" in out["violations"], out)
        rc, j = eng(repo, "scope-audit", "--session", "sess-a")
        check("CLI out-of-scope -> non-zero exit (A2)", rc != 0 and j.get("clean") is False, (rc, j))
        (wt / "sneaky.py").unlink()

        print("sensitive path is a violation even in scope (S8.4):")
        (wt / "src" / ".env").write_text("SECRET=fake\n")  # fake fixture, in src/ scope
        git(wt, "add", "-f", "src/.env")  # -f: a global gitignore may exclude .env
        git(wt, "commit", "-qm", "secret slipped in")
        out = audit.scope_audit(repo, "sess-a")
        check("in-scope .env still flagged (deny-list wins)",
              out["clean"] is False and "src/.env" in out["violations"], out)


def main():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "proj"; repo.mkdir()
        git(repo, "init", "-q"); git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        (repo / "README.md").write_text("x\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")

        # two batches: 010-data (done) -> 020-api (pending). In 020, task B
        # depends on task A.
        write_batch(repo, "010-data", "data", "done", [], ["TASK-DATA"])
        d2 = write_batch(repo, "020-api", "api", "pending", ["010-data"],
                         ["TASK-A", "TASK-B"])
        # TASK-DATA already done
        dd = repo / "docs" / "batches" / "010-data"
        write_task(dd, "TASK-DATA", "done", [], ["src/data.ts"])
        write_task(d2, "TASK-A", "todo", [], ["src/api/a.ts", "tests/a.test.ts"])
        write_task(d2, "TASK-B", "todo", ["TASK-A"], ["src/api/b.ts"])

        print("frontmatter:")
        t = engine.load_task(repo, d2, "TASK-A")
        check("scope parsed as list",
              t["scope"] == ["src/api/a.ts", "tests/a.test.ts"], t.get("scope"))
        check("depends_on parsed", engine.load_task(repo, d2, "TASK-B")["depends_on"] == ["TASK-A"])

        print("next-task DAG ordering:")
        rc, nt = eng(repo, "next-task")
        check("picks ready TASK-A (dep-free)", nt.get("task") == "TASK-A", nt)
        check("returns its scope", nt.get("scope") == ["src/api/a.ts", "tests/a.test.ts"])
        # B must NOT be pickable while A is todo
        check("does not pick dep-blocked TASK-B", nt.get("task") != "TASK-B")

        print("state transitions + active scope:")
        eng(repo, "set-state", "--task", "TASK-A", "--to", "challenged")
        eng(repo, "set-state", "--task", "TASK-A", "--to", "in-progress",
            "--branch", "task/a", "--expect-sha", "deadbee")
        check("active scope set for guard",
              ledger.active_scope(repo) == ["src/api/a.ts", "tests/a.test.ts"])
        st = ledger.load_state(repo)
        check("active_task branch recorded", st["active_task"]["branch"] == "task/a")
        check("expect_sha recorded", st["active_task"]["expect_sha"] == "deadbee")
        log = (repo / "docs" / "LEDGER.md").read_text()
        check("transition logged", "->in-progress" in log)

        print("resume reconciliation:")
        # clean tree currently (we committed) but expect_sha is 'deadbee' (bogus)
        # -> tree is clean -> restart
        rc, dec = eng(repo, "resume-check")
        check("clean tree -> restart", dec.get("action") == "restart", dec)
        # make tree dirty and set expect_sha to the real tree sha -> adopt
        (repo / "src").mkdir(exist_ok=True)
        (repo / "src" / "a.ts").write_text("// wip\n")
        real = ledger.tree_sha(repo)
        s2 = ledger.load_state(repo); s2["active_task"]["expect_sha"] = real
        ledger.save_state(repo, s2)
        rc, dec = eng(repo, "resume-check")
        check("dirty tree matching expect_sha -> adopt", dec.get("action") == "adopt", dec)
        # mismatch -> quarantine
        s3 = ledger.load_state(repo); s3["active_task"]["expect_sha"] = "0000000"
        ledger.save_state(repo, s3)
        rc, dec = eng(repo, "resume-check")
        check("dirty tree mismatch -> quarantine", dec.get("action") == "quarantine", dec)

        print("no-progress detector:")
        for _ in range(3):
            eng(repo, "record-failure", "--task", "TASK-A", "--signature", "test_login:abc")
        rc, prog = eng(repo, "check-progress", "--task", "TASK-A")
        check("escalates after repeat cap", prog.get("escalate") is True, prog)
        check("needs-human logged",
              "needs-human" in (repo / "docs" / "LEDGER.md").read_text())

        print("done-state clears active task:")
        eng(repo, "set-state", "--task", "TASK-A", "--to", "done")
        check("active_task cleared on done", ledger.load_state(repo)["active_task"] is None)
        rc, nt = eng(repo, "next-task")
        check("now TASK-B becomes ready", nt.get("task") == "TASK-B", nt)

        print("lock:")
        rc, r = eng(repo, "lock", "--session", "s1")
        check("lock acquired", r.get("acquired") is True)
        rc2, r2 = eng(repo, "lock", "--session", "s2")
        check("second session blocked (rc=1)", rc2 == 1 and r2.get("acquired") is False)

    parallel_tests()
    claim_release_tests()
    claims_tests()
    worktree_tests()
    lease_tests()
    holder_tests()
    merge_tests()
    scope_audit_tests()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
