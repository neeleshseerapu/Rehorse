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

   **Every criterion starts with `[issue]` or `[inferred]`**, right after its number: `1. [issue] ...`. `[issue]` means
   the task text asks for it — quoted, or paraphrased closely enough that a reader of the issue would recognise it.
   `[inferred]` means you added it: a consequence you worked out, a regression you decided to guard, a decision about
   existing tests. Inferring is expected and is not penalised; mislabelling is, because a rewrite of a test the repo
   already had is later judged by whether the criterion behind it came from the issue or from you. When in doubt it is
   `[inferred]`. Sub-bullets under a criterion are part of it and are not tagged.
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
   phase). A regression guard you expect to pass now gets `# rehorse: guard` (or `// rehorse: guard`) on the line
   above its definition; every other new test must fail. Run: cd <worktree> && <test_cmd>   (failures are expected;
   that is the point).
   Add tests; do not rewrite the ones already in the repo. The one exception is a test whose expectation REHORSE_SPEC.md
   says is wrong — then change it and declare it, quoting the criterion that says so. Anything else you disagree with
   stays as it is and goes in your reply.
   Commit: cd <worktree> && git add -A && git commit -m "tests: red for <id>"
   Reply with two lines, (1) which tests you added and where, (2) what fails and why, then a ```json block
   {"coverage": [{"criterion": "<criterion or its number>", "ref": "<test file>::<test name>"}],
    "expected_test_changes": [{"test": "<file>::<test>", "criterion": "<the criterion or its number>",
                               "why": "<one line: what that criterion says the old expectation got wrong>"}]}
   with one entry per acceptance criterion in REHORSE_SPEC.md, and one expected_test_changes entry per existing test you
   changed (omit it when you changed none). Cite the criterion that authorises each rewrite: a rewrite resting only on
   criteria the spec marks [inferred] is reported to the user, and to the verifier, as a warning. The hook records both
   and refuses the stop while a criterion has no test or an existing test changed with no reason given.
   ```

2. Run `cd <worktree> && <test_cmd>` yourself; the hook records `red_check`. **At least one test that was not failing at
   baseline must fail** (the hook says how many new failures it saw; failures that also fail at baseline do not count).
   If nothing new fails, the tests do not test the feature: spawn the subagent again saying which criteria are untested.
3. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/state.py advance implement` (it refuses, and says why, until a red run with a
   failure, or a failed build, is recorded and every acceptance criterion maps to a new test; if it names uncovered
   criteria, spawn the tests subagent again with that list).

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
   If this step is titled "Fix (verifier round <n>)", it names one case or caller: fix it there, not in the shared
   code underneath. If the narrowest correct fix is in shared code, line 1 must name the other callers you checked
   and the tests that cover them; if you cannot name them, scope the fix to the caller the finding named.
   Reply with exactly two lines: (1) what you changed, (2) what the tests say and what is left. If a test you must
   satisfy contradicts REHORSE_SPEC.md, reply instead with a last line starting "CONTRADICTS SPEC:" naming that test
   as <file>::<test> and the criterion it contradicts.
   ```

   Steps titled `Fix (verifier round N): ...` and `Make the verifier's tests pass: ...` come from the verifier (§4); the
   verifier's own test file is locked like every other test (in the tests phase too). A `CONTRADICTS SPEC:` reply naming a
   test moves the task to `tests` for a second opinion on that test (the hook does it, and it costs one of the three rounds):
   go to §4's `tests` branch. One naming no test, or one on the last round, moves the task to `needs-attention` instead:
   quote the line to the user and stop.

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
3. Do what **Next:** says. Four outcomes:
   - phase still `verify`, verdict recorded (`pass`, or `concerns`, or a `fail` the user must judge): `report.py` (§5).
   - phase `implement` again: the verdict was `fail` or the verifier's tests fail. The hook appended the findings as new
     plan steps and archived the verdict. Continue at §3.2 with the new steps, then `state.py advance verify` and run
     this section again (round 2, then 3 at most; the brief carries the earlier findings).
   - phase `tests` again: someone said an existing test pins the behaviour the spec calls a bug, and the implementer
     cannot touch a test. It reaches here two ways — a verifier finding carrying `pins_bug`, or a step's
     `CONTRADICTS SPEC:` line (§3.2) — and the answer is the same either way; **Next:** in PROGRESS.md names which, the
     test, and the claim in the claimant's own words. Spawn one `rehorse-step` subagent with the §2 tests prompt,
     replacing its first paragraph with:

     ```
     Rehorse phase: tests, revision (round <n>). Read <worktree>/REHORSE_SPEC.md first.
     <the verifier | step <k>> claims <test id> asserts the behaviour the spec calls the bug: <the claim, verbatim>.
     Judge that claim yourself against REHORSE_SPEC.md and that test. If it holds, change that test to what the
     criterion requires and nothing else — no other test, no implementation file (locked in this phase), not the
     verifier's rehorse_verify_* file — and declare it in expected_test_changes with the criterion. If it does not
     hold, change nothing and make your last line start "CONTRADICTS SPEC:" saying why the claim is wrong.
     ```

     If it agrees, its reply needs the same coverage block plus an `expected_test_changes` entry for that test naming
     the criterion; the hook refuses the stop without one. Then `state.py advance implement` and continue at the plan
     step you were on — **do not run `progress.py plan`**, which would drop the steps this round bought (it refuses,
     and says so). If it disagrees, the hook moves the task to `needs-attention` with **both** claims in the reason:
     run `report.py` (§5), quote both to the user and stop. Nobody but the user settles a disagreement between two
     agents that have each read the spec.
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
