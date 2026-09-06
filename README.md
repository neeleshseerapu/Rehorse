<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo.svg" alt="Rehorse" width="160" height="160">
  </picture>
</p>

<h1 align="center">Rehorse</h1>

<p align="center">Auto mode for Claude Code that you can walk away from.</p>

Type one command, leave, and come back to a report. Every task rehearses on its own git worktree, has to go
red-then-green on your tests, and stops. Nothing touches your branch until you type `/rehorse:merge`.

The rules are enforced by **hooks**, small Python scripts Claude Code runs on every tool call, not by prompt
prose. The model cannot edit outside the rehearsal, cannot touch your tests while it implements, cannot stop with
untested edits, and cannot merge. Those hold even with permissions bypassed.

> Pre-release. The eval on real repos (milestones 6 and 7) and the marketplace listing (milestone 8) are still to come;
> see [Status](#status).

## Install

You need Claude Code, git, and Python 3. For now your project also needs a test suite Rehorse can run: pytest,
vitest, jest, `npm test`, `cargo test`, `go test`, `swift test`, or a `make test` target. Red-then-green needs something to go red.
A no-tests path, where the first step writes a characterization test of the current behaviour before anything
changes, is planned but not built.

Until the marketplace listing exists, load the plugin from a clone:

```bash
git clone https://github.com/neeleshseerapu/Rehorse.git ~/Rehorse
cd your-project
claude --plugin-dir ~/Rehorse
```

Check it loaded with `/rehorse:status` (it should say there is no active task). Nothing is installed anywhere else,
and there are no dependencies to add: the hooks use only the Python standard library.

## Use it

```
/rehorse:build "add a --json flag to the export command"
```

Then walk away. When you come back, `rehorse-reports/<date>-<slug>.md` in your repo looks like this (from a real run
on a toy repo whose implementer had left the divide-by-zero branch untested and unimplemented; the verifier's round 1
caught it, a fix step followed, and round 2 passed; abridged):

```markdown
# Rehearsal report: Add divide(a, b) to app.py, returning a / b.

Task `t-20260904-add-divide` · branch `rehorse/t-20260904-add-divide` · base `f778950` · 2026-09-04

## GREEN: 28 passed, 0 failed · verifier PASS

| stage                                   | passed | failed |
| baseline                                | 2      | 0      |
| red (tests written, no implementation)  | 2      | 1      |
| green (last run)                        | 28     | 0      |

## Changes (base..HEAD)
 app.py                                             |   7 +
 tests/test_divide.py                               |   5 +
 tests/test_rehorse_verify_t-20260904-add-divide.py | 155 +++++++++++++++++++++

## Verifier: PASS (round 2 of 3)
Its run: 28 passed, 0 failed. Tests added: 12 in tests/test_rehorse_verify_t-20260904-add-divide.py
Findings: none

| acceptance criterion                                               | evidence | ref                                  |
| divide(6, 3) == 2                                                  | test     | ...::test_divide_6_by_3_equals_2     |
| divide(1, 0) raises ValueError with the message "division by zero" | test     | ...::test_divide_by_zero_message_... |

Round 1: FAIL (3 finding(s); its run 10 passed / 6 failed)
- [high] app.py:6 divide() is a bare `return a / b`; divide(1, 0) raises ZeroDivisionError, which is not a
  ValueError subclass, so acceptance criterion 2 is unmet. Shown by ::test_divide_by_zero_raises_value_error ...
- [medium] app.py:6 Float zero divisors (0.0, -0.0) escape as ZeroDivisionError with message 'float division by zero' ...
- [low] tests/test_divide.py:4 The implementer's only test covers divide(6, 3); no test in the diff exercises the
  zero-divisor branch that criterion 2 requires, so the reported '3 passed' gave no signal about the unmet criterion.

## Test-file drift
none: test files unchanged since the tests phase (`e51ad94`).

## Plan
- [x] 1. add divide(a, b) to app.py — Added divide(a, b) to app.py. Tests: 3 passed, 0 failed; nothing left.
- [x] 2. Fix (verifier round 1): divide() is a bare `return a / b`; divide(1, 0) raises ZeroDivisionError ... (app.py:6)
- [x] 3. Make the verifier's tests pass: tests/test_rehorse_verify_t-20260904-add-divide.py (6 failing) — No edits: ...

## Next
/rehorse:merge t-20260904-add-divide      merge rehorse/t-20260904-add-divide into your branch and remove the worktree
/rehorse:discard t-20260904-add-divide    drop the worktree and the branch
```

That is a rehearsal that worked. Here is one that did not, from the `rich` eval: `rich-3577` asked for
`Text.from_ansi` to stop dropping trailing newlines. Rehorse wrote the tests, implemented the fix, and the verifier
agreed the new output was right — then failed the round anyway, because one test the repo already had,
`tests/test_ansi.py::test_decode_example`, pinned the old output and now needed one more `\n` in its expected string.
Test files are locked once the tests phase ends, and a rehearsal cannot go back to that phase, so the one edit left
was the one Rehorse would not make. It stopped at `needs-attention` and said so: "The fix itself is complete; update
that one expected string on merge." Eleven minutes of work, handed back with a sentence of homework.

The tests phase can now make that edit, but only deliberately: it may change a test the repo already had when
`REHORSE_SPEC.md` says the behaviour that test pins is wrong, and it must name the test and the criterion that says so.
The declaration is recorded, the verifier is shown those tests first and checks the reason against the spec, the report
counts them under "Existing tests changed", and drift detection stops calling them drift.

That fixes the case the tests phase spots up front. The harder half is the one `rich-3577` actually hit, where nobody
notices until the fix is written and the suite will not go green. So the verifier can now say it: a finding marked
`pins_bug`, naming the test, sends the task **back to the tests phase** rather than to the implementer — who could
only answer it by editing a locked file. The test is rewritten there with a declared reason, implementation resumes at
the step it was on, and verification runs again; the whole trip costs one of the three rounds, like any other. The
report says which round that was, which test it rewrote and why. What has not changed is the lock itself: the
implementer still may not touch a test, and a step that finds one contradicting the spec still stops the task for you.
The rewrite is a decision someone has to own, so it happens in the open, at the one phase whose job is deciding what
the tests should say — and never to the verifier's own tests, which that phase may not edit at all.

Below the numbers the report has a "Try it yourself" section with the worktree path, the test command, how to run
the project when detectable, and the acceptance criteria no test covers (what to eyeball), plus an optional summary in
the model's own words, labelled as such. Read it, then decide:

```
/rehorse:merge      # fast-forward (or merge) the rehearsal into your current branch, remove the worktree
/rehorse:discard    # remove the worktree and branch; your branch is untouched
```

Both take an optional task id and default to the active task. Only you can run them: the authorization is minted
when *you* type the command, and the scripts refuse without it.

### Commands

| Command | What it does |
|---|---|
| `/rehorse:build "<task>"` | Start a rehearsal. With a task already active, it resumes from where it stopped. |
| `/rehorse:build resume` | Resume a task that stopped in `needs-attention`, from the phase it was in. |
| `/rehorse:status` | Show `rehorse-reports/PROGRESS.md`: phase, plan steps, last test result, next action. Read-only. |
| `/rehorse:merge [id]` | Merge the finished rehearsal into your current branch. |
| `/rehorse:discard [id]` | Drop the rehearsal. |

### What happens while you are away

0. **your branch is left alone.** If the folder is not a git repo yet, Rehorse asks before running `git init` and
   commits your files exactly as they are. That is the only thing it ever does outside the rehearsal.
1. **setup** (only when no test command is detectable) – inside the worktree, a subagent adds the smallest harness
   that runs one real test, and the smallest refactor needed to make the code testable, committed on the rehearsal
   branch. You can discard all of it.
2. **spec** – a worktree `.rehorse/worktrees/<id>/` on branch `rehorse/<id>` is created from your HEAD with your
   `.venv`/`node_modules` linked in, the test command is detected from your repo (its `.venv`, pyproject,
   package.json, Makefile, Package.swift), a short spec is written, and your tests run once for the baseline.
3. **tests** – a fresh subagent writes failing tests from the spec. It can only touch test files. At least one test
   must fail before the task moves on.
4. **implement** – the work is split into 1 to 6 steps. Each step is a fresh subagent that may edit implementation
   files only, must run the tests, and must commit. The orchestrator never reads source; it reads two-line summaries.
5. **verify** – an independent verifier subagent that has not seen how the code was built. It gets only the spec, the
   diff and the last test output (a script writes that brief; the orchestrator adds nothing), assumes the tests were
   written to pass, writes its own tests into one file of its own, runs the suite, and returns a verdict: `pass`,
   `concerns` or `fail`, with findings and a per-criterion coverage map. A hook records the verdict; nobody copies it.
   A `fail`, or a failing verifier test, sends the task back to implement with the findings as new steps, at most
   twice; a third failure stops the task for you.
6. **report** – the report is written, committed on the rehearsal branch, and the session ends. The verdict is the
   banner; the report cannot be rendered without one.

If a session is interrupted, compacted, or you open a new one, Rehorse injects a one-line state summary and
continues from PROGRESS.md. If the model gets stuck (for example, it keeps trying to stop without running tests), the
task drops to `needs-attention` with the reason instead of ending silently; `/rehorse:status` shows it and
`/rehorse:build resume` continues.

### What Rehorse writes in your repo

- `.rehorse/` (added to your `.gitignore` on first run): `state.json`, the single source of truth, and the worktrees.
- `rehorse-reports/`: `PROGRESS.md`, one report per task, and `verifier/` for findings too long for the report. These
  are meant to be committed; the merge brings them in from the rehearsal branch.
- `~/.rehorse/`: one-shot merge/discard grants, outside every repo, deleted when used.

## The guarantees

While a task is active, regardless of permission mode:

- **Isolation.** Edits outside the rehearsal worktree are denied (except `rehorse-reports/`). Writing files from the
  shell (`>>`, `tee`, `cp`, `mv`, `sed -i` ...) into the repo is denied too, so the lock cannot be sidestepped.
- **Tests are locked when it implements.** In the tests phase only test files can change; in the implement phase
  test files cannot change at all. The report flags any drift in test files after the tests phase.
- **Red before green, with evidence.** A test run counts only if it ran inside the worktree and printed the runner's
  own summary line. A baseline that runs zero tests stops the task. The task cannot leave the tests phase until a red
  run is recorded with a failing test that was not failing at baseline (by test id; pre-existing failures are listed
  in the report and ignored). A red run that does not even compile because the new tests name symbols that do
  not exist yet counts as red, and the report says so instead of showing counts.
- **Verified by someone else, before the report.** The verifier's stop is held until it ran the tests, committed, and
  returned a JSON verdict; that verdict is written to state by the hook, and the report cannot be rendered without
  one. During verification the only writable file is the verifier's own test file; afterwards it is locked like every
  test. The verifier's inputs are enforced too: while it runs, Read, Grep and Glob are denied outside its brief and the
  worktree, so it never sees `rehorse-reports/`, `PROGRESS.md` or the step summaries.
- **No stopping with untested edits.** The turn cannot end, and a step cannot close, until the tests ran after the
  last edit and the work is committed.
- **No merge.** `git merge/rebase/push/checkout/reset --hard` and friends are denied, along with `rm -rf` on your repo
  and `--no-verify`. Only `/rehorse:merge` and `/rehorse:discard`, typed by you, touch your branch.

Every denial tells the model what it may do instead.

### How red-then-green works

Rehorse never edits your existing tests. Red comes from new tests written from the spec before any implementation
exists, run against your unchanged code; if they cannot fail, the task does not move on. Red is judged by test ids,
not counts: a test that already failed before Rehorse started does not make a run red. Green comes from
implementation code that satisfies them, written while every test file is locked, so the only way to green is to
change the code. A new test that passes before the implementation exists is flagged in the report as possibly
testing nothing, unless it is marked `# rehorse: guard` (a regression guard, expected to pass); the report counts
guards and unexpected passes separately. Bug fixes follow the same flow: the new test reproduces the bug first, then the fix makes it pass.

### What this is not

Hooks stop **shortcuts**, not an **adversarial model**. Bash can run arbitrary programs, and a determined program can
write any file you can. Rehorse makes the honest path the only one the hooks describe and makes the dishonest path
require deliberate obfuscation: an accident cannot merge, only intent can. Rehorse never widens permissions either;
your own permission prompts still apply in default mode.

Out of scope for v1: model routing, non-git repos, running several tasks in parallel, any UI.

## Status

| Milestone | State |
|---|---|
| 1. Day-1 spikes: 11 assumptions about Claude Code hooks, proven with evidence | done |
| 2. State, worktree and test-command scripts | done |
| 3. The four guard hooks, live-checked | done |
| 4. Skills, step agent, progress/report/merge, user-granted merge authority; live-checked end to end | done |
| 5. Red-before-green gate, verifier agent, verdict in the report, verify round-trip; live-checked | done |
| 6–7. Eval on `rich`, `fastapi`, `zod` (graded by the upstream PRs' tests) | next |
| 8. Marketplace listing, install instructions, demo | |

## Contributing

The spec is `SPEC.md`; every decision and the evidence behind it is in `DECISIONS.md`; ideas out of scope are in
`IDEAS.md`. The layout follows the Claude Code plugin format: `skills/`, `agents/`, `hooks/hooks.json`, `scripts/`.

```bash
python3 -m venv .venv && .venv/bin/pip install pytest    # dev only
.venv/bin/python -m pytest tests/ -q                     # every script is tested against real hook payloads
claude plugin validate .
bash tests/e2e_live.sh /tmp/rehorse-e2e                  # real sessions on toy repos: build, merge, compact, resume
```

Hook scripts are written test-first and import only the standard library. Each one Claude Code invokes stays under
150 lines, so you can read the thing that enforces a guarantee before you trust it; the logic they share lives in
`scripts/rehorse_lib/`, which has no cap and the same stdlib-only rule. `tests/test_line_cap.py` checks both.

### Development

`main` is kept green: pytest passes on every commit, so any commit is safe to load. Releases are tagged. The plugin
runs from whatever is checked out in the directory you pass to `--plugin-dir`, so a half-finished change in your
working tree is live in every session that uses it. To test Rehorse on another project while mid-change, keep a second
clone checked out at the latest tag and point `--plugin-dir` at that one.

### Testing Rehorse on your own project

The most useful thing you can do right now is run it on a real repo. Clone this repository, start Claude Code in
your project with `claude --plugin-dir /path/to/Rehorse`, and give `/rehorse:build` one small, well-tested task, the
kind you would hand a new teammate on their first day. Read the report in `rehorse-reports/` before deciding to merge
or discard. If anything looked wrong, the test command it detected, a hook that denied something it should not have,
a report that misrepresents what happened, open an issue with the report attached and, if you can, the lines from
`claude --debug-file` that mention `Hook`. Nothing you run touches your branch until you type `/rehorse:merge`.

### Eval

`eval/` measures Rehorse on real bug-fix tasks from open-source repos, SWE-bench style: the task is a closed GitHub
issue, and the grade is the tests from the upstream PR that fixed it, never Rehorse's own tests.

```bash
python3 eval/find_tasks.py Textualize/rich          # closed issues whose merged PR touched 1-5 files incl. a test
python3 eval/run_eval.py                            # every task in eval/tasks.json; resumable; results in eval/results.md
python3 eval/run_eval.py --only rich-3881 --rerun   # one task again
```

`find_tasks.py` writes candidates in the `tasks.json` schema (`id, repo, base_sha, issue_url, issue_title, issue_body,
pr_url, pr_test_files, test_cmd, setup_cmd`); `base_sha` is the base branch the moment before the fix merged. For each
task `run_eval.py` clones the repo at `base_sha` into `/tmp/rehorse-eval/<id>`, runs `setup_cmd` (the target's own
venv), runs `claude -p "/rehorse:build \"<issue>\""` with this plugin and permissions bypassed, then checks the PR's
test files out into the rehearsal worktree and runs them. One JSON result per task lands in `eval/results/` with a copy
of the report; a task with a result is skipped on the next run, and a failure in one task is a row, not an abort.
Columns: self-green (Rehorse reached its report with a green run: its own claim, not the grade), rehorse-outcome
(the phase it stopped in: green, needs-attention, error), upstream-tests-pass (the grade), verifier verdict
and rounds, wall time, session turns, report.

Ten `rich` tasks have run (`eval/results.md`): nine pass the upstream PR's tests, eight reached a green report of
their own, and none errored. The two that did not finish are worth more than the eight that did — `rich-3577` is the
pinned-test stop described above, and `rich-3871` was stopped by its own verifier after three rounds for a regression
the upstream tests never cover, which is why its row says `needs-attention` next to `upstream-tests-pass: yes`.

## License

MIT. See [LICENSE](LICENSE).
