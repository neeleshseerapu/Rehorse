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
| 3. Hook scripts (`guard_edit`, `guard_bash`, `on_bash_done`, `guard_stop`) + `hooks.json` | next |
| 4. Skills, report/progress/handoff, end-to-end on a toy repo | |
| 5. Red-before-green, test-path lock, verifier agent | |
| 6–8. Eval harness (`rich`, `fastapi`, `zod`), demo, publish | |

## Layout so far

```
scripts/state.py      .rehorse/state.json: the single source of truth; phase machine; SessionStart summary
scripts/worktree.py   create / list / diff / dirty / remove rehearsal worktrees under .rehorse/worktrees/
scripts/testcmd.py    detect the test command; recognise test runs, test paths, pass/fail counts
tests/                pytest for every script; tests/fixtures/hook_inputs/ are real hook payloads from the spikes
```

Runtime dependencies: Python 3 stdlib and git. Nothing else, ever, at hook time.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install pytest   # dev only
.venv/bin/python -m pytest tests/ -q

# exercise a script the way Claude Code will: JSON on stdin, JSON on stdout
python3 scripts/state.py --summary < tests/fixtures/hook_inputs/sessionstart_resume.json
python3 scripts/testcmd.py parse   < tests/fixtures/hook_inputs/posttoolusefailure_bash_pytest_fail.json
```

Every hook script is written test-first, stays under 150 lines, and imports only the stdlib.
