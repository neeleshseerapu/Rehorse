# Rehorse

Auto mode for Claude Code that you can walk away from. Every task rehearses on a git worktree,
must go red-then-green on tests, is checked by an independent verifier subagent, and stops with a
report. Nothing touches your real branch until you run `/rehorse:merge`.

The workflow is enforced by **hooks** (Python scripts Claude Code runs on every tool call), not by
prompt prose. Hook denials hold even when permissions are bypassed.

## Status

Pre-release, built in numbered milestones (see `PROMPT.md`, the spec, and `DECISIONS.md`, the evidence).

| Milestone | State |
|---|---|
| 1. Day-1 spikes (11 assumptions about Claude Code hooks, proven with evidence) | done |
| 2. `scripts/state.py`, `worktree.py`, `testcmd.py` + tests | done |
| 3. Hook scripts (`guard_edit`, `guard_bash`, `on_bash_done`, `guard_stop`) + `hooks.json`, live-checked on a toy repo | done |
| 4. Skills, step agent, `progress.py` / `handoff.py` / `report.py` / `merge.py` / `discard.py`, user-minted merge grants | done: 253 tests; live-checked with real sessions (full build, user-typed merge, forced `/compact`, resume in the same and a fresh session) |
| 5. Red-before-green gate, verifier agent, verdict + drift in the report | next |
| 6–8. Eval harness (`rich`, `fastapi`, `zod`), demo, publish | |

## How a rehearsal runs

```
/rehorse:build "add a subtract function"
```

1. **spec** – `state.py new` creates `.rehorse/worktrees/<id>/` on branch `rehorse/<id>` and detects the test command
   from *your* repo (its `.venv`, pyproject, package.json, Makefile). The orchestrator writes `REHORSE_SPEC.md` there
   and runs the tests once: the baseline.
2. **tests** – a fresh `rehorse-step` subagent writes failing tests from the spec. Only test paths are editable. The
   run is recorded as `red_check`; at least one test must fail.
3. **implement** – the orchestrator writes a 1–6 step plan (`progress.py plan`); each step runs as a fresh subagent
   that may edit implementation files only, must run the tests, and must commit. The SubagentStop hook refuses to close
   a step otherwise, naming the exact command. The orchestrator reads only two-line summaries.
4. **verify** – the independent verifier (milestone 5).
5. **report** – `report.py` writes `rehorse-reports/<date>-<slug>.md` and `PROGRESS.md`, commits copies on the
   rehearsal branch, and the turn ends. You read the report and type `/rehorse:merge <id>` or `/rehorse:discard <id>`.

`/rehorse:status` shows PROGRESS.md; a new session, a resumed one, or one that just compacted gets a one-line state
summary injected and continues from PROGRESS.md's **Next:** line.

## Layout

```
.claude-plugin/plugin.json   manifest (name `rehorse`, so skills are /rehorse:<name>)
skills/rehorse-{build,status,merge,discard}/SKILL.md   the four commands (build/merge/discard are user-invoked only)
agents/rehorse-step.md       the step worker: one tests-phase or implement step per fresh subagent
hooks/hooks.json             wires events to scripts, exec form: {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/..."]}
scripts/state.py             .rehorse/state.json: the single source of truth; phase machine; SessionStart summary; `new` bootstraps a task
scripts/worktree.py          create / list / diff / dirty / remove rehearsal worktrees; local excludes for the spec file and test caches
scripts/testcmd.py           detect the test command from the target repo; recognise test runs, test paths, pass/fail counts
scripts/guard_edit.py        PreToolUse Edit|Write|MultiEdit: worktree isolation, phase path lock, orchestrator rule, edit_seq
scripts/guard_bash.py        PreToolUse Bash: no branch mutation without a user grant, no rm -rf on repo/.rehorse, ~/.rehorse off limits
scripts/on_bash_done.py      PostToolUse + PostToolUseFailure Bash: record real test runs (baseline / red_check / last_test_run)
scripts/guard_stop.py        Stop: in implement, block the turn until tests ran after the last edit (8-block cap -> needs-attention)
scripts/authorize.py         UserPromptSubmit: mint the one-shot merge/discard grant when *you* type the command
scripts/grant.py             ~/.rehorse/<action>-<id> grant files: mint / present / take / clear
scripts/progress.py          PROGRESS.md regenerated from state; `plan`/`add`; SubagentStop --step-done (tests ran + committed, else refuse)
scripts/handoff.py           PreCompact: .rehorse/handoff.json snapshot + PROGRESS.md refresh
scripts/report.py            the one-screen rehearsal report; advances verify -> report; commits evidence on the branch
scripts/merge.py, discard.py the only code paths that touch your branch; both consume a grant first
tests/                       pytest for every script; tests/fixtures/hook_inputs/ are real hook payloads; tests/e2e_live.sh drives real sessions
```

## What the hooks guarantee (and what they do not)

While a task is active (any phase before `merged`/`discarded`), regardless of permission mode:

- **Isolation.** Edit/Write/MultiEdit outside `.rehorse/worktrees/<task>/` is denied, except `rehorse-reports/` (the
  evidence trail). `.rehorse/state.json` is never edited directly; phases move only through `scripts/state.py`.
- **Test-path lock.** Phase `tests`: only test files may be edited. Phase `implement`: test files are locked, and
  the main thread (no `agent_id` in the hook input) may not edit at all; step subagents do the editing. Writing files
  from Bash (`>>`, `tee`, `cp`, `mv`, `sed -i` ... into the repo or worktree) is denied so the lock cannot be sidestepped;
  the reason says to use Edit or Write.
- **No branch mutation.** `git merge/rebase/pull/push/checkout/switch`, `reset --hard`, branch delete/move and
  `git worktree` changes are denied everywhere unless you hold a grant (below); `git commit` is denied outside the
  worktree; `rm -rf` on the repo root, its parents, `.rehorse/` or a worktree root is denied; `--no-verify` and
  `core.hooksPath` are denied.
- **Merge authority is yours.** `UserPromptSubmit` fires only for text a human typed. When you type
  `/rehorse:merge <id>` (task in `report`) or `/rehorse:discard <id>`, `authorize.py` writes a one-shot grant to
  `~/.rehorse/<action>-<id>`, outside the repo. `merge.py`/`discard.py` consume it; without it they refuse. Grants are
  cleared on your next prompt and expire after an hour. Any command that names `~/.rehorse/` is denied.
- **Red before green, evidence-based.** A test run is recorded only when the command runs the task's runner inside
  the worktree and its output parses to the runner's own summary line. `--collect-only`, `--version` and grep hits
  do not count. A baseline of 0 tests sends the task to `needs-attention`.
- **No stopping with untested edits.** In implement the Stop hook blocks, naming the exact command, until a run is
  recorded after the last edit. A step subagent additionally cannot stop with an uncommitted worktree: the
  SubagentStop hook names the exact `git add -A && git commit` command. After 8 consecutive blocks the task drops to
  `needs-attention` instead of ending silently.

Every denial says what the model may do instead.

### Threat model

Hooks stop **shortcuts**, not an **adversarial model**.

- What they stop: the model merging or pushing "to save you a step", editing tests to make them pass, editing your
  checkout instead of the worktree, stopping before tests ran, closing a step with uncommitted work, minting its own
  merge authorization, and any of the above under `--dangerously-skip-permissions`, because hooks run either way.
- What they do not stop: a model that deliberately evades them. `guard_bash.py` is a token check, not a shell parser;
  Bash can run arbitrary programs, and a program can write any file the user can, including `~/.rehorse/`. The
  grant design makes the honest path (`/rehorse:merge`) the only path the hooks describe, and makes the dishonest path
  require deliberate obfuscation, which is the point: an accident cannot merge, only intent can.
- Prose-only rules: which files a step may touch, keeping the orchestrator from reading source (hooks cannot tell a
  Read in the main thread from one in a subagent), and step ordering. Everything in the list above is hook-enforced.
- Rehorse never widens permissions: an allowed call prints nothing, so your own permission prompts still apply in
  default mode.

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install pytest   # dev only; nothing is needed at hook time
.venv/bin/python -m pytest tests/ -q

# exercise a script the way Claude Code will: JSON on stdin, JSON on stdout
python3 scripts/state.py --summary < tests/fixtures/hook_inputs/sessionstart_resume.json
python3 scripts/testcmd.py parse   < tests/fixtures/hook_inputs/posttoolusefailure_bash_pytest_fail.json
python3 scripts/guard_bash.py      < tests/fixtures/hook_inputs/pretooluse_bash_git_merge.json   # dormant: prints nothing

# load the plugin from this checkout in any repo; --debug-file records which hooks matched, exit codes and output
claude --plugin-dir /path/to/Rehorse --debug-file /tmp/hooks.log
claude plugin validate .

# real sessions end to end on two toy repos (full build + merge; compaction mid-implement + resume)
bash tests/e2e_live.sh /tmp/rehorse-e2e
```

Every hook script is written test-first, stays under 150 lines, and imports only the stdlib. Runtime dependencies:
Python 3 and git. Nothing else, ever, at hook time.
