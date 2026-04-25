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
