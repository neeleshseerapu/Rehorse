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
- The tests-to-implement transition is refused by `state.py` until a red run with a failing test (or a failed build) is recorded, with the reason.
- An independent verifier subagent (`rehorse-verifier`) checks every rehearsal before the report: it gets only the spec, the diff and the last test output, may write tests into one file of its own, must run the test command, and returns a JSON verdict (pass / concerns / fail) with findings and a per-criterion coverage map. A hook records the verdict; the report cannot be rendered without one.
- The report leads with the verdict (a `fail` is the banner), lists the verifier's findings and a per-criterion coverage table after the changes, and ends "Try it yourself" with the criteria no test covers. More than five findings go to `rehorse-reports/verifier/`. `PROGRESS.md` shows the verdict.
- A failing verdict, or a failing verifier test, sends the task back to implementation with the findings as new plan steps, at most twice; a third failure stops the task for you with the findings. A step that finds a test contradicting the spec (`CONTRADICTS SPEC:`) stops the task instead of working around it.
- While the verifier runs, Read, Grep and Glob outside its brief and the worktree are denied, so it never sees the implementer's summaries or earlier reports.
- The tests phase cannot end until every acceptance criterion in the spec is mapped to a test in a new test file; the mapping comes from the tests subagent's reply and is checked against the files.
