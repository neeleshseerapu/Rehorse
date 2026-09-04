# Changelog

All notable changes to Rehorse are recorded here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions will follow [Semantic Versioning](https://semver.org/) once released.

## [Unreleased]

### Added
- `/rehorse:build "<task>"`: rehearses a task on its own git worktree and branch, writes failing tests first, implements in committed steps, and stops with a one-screen report in `rehorse-reports/`. It never merges.
- `/rehorse:merge` and `/rehorse:discard`: the only ways work reaches your branch or is dropped. Only a command you type can authorize them.
- `/rehorse:status`: phase, plan progress, last test result and next action. Work resumes from it after an interruption, a `/compact`, or in a new session.
- Guarantees enforced by hooks in every permission mode: edits stay inside the rehearsal, test files are locked during implementation, no stopping with untested edits, no branch-changing git commands, no shell writes around the lock.
- Test command detected from your own repo (pytest, vitest, jest, `npm test`, `cargo test`, `go test`, `swift test`, `make test`), with your `.venv`, `node_modules`, `target` or `.tox` linked into the worktree. Reports flag test-file drift, new tests that already passed before implementation, and a red run that was a compile failure rather than failing tests.
- Loads from a clone with `claude --plugin-dir`. MIT licensed.
