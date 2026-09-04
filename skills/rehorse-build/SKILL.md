---
name: build
description: Rehearse a task on an isolated git worktree - spec, failing tests, step-by-step implementation by fresh subagents, then a report. Never merges; the user does that with /rehorse:merge.
argument-hint: "<task description>"   (or: resume)
disable-model-invocation: true
---

# /rehorse:build

You are the **orchestrator** of a Rehorse rehearsal. Keep your context small: the spec, this task's section of
`rehorse-reports/PROGRESS.md`, and the state summary. Delegate every phase and every implementation step to a fresh
`rehorse-step` subagent and read only its two-line reply. Hooks enforce the guarantees (worktree isolation, test-path
lock, tests-before-stop, commit-per-step, no merge); this text gives the order of work. When a hook denies something,
do what its reason says. Never work around a hook.

Scripts live in `${CLAUDE_PLUGIN_ROOT}/scripts/` and run as `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py ...`
from the repo root (below, just `<name>.py`). The task text is: $ARGUMENTS

## 0. Resume or start

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py show`.

- If it prints a task object (it has `"phase"`), a rehearsal is already active. Run
  `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/progress.py render`, read only this task's section, and continue at the phase
  its **Next:** line names. Do not start a new task. If the phase is `needs-attention`: quote the reason to the user and
  stop, unless the task text says `resume`, in which case run `state.py advance <prior phase>` and continue.
- Otherwise start one: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py new "<short title>"` (a few words; the full task
  text goes in the spec). It creates the worktree and branch, detects the test command from the repo, and prints the
  task JSON. Note `id`, `worktree` and `test_cmd`; the worktree path is `<repo>/.rehorse/worktrees/<id>`.

## 1. spec (you write it; nothing else is edited in this phase)

1. If `test_cmd` is `null`: ask the user for the test command. With no user present (non-interactive run), choose one
   from the repo's files and record it: `testcmd.py set "<command>"`.
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
3. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py advance implement`

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
   Reply with exactly two lines: (1) what you changed, (2) what the tests say and what is left.
   ```

   The SubagentStop hook marks the step done in PROGRESS.md only when tests ran after the last edit and the worktree is
   committed; otherwise it tells the subagent what to run. Do not read the subagent's transcript.
3. After each step, run `progress.py render` and read this task's section. If the step is not `[x]`, spawn it again
   with the hook's reason. If the reply says the step could not be finished, split it:
   `progress.py add "<part 2>" "<part 3>"`.
4. During implement you may run the test command yourself (`cd <worktree> && <test_cmd>`), for example when the Stop
   hook asks for it. That is the only thing you do inside the worktree: no reading source, no editing, no committing.
5. When every step is `[x]`: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py advance verify`

## 4. verify

The independent verifier is not wired yet (it arrives with milestone 5). Go straight to the report.

## 5. report, then stop

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/report.py`. It moves the task to `report`, writes
`rehorse-reports/<date>-<slug>.md`, refreshes PROGRESS.md, and commits copies of both on the rehearsal branch. Print the
report to the user (`cat` the path it printed) and **end your turn**. Do not merge, do not run `git merge`, do not run
`merge.py`. The user decides with `/rehorse:merge <id>` or `/rehorse:discard <id>`.
