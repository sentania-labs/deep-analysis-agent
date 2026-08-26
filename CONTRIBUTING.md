# Contributing to Deep Analysis Agent

## From v0.4.0 onward: PR discipline

Prior to v0.4.0, this repo used a rapid-build posture — direct commits to `main`
for speed during initial construction. That phase is now complete.

**All changes from v0.4.0 onward ship via pull request.**

1. Branch from `main` with a descriptive name (e.g. `fix/watcher-stability`, `feat/error-tray-state`).
2. Open a PR against `main`.
3. CI must pass before merge.
4. One-person repos: self-merge is fine; the PR is the review artifact.

**Branch protection is enabled on `main`** (as of 2026-04-25): PRs are required, and
the `lint`, `typecheck`, `test`, and `build-windows` checks must pass before merge.
Repo admins can bypass for urgent fixes (admin enforcement is off), but the
follow-up CI run on `main` must still go green.

## License

This project is MIT-licensed. Contributions are accepted under the same license.

## Pre-push review gate

`.claude/hooks/check-review-passed.sh` runs as a PreToolUse hook on every Bash
command and blocks pushes that have not been reviewed. What it checks:

- It works out which directory the push actually runs from, following `cd`,
  `git -C <path>`, `--git-dir`, and `--work-tree`, rather than assuming the
  harness working directory. Work done in a `git worktree` is therefore gated
  against that worktree's HEAD, not the primary checkout's.
- A `.review-passed` marker must exist at the root of the tree being pushed (or
  at the main worktree root) and must contain the exact commit being pushed.
  `/self-review` writes it after an approving review. Hand-writing the marker is
  a bypass, not a workflow.
- It fails closed. If the hook cannot tell which HEAD is being pushed (missing
  `jq`, unreadable hook input, an unresolvable path, a subcommand behind a
  variable, a push wrapped in `bash -c` or `ssh`, an opaque or shell-out git
  alias), it blocks.
- Aliases are followed by their effective subcommand, including one set inline
  with `-c alias.x=push`, and `git send-pack` and the dash-form `git-push`
  binary count as pushes. Builtin prefixes (`command`, `builtin`, `exec`) are
  stepped over rather than treated as opaque wrappers.
- Pipeline stages run in their own subshells, so a `cd` in one stage is not
  carried into the next.

One practical consequence of failing closed: a command that merely *contains*
something that parses as a push, for example a heredoc writing a doc or test
that includes that text at the start of a line, is also blocked. Restructure the
command (write the file with a placeholder and substitute, or use a different
tool) rather than weakening the gate.

`tests/test_review_gate_hook.py` covers the gate. Run it after touching the hook.
