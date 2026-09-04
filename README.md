# Rehorse

Auto mode for Claude Code that you can walk away from. Every task rehearses on a git worktree,
must go red-then-green on tests, is checked by an independent verifier subagent, and stops with a
report. Nothing touches your real branch until you run `/rehorse:merge`.

The workflow is enforced by **hooks** (Python scripts Claude Code runs on every tool call), not by
prompt prose. Hook denials hold even under `--dangerously-skip-permissions`.

## Status

Pre-release, built in numbered milestones (see `PROMPT.md`, the spec, and `DECISIONS.md`, the evidence).

| Milestone | State |
|---|---|
| 1. Day-1 spikes (11 assumptions about Claude Code hooks, proven with evidence) | done |
| 2. `scripts/state.py`, `worktree.py`, `testcmd.py` + tests | done |
| 3. Hook scripts (`guard_edit`, `guard_bash`, `on_bash_done`, `guard_stop`) + `hooks.json`, live-checked on a toy repo | done |
| 4. Skills, report/progress/handoff, end-to-end on a toy repo | next |
| 5. Red-before-green, test-path lock, verifier agent | |
| 6–8. Eval harness (`rich`, `fastapi`, `zod`), demo, publish | |

## Layout so far

```
.claude-plugin/plugin.json   manifest (name `rehorse`, so skills are /rehorse:<name>)
hooks/hooks.json             wires events to scripts, exec form: {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/..."]}
scripts/state.py             .rehorse/state.json: the single source of truth; phase machine; SessionStart summary
scripts/worktree.py          create / list / diff / dirty / remove rehearsal worktrees under .rehorse/worktrees/
scripts/testcmd.py           detect the test command; recognise test runs, test paths, pass/fail counts, effective cwd
scripts/guard_edit.py        PreToolUse Edit|Write|MultiEdit: worktree isolation, phase path lock, orchestrator rule, edit_seq
scripts/guard_bash.py        PreToolUse Bash: no branch mutation, no commit outside the worktree, no rm -rf on repo/.rehorse
scripts/on_bash_done.py      PostToolUse + PostToolUseFailure Bash: record real test runs (baseline / red_check / last_test_run)
scripts/guard_stop.py        Stop: in implement, block the turn until tests ran after the last edit (8-block cap -> needs-attention)
tests/                       pytest for every script; tests/fixtures/hook_inputs/ are real hook payloads from the spikes
```

## What the hooks guarantee (and what they do not)

While a task is active (any phase before `merged`/`discarded`), regardless of permission mode:

- **Isolation.** Edit/Write/MultiEdit outside `.rehorse/worktrees/<task>/` is denied, except `rehorse-reports/` (the
  evidence trail). `.rehorse/state.json` is never edited directly; phases move only through `scripts/state.py`.
- **Test-path lock.** Phase `tests`: only test files may be edited. Phase `implement`: test files are locked, and
  the main thread (no `agent_id` in the hook input) may not edit at all; step subagents do the editing.
- **No branch mutation.** `git merge/rebase/pull/push/checkout/switch`, `reset --hard`, branch delete/move and
  `git worktree` changes are denied everywhere; `git commit` is denied outside the worktree; `rm -rf` on the repo
  root, its parents, `.rehorse/` or a worktree root is denied; `--no-verify` and `core.hooksPath` are denied.
- **Red before green, evidence-based.** A test run is recorded only when the command runs the task's runner inside
  the worktree and its output parses to the runner's own summary line. `--collect-only`, `--version` and grep hits
  do not count. A baseline of 0 tests sends the task to `needs-attention`.
- **No stopping mid-implement with untested edits.** The Stop hook blocks, naming the exact command, until a run is
  recorded after the last edit. After 8 consecutive blocks the task drops to `needs-attention` instead of ending silently.

Every denial says what the model may do instead. Known limits: `guard_bash.py` is a token check, not a shell
parser (it splits on operators, parentheses and backticks and recurses into `-c "..."`/`eval` strings, but a
sufficiently creative script can evade it); the hooks run per tool call, so a subagent's turn is checked the same
way as the main thread's, and `edit_seq` is bumped before an Edit runs, so an Edit that then fails still counts.

Runtime dependencies: Python 3 stdlib and git. Nothing else, ever, at hook time.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install pytest   # dev only
.venv/bin/python -m pytest tests/ -q

# exercise a script the way Claude Code will: JSON on stdin, JSON on stdout
python3 scripts/state.py --summary < tests/fixtures/hook_inputs/sessionstart_resume.json
python3 scripts/testcmd.py parse   < tests/fixtures/hook_inputs/posttoolusefailure_bash_pytest_fail.json
python3 scripts/guard_bash.py      < tests/fixtures/hook_inputs/pretooluse_bash_git_merge.json   # dormant: prints nothing

# load the plugin from this checkout in any repo; --debug-file records which hooks matched, exit codes and output
claude --plugin-dir /path/to/Rehorse --debug-file /tmp/hooks.log
claude plugin validate .
```

Every hook script is written test-first, stays under 150 lines, and imports only the stdlib.
