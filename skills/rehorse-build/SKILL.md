---
name: build
description: Rehearse a task on an isolated git worktree - spec, failing tests, step-by-step implementation by fresh subagents, then a report. Never merges; the user does that with /rehorse:merge.
argument-hint: "<task description>"   (or: resume)
disable-model-invocation: true
---

# /rehorse:build

You are the **orchestrator** of a Rehorse rehearsal. Keep your context small: the spec, this task's section of
`rehorse-reports/PROGRESS.md`, and the state summary. Delegate every phase and every implementation step to a fresh
`rehorse-step` subagent and read only its two-line reply; the verification to a `rehorse-verifier` subagent whose
verdict a hook records. Hooks enforce the guarantees (worktree isolation, test-path lock, tests-before-stop,
commit-per-step, red before implement, a verdict before the report, no merge); this text gives the order of work. When a hook denies something,
do what its reason says. Never work around a hook.

Scripts live in `${CLAUDE_PLUGIN_ROOT}/scripts/` and run as `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py ...`
from the repo root (below, just `<name>.py`). The task text is: $ARGUMENTS

## 0. Resume or start

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py show`.

- If it prints a task object (it has `"phase"`), a rehearsal is already active. Run
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/progress.py render`, read only this task's section, and continue at the phase
  its **Next:** line names. Do not start a new task. If the phase is `needs-attention`: quote the reason to the user and
  stop, unless the task text says `resume`, in which case run `state.py advance <prior phase>` and continue.
- If the folder is **not a git repository** (`git rev-parse --git-dir` fails): ask the user for permission to run
  `git init` and commit the current files exactly as they are. With permission (or no user present), run
  `git init -q && git add -A && git commit -q -m "Initial commit (as-is, before Rehorse)"` and **nothing else**: no
  refactor, no test harness, no `.gitignore` edits, no file moves. Everything that makes the code testable happens
  inside the rehearsal (phase `setup` below), where the hooks are live and the user can still discard it.
- Then start the task **immediately**, before any other command:
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py new "<short title>"` (a few words; the full task text goes in the
  spec). It creates the worktree and branch, links the repo's `.venv`/`node_modules`/`target`/`.tox` into it, detects
  the test command from the repo, and prints the task JSON. Note `id`, `worktree` and `test_cmd`; the worktree path is
  `<repo>/.rehorse/worktrees/<id>`. If `test_cmd` is `null` the task starts in phase `setup`; otherwise in `spec`.

## 1a. setup (only when no test command was detected; delegated)

The main checkout is untouched from here on. Spawn one `rehorse-step` subagent (`subagent_type: "rehorse:rehorse-step"`):

```
Rehorse phase: setup. Worktree: <worktree>. Edit only there.
This project has no test command Rehorse can run. Add the smallest harness that makes one real test runnable
(for example a pytest.ini and tests/, a Package.swift test target, a Makefile `test` target that builds and runs the
tests) and, only if needed, the smallest refactor that makes the code testable (a seam such as an injectable path,
a module split). Do not change behaviour. Run the harness once.
Commit: cd <worktree> && git add -A && git commit -m "setup: test harness for <id>"
Reply with exactly two lines: (1) the exact test command to run from the worktree root, (2) what you changed and why.
```

Record its command and move on: `testcmd.py set "<command>"`, then
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py advance spec`.

## 1. spec (you write it; nothing else is edited in this phase)

1. If `test_cmd` is still `null` (detection failed and no setup happened): ask the user for the test command, or with
   no user present choose one from the repo's files, and record it with `testcmd.py set "<command>"`.
2. Write `<worktree>/REHORSE_SPEC.md`. First line: one sentence stating the goal (the report quotes it). Then
   `## Acceptance criteria` (numbered, each testable), `## Files likely involved`, `## Assumptions` (every question you
   would have asked; if a user is present and the task is genuinely ambiguous, ask before writing).
3. Baseline: run exactly `cd <worktree> && <test_cmd>`. The PostToolUse hook records the counts. If it replies that the
   baseline ran 0 tests, the task is now `needs-attention`: fix the command with `testcmd.py set`, run
   `state.py advance spec`, and run the baseline again.
4. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py advance tests`

## 2. tests (delegated)

1. Spawn one `rehorse-step` subagent with the Agent tool (`subagent_type: "rehorse:rehorse-step"`) and this prompt:

   ```
   Rehorse phase: tests. Read <worktree>/REHORSE_SPEC.md first.
   Worktree: <worktree>. Edit only there. Test paths: <test_paths>.
   Write failing tests for every acceptance criterion, in test files only (implementation files are locked in this
   phase). Run: cd <worktree> && <test_cmd>   (failures are expected; that is the point).
   Commit: cd <worktree> && git add -A && git commit -m "tests: red for <id>"
   Reply with exactly two lines: (1) which tests you added and where, (2) what fails and why.
   ```

2. Run `cd <worktree> && <test_cmd>` yourself; the hook records `red_check`. **At least one test must fail.** If nothing
   fails, the tests do not test the feature: spawn the subagent again saying which criteria are untested.
3. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py advance implement` (it refuses, and says why, until a red run with a
   failure, or a failed build, is recorded).

## 3. implement (every step delegated)

1. Plan 1 to 6 steps. A step is what one subagent can finish, test and summarise without reading more than ~15 files.
   `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/progress.py plan "step 1 title" "step 2 title" ...`
   (it refuses while the tests are uncommitted, and records where the tests phase ended).
2. For each step in order, spawn a fresh `rehorse-step` subagent (`subagent_type: "rehorse:rehorse-step"`):

   ```
   Rehorse phase: implement, step <n> of <m>: <title>. Read <worktree>/REHORSE_SPEC.md first.
   Worktree: <worktree>. Edit only there, implementation files only (test paths are locked; if a test is wrong,
   say so in your reply instead of changing it).
   Previous step: <its two lines, or "none">
   Test command: cd <worktree> && <test_cmd>   (run it after your edits)
   Commit: cd <worktree> && git add -A && git commit -m "step <n>: <title>"
   Reply with exactly two lines: (1) what you changed, (2) what the tests say and what is left. If a test you must
   satisfy contradicts REHORSE_SPEC.md, reply instead with a last line starting "CONTRADICTS SPEC:" naming the test
   and the criterion.
   ```

   Steps titled `Fix (verifier round N): ...` and `Make the verifier's tests pass: ...` come from the verifier (§4); the
   verifier's own test file is locked like every other test. A `CONTRADICTS SPEC:` reply moves the task to
   `needs-attention` (the hook does it): quote the line to the user and stop.

   The SubagentStop hook marks the step done in PROGRESS.md only when tests ran after the last edit and the worktree is
   committed; otherwise it tells the subagent what to run. Do not read the subagent's transcript.
3. After each step, run `progress.py render` and read this task's section. If the step is not `[x]`, spawn it again
   with the hook's reason. If the reply says the step could not be finished, split it:
   `progress.py add "<part 2>" "<part 3>"`.
4. During implement you may run the test command yourself (`cd <worktree> && <test_cmd>`), for example when the Stop
   hook asks for it. That is the only thing you do inside the worktree: no reading source, no editing, no committing.
5. When every step is `[x]`: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py advance verify`

## 4. verify (delegated to the independent verifier)

1. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/verify.py brief` writes the verifier's brief (the spec, the diff and the last
   test output; never a step summary or a transcript) and prints the prompt. Spawn one `rehorse-verifier` subagent
   (`subagent_type: "rehorse:rehorse-verifier"`) with that output as its **whole prompt, verbatim**. Add nothing: not
   the step summaries, not your view of the code. It writes its own tests into one file, runs the test command, and
   ends with a JSON verdict.
2. Its SubagentStop hook records the verdict only after it ran the tests and committed; you never copy a verdict.
   Run `progress.py render` and read this task's section: the **Verifier** line and the **Next:** line. If no verdict
   was recorded, spawn it again with the hook's reason.
3. Do what **Next:** says. Three outcomes:
   - phase still `verify`, verdict recorded (`pass`, or `concerns`, or a `fail` the user must judge): `report.py` (§5).
   - phase `implement` again: the verdict was `fail` or the verifier's tests fail. The hook appended the findings as new
     plan steps and archived the verdict. Continue at §3.2 with the new steps, then `state.py advance verify` and run
     this section again (round 2, then 3 at most; the brief carries the earlier findings).
   - phase `needs-attention`: three rounds failed. Run `report.py --summary "..."` (it renders the reason and the
     findings), print the report, quote the reason to the user, and stop. The user resumes with `/rehorse:build resume`
     (which renders the FAIL report for a merge/discard decision) or discards.

## 5. report, then stop

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/report.py --summary "<summary>"`. The summary is the one part of the report
in your own words, and the report labels it as written by the model: three to five sentences on what the user gets on
merge, what was verified (which tests, which behaviour) and what was not (anything only type-checked, built, or
eyeballed), and anything they should know before merging. The script moves the task to `report`, writes
`rehorse-reports/<date>-<slug>.md` (with a "Try it yourself" section: the worktree path, the test command and how to
run the project), refreshes PROGRESS.md, and commits copies of both on the rehearsal branch. Print the report to the
user (`cat` the path it printed) and **end your turn**. Do not merge, do not run `git merge`, do not run
`merge.py`. The user decides with `/rehorse:merge <id>` or `/rehorse:discard <id>`.
