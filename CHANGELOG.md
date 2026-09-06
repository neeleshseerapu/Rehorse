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
- A plan step that needed no edits is reported as already satisfied by the step that did the work.
- The tests phase may change a test the repo already had only when the spec says the behaviour it pins is wrong, and only
  by declaring it: the reply names the test and the criterion, the hook refuses the stop otherwise, and `state.py` refuses
  the transition to implementation for the same reason. Declared changes are shown to the verifier ahead of the diff,
  counted in the report as "Existing tests changed" with the reason for each, and no longer reported as test-file drift.
- A verifier `fail` must cite the acceptance criterion it violates; one that cites none is recorded as `concerns`, and the
  hook says so. `concerns` is for a specific risk worth reading before merging, not for style notes or for coverage the
  verifier itself added.
- `/rehorse:merge` reports how many verifier tests are merged with the change; the verifier is asked for the fewest tests that demonstrate each finding.
- Red is judged by failing test ids, not counts: the baseline's failing tests are recorded (pytest runs with `-rfE`) and the tests phase ends only when a test fails that was not failing at baseline. Pre-existing failures are listed in the report as ignored; runners that print no ids fall back to counts with a warning.
- Regression guards: a new test marked `# rehorse: guard` (or `// rehorse: guard`) is expected to pass before the implementation; the report says "N guard(s) expected to pass; M unexpected pass(es)" and warns only when M > 0. A failing guard does not count as red.
- `eval/results.md` opens with the grading methodology (task selection, base commit, grading from the PR's merge commit, environment pins) above the results table, which now carries each task's tier.
- Hook scripts may now share logic through `scripts/rehorse_lib/` (standard library only, no install step). The 150-line cap still applies to every script Claude Code invokes as a hook, and is now checked by the test suite along with the stdlib-only rule.
- A verifier finding may say that an existing test pins the behaviour the spec calls a bug (`pins_bug`, with the test id). That sends the task back to the tests phase, not to the implementer, who may not edit a test: the test is rewritten there with a declared reason, then implementation and verification run again, and the trip costs one of the three rounds. The report shows "Round N: test revision" with the test and the reason. The tests phase may not edit the verifier's own test file, and re-planning is refused once a round trip has added steps.
- Every acceptance criterion in `REHORSE_SPEC.md` records where it came from: `[issue]` (the task text asks for it) or `[inferred]` (the model added it). A rewritten test cites the criterion that authorises it, and one resting only on inferred criteria is rendered as a warning in the report and in the verifier's brief. The report's coverage table shows each criterion's source. Sub-bullets under a criterion are no longer counted as criteria of their own.
- A test run narrowed to part of the suite — file paths, node ids, `-k` or `-m` past the runner — is recorded as a diagnostic instead of a test run. It cannot show red or green, cannot become the baseline, and does not let the turn end; the Stop hook keeps asking for the full command, and the report notes "Diagnostic runs: N" beside the tests table.
- A step that says an existing test contradicts the spec now names it (`<file>::<test>`) and the task goes back to the tests phase for a second opinion, the same trip a verifier `pins_bug` finding buys and at the same cost of one round. The tests agent judges the claim itself: it rewrites the test with a declared reason, or says the claim is wrong, and only then does the task stop for you — with both claims. A claim naming no test, or one on the last round, still stops the task directly.
- A step that fixes a verifier finding is told to stay in the caller or case the finding named. A fix in shared code that other callers go through must name, in the step summary, the other callers it checked and the tests that cover them — the summary the report shows you at merge time.
- A task that stops at `needs-attention` now gets its report written by the hook that stopped it, with the reason as the banner — a walk-away stop leaves the same artifact a finished rehearsal does, whether it came from a step's `CONTRADICTS SPEC:`, a third failing verifier round, the Stop or SubagentStop block cap, or a baseline that ran no tests.
