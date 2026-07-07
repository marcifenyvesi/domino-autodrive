# Contributing

Thanks for your interest. This is primarily a reference implementation, but issues and
PRs are welcome.

## Ground rules

- **No third-party runtime dependencies.** The engine and hooks are standard-library
  Python 3 by design. Keep it that way — it's part of what makes the harness portable and
  auditable.
- **Tests must stay green.** Both self-test suites run in CI on every push:
  ```bash
  python3 harness/hooks/_selftest.py        # 114 assertions
  python3 harness/autodrive/_selftest.py    # 121 assertions
  ```
  New behavior needs new assertions in the matching `_selftest.py`. The suites test the
  code against real git worktrees — no mocks.
- **The enforcement guarantees are load-bearing.** Changes that weaken scope enforcement,
  the resumable-ledger contract, the challenge-convergence rule, or requirement
  traceability need an explicit rationale in the PR and a matching design note.
- **Coding standards** live in [`harness/STANDARDS.md`](harness/STANDARDS.md) — NASA-style
  discipline, no stubs/mocks/stales, security minimums. Code is expected to follow them
  (the harness enforces them on itself).

## Design changes

Substantive design changes should come with a clear rationale in the PR, and ideally
survive a `/challenge` pass.

## Commit style

Conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`).
