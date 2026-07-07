# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities **privately** via GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
(the repository's **Security → Report a vulnerability** tab). Please do not open a
public issue for a security report. This is a small project maintained on a
best-effort basis; there is no formal SLA, but reports are appreciated and will
be acknowledged.

## Threat model — a guardrail against drift, not an adversarial sandbox

This is important to understand before relying on the enforcement guarantees.

The scope enforcement (the `PreToolUse` guard, the pre-commit guard, and the
post-run scope audit) is designed to keep a **cooperative** AI agent inside its
task's declared `scope[]` and to catch **accidental** drift — the common, real
failure mode when an autonomous agent wanders. It is **not** a containment
boundary against an agent that is actively trying to subvert the harness itself.

Concretely, the following are **trusted** and are *not* confined by the scope
guard:

- **Always-allowed paths** — a small set of bookkeeping locations (`docs/`,
  `reviews/`, `.claude/`, `STANDARDS.md`, `.harness.yaml`) is exempt from scope
  checks so the loop can maintain its own ledger, docs, and config. An agent that
  writes to these paths is not blocked — including the harness's own state
  (`docs/LEDGER.state.json`) and hook scripts under `.claude/`.
- **`.harness.yaml` command hooks** — values such as `merge.verify`,
  `worktree.ready`, and `merge.lockfile_regen` name commands the engine executes
  on the local machine. Treat `.harness.yaml` as trusted input.
- **git** — `git commit --no-verify` and `git -c core.hooksPath=…` can skip the
  pre-commit guard; the post-run audit is the backstop, but it too reads trusted
  state.

**If you are running agents you do not fully trust, run the entire harness under
an OS-level sandbox** (container, VM, or a restricted user) rooted at the target
repository. The tool-layer hooks are fast in-the-loop feedback; the operating
system is the real boundary.

## What is enforced well

For a well-intentioned agent, the harness reliably prevents out-of-scope edits at
the tool layer, blocks obvious secret-bearing files (`.env`, `*.pem`, `*.key`,
credential-like names) from commits, and re-checks the actual diff after each turn.
The Python is standard-library only (no third-party runtime dependencies), uses
argument-array subprocess calls throughout (no shell string injection), and
canonicalizes paths before every scope decision.
