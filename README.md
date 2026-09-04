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

> Pre-release. The verifier subagent (milestone 5) and the marketplace listing (milestone 8) are still to come; see
> [Status](#status).

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
on a toy repo):

```markdown
# Rehearsal report: Add sub(a, b) to app.py returning a - b.

Task `t-20260903-add-sub-function` · branch `rehorse/t-20260903-add-sub-function` · base `b59e534` · 2026-09-03

## GREEN: 8 passed, 0 failed · unverified

| stage                                   | passed | failed |
| baseline                                | 2      | 0      |
| red (tests written, no implementation)  | 3      | 5      |
| green (last run)                        | 8      | 0      |

## Changes (base..HEAD)
 app.py            | 4 ++++
 tests/test_sub.py | 22 ++++++++++++++++++++++

## Test-file drift
none: test files unchanged since the tests phase.

## Next
/rehorse:merge t-20260903-add-sub-function      merge into your branch and remove the worktree
/rehorse:discard t-20260903-add-sub-function    drop the worktree and the branch
```

Below the numbers the report has a "Try it yourself" section with the worktree path, the test command and, when
detectable, how to run the project, and an optional summary in the model's own words, labelled as such. Read it, then
decide:

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
5. **verify** – an independent verifier that has not seen how the code was built (milestone 5).
6. **report** – the report is written, committed on the rehearsal branch, and the session ends.

If a session is interrupted, compacted, or you open a new one, Rehorse injects a one-line state summary and
continues from PROGRESS.md. If the model gets stuck (for example, it keeps trying to stop without running tests), the
task drops to `needs-attention` with the reason instead of ending silently; `/rehorse:status` shows it and
`/rehorse:build resume` continues.

### What Rehorse writes in your repo

- `.rehorse/` (added to your `.gitignore` on first run): `state.json`, the single source of truth, and the worktrees.
- `rehorse-reports/`: `PROGRESS.md` and one report per task. These are meant to be committed; the merge brings them in
  from the rehearsal branch.
- `~/.rehorse/`: one-shot merge/discard grants, outside every repo, deleted when used.

## The guarantees

While a task is active, regardless of permission mode:

- **Isolation.** Edits outside the rehearsal worktree are denied (except `rehorse-reports/`). Writing files from the
  shell (`>>`, `tee`, `cp`, `mv`, `sed -i` ...) into the repo is denied too, so the lock cannot be sidestepped.
- **Tests are locked when it implements.** In the tests phase only test files can change; in the implement phase
  test files cannot change at all. The report flags any drift in test files after the tests phase.
- **Red before green, with evidence.** A test run counts only if it ran inside the worktree and printed the runner's
  own summary line. A baseline that runs zero tests stops the task. A red run that does not even compile because the
  new tests name symbols that do not exist yet counts as red, and the report says so instead of showing counts.
- **No stopping with untested edits.** The turn cannot end, and a step cannot close, until the tests ran after the
  last edit and the work is committed.
- **No merge.** `git merge/rebase/push/checkout/reset --hard` and friends are denied, along with `rm -rf` on your repo
  and `--no-verify`. Only `/rehorse:merge` and `/rehorse:discard`, typed by you, touch your branch.

Every denial tells the model what it may do instead.

### How red-then-green works

Rehorse never edits your existing tests. Red comes from new tests written from the spec before any implementation
exists, run against your unchanged code; if they cannot fail, the task does not move on. Green comes from
implementation code that satisfies them, written while every test file is locked, so the only way to green is to
change the code. A new test that passes before the implementation exists is flagged in the report as possibly
testing nothing. Bug fixes follow the same flow: the new test reproduces the bug first, then the fix makes it pass.

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
| 5. Red-before-green gate, verifier agent, verdict in the report | next |
| 6–7. Eval on `rich`, `fastapi`, `zod` (graded by the upstream PRs' tests) | |
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

Hook scripts are written test-first, stay under 150 lines, and import only the standard library.

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

## License

MIT. See [LICENSE](LICENSE).
