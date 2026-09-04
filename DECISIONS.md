# DECISIONS.md

One line per decision, with the reason. Newest at the bottom.

## Milestone 1: Day-1 spikes (2026-09-03)

Environment: Claude Code 2.1.259, macOS 25.3.0 (Darwin, Apple Silicon), Python 3.13.5, git 2.50.1.
Method: a throwaway plugin (`plugin.json` + one skill + one Python hook script wired to every event) loaded with
`claude --plugin-dir <path> -p "<prompt>" --dangerously-skip-permissions --output-format json`, run inside a toy git repo with
a two-test pytest suite and a separate vitest project. The hook script appended its full stdin to a JSONL log and returned
decisions per the docs. Raw hook inputs from these runs are saved under `tests/fixtures/hook_inputs/`.

| # | Assumption | Result | Evidence |
|---|---|---|---|
| 1 | Local plugin loads; skill invocable as `/rehorse:status` | PASS | `claude -p "/rehorse:status" --plugin-dir ./plugin` returned the skill's sentinel string `REHORSE_SPIKE_STATUS_OK`. `claude plugin validate` passed (warning: no author). |
| 2 | Hook scripts resolve by path from the plugin | PASS (macOS only) | `hooks.json` exec form `{"command":"python3","args":["${CLAUDE_PLUGIN_ROOT}/scripts/spike_hook.py"]}` fired for every event; `CLAUDE_PLUGIN_ROOT` env var was set to the `--plugin-dir` path. Linux untested; exec form uses no shell, so no bash-isms to break. |
| 3 | PreToolUse can deny Edit/Write with a reason the model adapts to | PASS | Deny on `*.lock` via `hookSpecificOutput.permissionDecision: "deny"`. Model's final answer quoted the reason verbatim, did not retry, and completed the allowed second edit. File unchanged. |
| 4 | PreToolUse can deny a Bash command by pattern | PASS | `git merge some-branch` denied with reason; model quoted it, did not retry, ran the allowed `git status` next. |
| 5 | Stop hook can block the turn; reason reaches the model | PASS | Returned root-level `{"decision":"block","reason":"... touch <sentinel>"}`. Model ran the exact `touch`, then the second Stop fired with `stop_hook_active: true` and was allowed. Transcript shows the reason as "Stop hook feedback". |
| 6 | PostToolUse for Bash receives command + stdout; pytest/vitest counts parseable | PASS, with a catch | Passing run: `PostToolUse.tool_response = {stdout, stderr, interrupted, isImage, noOutputExpected}`, stdout ends `2 passed in 0.01s`. **Failing run (exit code 1) fires `PostToolUseFailure` instead, never `PostToolUse`.** Its `error` field is `"Exit code 1\n<stdout+stderr interleaved>"`, ending `1 failed, 2 passed in 0.01s` (pytest) or `Tests  1 failed | 1 passed (2)` (vitest). Both are regex-parseable. |
| 7 | `git worktree` works from stdlib Python; hook paths distinguish inside/outside worktree | PASS | `subprocess.run(["git","worktree","add"/"remove"])`, `git diff --stat base..HEAD` in the worktree, and `git branch -D` all exit 0; main checkout untouched. Every `tool_input.file_path` in hook input was absolute (`/private/tmp/.../toy/app.lock`), and `cwd` inside a worktree was the worktree path. Prefix comparison against the resolved worktree path is sufficient. |
| 8 | Subagent tool calls pass through PreToolUse; SubagentStop identifiable | PASS | Subagent's Edit on `app.lock` arrived with `agent_id: "ae512f99..."`, `agent_type: "general-purpose"` and was denied; subagent reported the reason verbatim. `SubagentStart` and `SubagentStop` fired with the same `agent_id` plus `last_assistant_message` and `agent_transcript_path`. |
| 9 | PreCompact fires; injected text is present after compaction | PASS, via a different hook | `claude -p "/compact" --resume <id>` fired `PreCompact` (trigger `manual`), then `SessionStart` with `source: "compact"`, then `PostCompact`. PreCompact has **no** `additionalContext` output in the docs; the SessionStart(compact) hook's injection appears in the transcript as a `hook_success` attachment right after the `compact_boundary`, and the compact summary itself also restated it. |
| 10 | SessionStart injection works on resume | PASS | `claude -p --resume <id> "What is the active Rehorse task id?"` answered `t-test`, the value injected by the hook; log shows `source: "resume"`. |
| 11 | `claude -p` runs with the plugin inside a worktree and exits cleanly | PASS | From `.rehorse/worktrees/t-eleven/`, `/rehorse:status` returned the sentinel, exit 0, hook `cwd` was the worktree path. |

### Decisions taken from the spikes

- Hook scripts use exec form (`"command": "python3", "args": [...]`) in `hooks.json`: no shell, so identical on macOS/Linux/Windows and no quoting issues. (Spike 2)
- `on_bash_done.py` is wired to **both** `PostToolUse` and `PostToolUseFailure` for Bash, and parses `tool_response.stdout` or `error` respectively; a red test run is a failed tool call. Without this, `red_check` could never be recorded. (Spike 6)
- Compaction survival is implemented by `handoff.py` on `PreCompact` (write `.rehorse/handoff.json`) plus `state.py --summary` on `SessionStart` for **all** sources (`startup|resume|clear|compact`), since only SessionStart can inject context. The spec's hook table is amended accordingly. (Spike 9)
- `progress.py --step-done` on `SubagentStop` must filter by `agent_type`: compaction itself runs a summarizer that fires `SubagentStop` with an empty `agent_type`, and unrelated subagents (Explore, verifier) also fire it. Use a dedicated step-agent name in `agents/` and match on it. (Spikes 8, 9)
- `guard_stop.py` must honor `stop_hook_active` and Claude Code's cap of 8 consecutive blocks; a block reason must name the exact command to run, which the model followed reliably. (Spike 5)
- Hook denials hold even under `--dangerously-skip-permissions`; permission mode is not a bypass for Rehorse's guarantees. This should be stated in the README. (Spikes 3, 4)
- Non-interactive runs pass `< /dev/null`; otherwise `claude -p` waits 3 s for stdin. `run_eval.py` does this. (Spike 1)
- Stop/SubagentStop output is root-level `decision`/`reason`, as the spec said; the softer `hookSpecificOutput.additionalContext` form also continues the turn but is labeled as feedback rather than an error. Rehorse uses `decision: "block"`. (Spike 5)

### Spec statement contradicted by the docs and the evidence (resolved below)

- The spec says "hooks cannot reliably tell a subagent's tool call from the main session's", so the orchestrator-never-edits rule was to be prose-only. Hook input now carries `agent_id` only when the call comes from a subagent (docs: "Use this to distinguish subagent hook calls from main-thread calls"; spike 8 confirmed). `guard_edit.py` could therefore deny main-thread edits during `implement` and make the rule hook-enforced. Resolved: see milestone 2 decisions.

### Not verified

- Linux path resolution for `${CLAUDE_PLUGIN_ROOT}` (no Linux machine in this session).
- Auto-triggered compaction (`trigger: "auto"`); only manual `/compact` was exercised. Same hooks fire per the docs.

## Before milestone 2: user decisions (2026-09-03)

- "Orchestrator never edits" is hook-enforced: in `implement`, `guard_edit.py` denies Edit/Write/MultiEdit calls with no `agent_id` (main thread) except paths under `.rehorse/` and `rehorse-reports/`, because `agent_id` is documented as the subagent discriminator and spike 8 confirmed it. PROMPT.md "Context management" updated; it no longer calls the rule prose-only.
- `guard_stop.py` tracks consecutive blocks in `state.json` (`stop_blocks`, reset on any allowed stop); on the 8th block it sets the phase to `needs-attention` with the reason, allows the stop, and `report.py` renders that state as the banner, because Claude Code caps consecutive Stop blocks at 8 and silently allowing the 9th would hide an unfinished task.
- `on_bash_done.py` stays wired to both `PostToolUse` and `PostToolUseFailure` for Bash (spike 6 decision confirmed).
- `needs-attention` is a phase in `state.py`: reachable from any non-terminal phase, records `{reason, prior_phase}` in `attention`, and exits only back to `prior_phase` (user-driven resume) or to `discarded`; `merged` is reachable only from `report`, `discarded` from any non-terminal phase.
- Dev-only pytest lives in `./.venv` (`python3 -m venv .venv && .venv/bin/pip install pytest`); nothing at hook time imports it, so the zero-cost / stdlib-only constraint is untouched.

## Milestone 2: state.py, worktree.py, testcmd.py (2026-09-03)

- `state.find_root()` locates the main checkout by path alone (a `.rehorse` component means "inside a worktree, root is its parent"; otherwise the nearest `.git`), so the SessionStart hook never shells out to git.
- `state.save()` writes via a temp file and `os.replace`, because a hook killed mid-write must never leave a half-written state file for the next hook to read.
- `worktree.diff()` is `base_sha..HEAD` only (committed work), per spec; `worktree.dirty()` exists so the report can flag uncommitted files rather than silently ignoring them.
- `testcmd.is_test_path()` matches test directories *and* filename patterns (`test_*.py`, `*_test.py`, `*.test.ts`, `conftest.py`, `__tests__/`), because a test-path lock keyed on `tests/` alone would let an implementer edit `src/foo_test.py`.
- `testcmd.is_test_command()` matches on the runner token, not the exact string, because the spikes showed commands like `/venv/bin/python -m pytest -q` and `cd x && npx vitest run`.
- `testcmd.parse_counts()` reads only the runner's own summary line (pytest `... in 0.01s`, vitest/jest `Tests ...`, cargo `test result:`) and counts errors as failures; `Test Files` lines and `FAILED` detail lines are ignored.
- `state.py` stays at 150 lines because it runs as the SessionStart hook; other helpers get no such cap but keep the same style.

## Before milestone 3: user decisions (2026-09-03)

- Steps must end in a commit: `progress.py --step-done` refuses to mark a step complete while `worktree.dirty()` is non-empty, with a reason naming the exact git command, because the verifier and the report see only `base_sha..HEAD` and uncommitted work would be invisible to both. (Enforced when `progress.py` is written in milestone 4; spec amended now.)
- Zero collected tests is a failure: `red_check` fails if the run parses no summary line or reports 0 tests, and a 0-test baseline sends the task to `needs-attention`, because "0 failed" from a suite that never ran would satisfy red-then-green vacuously. `testcmd.parse_counts()` therefore returns `{passed: 0, failed: 0}` for pytest's `no tests ran in Ns` line (a real runner summary) instead of `None`, so the hook can see the difference between "the suite is empty" and "this was not a test run".
- `on_bash_done.py` records a test run only when `parse_counts()` returns a summary; `--collect-only`, `--version`, and grep-style matches on the runner name never count, because a recorded run is what releases the Stop guard and it must mean tests actually executed.

## Milestone 3: guard_edit.py, guard_bash.py, on_bash_done.py, guard_stop.py, hooks.json (2026-09-03)

Docs re-fetched before writing (hooks reference, plugins). They confirm the spike findings: PreToolUse answers with
`hookSpecificOutput.permissionDecision`; PostToolUse, PostToolUseFailure and Stop use top-level `decision`/`reason` and
`hookSpecificOutput.additionalContext`; PostToolUse input carries `tool_response`, PostToolUseFailure carries `error`; Claude Code
overrides a Stop hook after 8 consecutive blocks. Nothing in PROMPT.md contradicted the docs this time.

- Every hook is written test-first (`tests/test_guard_*.py`, `test_on_bash_done.py`; 106 red, then green) against the captured
  inputs in `tests/fixtures/hook_inputs/` with `cwd`/`file_path`/`command` overridden to point at a throwaway repo, so the
  payload shapes are real and only the paths are synthetic.
- An allowed call prints nothing. Printing `permissionDecision: "allow"` would skip the user's own permission prompt in
  default mode, so Rehorse only ever narrows what the model may do, never widens it.
- `state.active(cwd)` is the one definition of "dormant": no repo, or no active task, and every hook returns silently. Without
  an active task Rehorse must not interfere with ordinary Claude Code use of the same machine.
- `guard_edit.py` denies `.rehorse/` outside worktrees (the spec listed it as an orchestrator exception): `state.json` is
  changed only through `state.py`, and nothing else under `.rehorse/` is model-written. `rehorse-reports/` stays writable from
  either checkout and does not bump `edit_seq`, because a report edit is not code and must not demand a test run.
- `edit_seq` is bumped in PreToolUse, before the edit runs, so an Edit that then fails (old_string missing) still counts.
  Conservative by design: a spurious "run tests" beats a missed one.
- `guard_bash.py` tokenizes with `shlex(punctuation_chars=True)` and recurses into `-c "..."`/`eval` strings; a first draft that
  split the raw string on `&&` broke on `sh -c "cd wt && git push"`. It also denies `git commit` outside the worktree (the
  spec's "anything writing to the real branch"), `git pull` (fetch + merge), branch delete/move, `git worktree` changes, and
  `core.hooksPath` overrides next to `--no-verify`. `rm -rf` protection covers the repo root, its parents, `.rehorse/`,
  `worktrees/` and worktree roots, but not files inside a worktree (build outputs must stay deletable).
- The merge token is accepted from the hook's environment or as `REHORSE_MERGE_TOKEN=<tok> git ...` inside the command,
  because a hook inherits Claude Code's environment, not the Bash tool's, so `merge.py` cannot set an env var the hook sees.
  It never lifts the `rm -rf` rule.
- `on_bash_done.py` also requires the run to happen inside the worktree (`cwd` after a leading `cd`): a test run in the main
  checkout tests the wrong tree and would falsely release the Stop guard. It sets `baseline` in `spec` and `red_check` in
  `tests` itself, from runner output, rather than trusting a skill to copy numbers into state.
- `guard_stop.py` blocks only in `implement`, with the exact `cd <worktree> && <test_cmd>`; blocks 1-7 block, the 8th moves
  the task to `needs-attention` with a `systemMessage` so the walk-away user sees it.
- `hooks.json` wires SessionStart to `state.py --summary` now (it exists); PreCompact and SubagentStop wait for `handoff.py` and
  `progress.py` in milestone 4. Every hook has `timeout: 30`.

### Live check (Claude Code 2.1.260, `claude --plugin-dir <Rehorse> --debug-file <log> -p ... --dangerously-skip-permissions`)

Toy repo (`app.py` + two pytest tests), task `t-20260903-add-subtract-function` created with `state.py new` and `worktree.py
create`, advanced to `implement`. Hook lines below are from Claude Code's own debug log; `<toy>` stands for the scratch path.

1. Denied edit outside the worktree (main checkout `app.py`); the model quoted the reason and stopped, file unchanged.
   `Hook PreToolUse (python3 ${CLAUDE_PLUGIN_ROOT}/scripts/guard_edit.py) returned permissionDecision: deny (reason: REHORSE: edits outside the active worktree are denied. Task t-20260903-add-subtract-function rehearses in <toy>/.rehorse/worktrees/t-20260903-add-subtract-function; edit <toy>/.rehorse/worktrees/t-20260903-add-subtract-function/app.py instead.)`
2. Denied test-path edit during implement (`<wt>/tests/test_app.py`); the model quoted the reason and stopped, file unchanged.
   `Hook PreToolUse (python3 ${CLAUDE_PLUGIN_ROOT}/scripts/guard_edit.py) returned permissionDecision: deny (reason: REHORSE: phase implement: test paths are locked (tests/test_app.py). Edit implementation files only; if a test is wrong, say so in your step summary instead of changing it.)`
3. Denied `git merge rehorse/<id>` in the main checkout; the model quoted the reason, ran the allowed `git status --short`; `main` still at `9c2250f init`.
   `Hook PreToolUse (python3 ${CLAUDE_PLUGIN_ROOT}/scripts/guard_bash.py) returned permissionDecision: deny (reason: REHORSE: \`git merge\` is denied while task t-20260903-add-subtract-function is rehearsing: only /rehorse:merge and /rehorse:discard, run by the user, touch the real branch. Work inside <wt> and commit there; to undo a file use \`git restore <file>\`.)`
4. Blocked stop that releases after a test run. A general-purpose subagent edited `<wt>/app.py` (allowed: `agent_id` present, non-test path; `edit_seq` 0 -> 1) without running tests; the main thread's Stop was blocked, it ran the named command once, the run was recorded, and the next Stop was allowed (`stop_blocks` back to 0). Final answer: "Tests ran as the Stop hook requested. Result: 2 passed, 0 failed."
   `Hook Stop (Stop) success: {"decision": "block", "reason": "REHORSE: 1 edit(s) since the last recorded test run (block 1 of 7). Run this exact command before stopping: cd <wt> && /Users/neelesh/Desktop/Rehorse/.venv/bin/python -m pytest -q"}`
   `Hook PostToolUse (python3 ${CLAUDE_PLUGIN_ROOT}/scripts/on_bash_done.py) provided additionalContext (60 chars)` = `REHORSE: recorded test run: 2 passed, 0 failed (edit_seq 1).`
   state.json after: `phase implement, edit_seq 1, stop_blocks 0, last_test_run {passed 2, failed 0, after_edit_seq 1, command "cd <wt> && ... -m pytest -q"}`; `<wt>/app.py` contains `sub`.

Also observed: the SessionStart summary was injected in every session (`Hook SessionStart (... state.py --summary) provided
additionalContext (119 chars)`), and in scenario 1 the model noted that `rehorse-reports/PROGRESS.md`, which the summary tells it
to read, does not exist yet (it arrives with `progress.py` in milestone 4). Allowed hooks print nothing, so they leave no log line.
