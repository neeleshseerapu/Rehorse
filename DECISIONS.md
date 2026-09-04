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

- "Orchestrator never edits" is hook-enforced: in `implement`, `guard_edit.py` denies Edit/Write/MultiEdit calls with no `agent_id` (main thread) except paths under `.rehorse/` and `rehorse-reports/`, because `agent_id` is documented as the subagent discriminator and spike 8 confirmed it. SPEC.md "Context management" updated; it no longer calls the rule prose-only.
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
overrides a Stop hook after 8 consecutive blocks. Nothing in SPEC.md contradicted the docs this time.

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

## Before milestone 4: user decisions (2026-09-03)

- **Merge authority moves to `UserPromptSubmit`.** That event fires only for text a human typed (a Skill tool call is a
  PreToolUse), so `authorize.py` minting `~/.rehorse/<merge|discard>-<id>` there proves the user asked. `guard_bash.py`
  lifts its git denials only while such a file exists (`grant.present`), `merge.py`/`discard.py` consume it first
  (`grant.take`), and every command string naming `~/.rehorse/` is denied, so the model has no honest way to read or mint
  one. The old `REHORSE_MERGE_TOKEN` in `state.json` was readable by the model; it is gone.
- A grant is one-shot, dies on the next user prompt (`authorize.py` clears this repo's grants before it looks at the
  prompt) and after one hour, and `merge` is granted only for a task in `report`; `discard` for any non-terminal task.
  A stale or premature grant must not linger to lift denials in a later turn.
- **`testcmd.detect()` reads the target repo only**: its `.venv`/`venv` interpreter by absolute path (`bin/python` or
  `Scripts/python.exe`), else `python3` on PATH; never `sys.executable`, which is whatever runs Rehorse. The worktree has
  no venv of its own (it is gitignored), so the main checkout's interpreter runs with `cd <worktree>`; `python -m pytest`
  puts the cwd first on `sys.path`, which is why the worktree's code wins for flat layouts (src-layout editable installs
  are a known gap, IDEAS.md). Quiet flags are appended (`-q --tb=short`, `--reporter=dot`). `tests/fixtures/repo_with_venv/`
  plus a real pip-less venv created at test time prove the detected interpreter's `sys.prefix` is the fixture's.
- **The orchestrator may run the test command during implement; everything else it delegates.** The Stop hook names
  `cd <worktree> && <test_cmd>` for the main thread, baseline and red runs are recorded from the orchestrator's own run,
  and a test run reads nothing into context but a summary line. Reading source or editing stays delegated.

## Milestone 4: skills, step agent, progress / handoff / report / merge / discard (2026-09-03)

Docs re-fetched before writing (hooks, skills, plugins, sub-agents). What they settled: `UserPromptSubmit` has no matcher
and carries the raw `prompt`; `SubagentStop` uses Stop's `decision`/`reason` schema and its `agent_type` is the
plugin-scoped name (`rehorse:rehorse-step`); a plugin skill's command comes from the frontmatter `name`, so
`skills/rehorse-build/SKILL.md` with `name: build` is `/rehorse:build`; `${CLAUDE_PLUGIN_ROOT}` is substituted in plugin
skill bodies; plugin agents ignore `permissionMode`/`hooks`. SPEC.md amended accordingly (hook table, phase 1 and 6,
context-management paragraph, state example).

- Every new script was written test-first (`test_grant`, `test_authorize`, `test_progress`, `test_handoff`, `test_report`,
  `test_merge_discard`; 235 tests green). `tests/fixtures/` is excluded from collection because fixture repos carry tests
  of their own.
- `state.py new` now creates the worktree and detects the test command in one call and prints the task JSON, so the
  orchestrator starts a task with one command; `testcmd.py set` records a user-supplied command when detection fails.
- `worktree.create` adds `REHORSE_SPEC.md`, `__pycache__/` and `.pytest_cache/` to `.git/info/exclude` (local, shared by
  all worktrees, never committed) so `git add -A` in a step never sweeps them up and the dirty-tree refusal never fires
  on junk.
- `progress.py plan` refuses a dirty worktree and records `tests_sha` (worktree HEAD) at that moment, which is what the
  report's drift check diffs test paths against; so the red tests are committed before the plan exists.
- `progress.py --step-done` acts only for `agent_type` ending in `rehorse-step` (the compact summarizer arrives with
  `agent_type: ""`, spike 9), only in `tests`/`implement`, and blocks in this order: untested edits (names the test
  command), uncommitted tree (names `git add -A && git commit -m "step N: <title>"`), then marks the step done with the
  first two non-empty lines of `last_assistant_message` and the commit sha. It shares `guard_stop.block()` and the same
  8-consecutive-block cap into `needs-attention`, since Claude Code applies that cap to SubagentStop too.
- `report.py` writes the report and PROGRESS.md in the main checkout (the user cannot be asked to look inside
  `.rehorse/`) and commits copies on the rehearsal branch, because the model may not commit outside the worktree and
  the evidence must reach the real branch with the merge. The first dry run showed the flaw: git refuses a merge that
  would overwrite those untracked copies, so `merge.py` removes them first (they are identical; PROGRESS.md is
  re-rendered after the merge). Test added before the fix.
- `handoff.py` prints nothing: PreCompact cannot inject (spike 9); it snapshots `.rehorse/handoff.json` and refreshes
  PROGRESS.md, and `state.py --summary` on `SessionStart(compact)` points the model at PROGRESS.md's `Next:` line.
- The `rehorse-step` agent gets `tools: Read, Edit, Write, MultiEdit, Bash, Grep, Glob` (no `Agent`, no questions);
  `build`/`merge`/`discard` skills carry `disable-model-invocation: true`. Both are prose; the hooks above are the
  guarantees, and README now has a threat-model section saying so.
- The red-before-green gate in `state.advance` (tests -> implement requires a failing run) and the verifier are left to
  milestone 5 as scoped; the report renders `unverified` and `Verifier: not run` until then.

### Evidence: model-free walk of the whole pipeline on a toy repo (2026-09-03)

A throwaway repo (`app.py` with `add`, two tests, its own `.venv` with pytest) was driven through every script with the
JSON Claude Code sends to each hook (`tests/e2e` dry run; `<toy>` stands for the scratch path, `<id>` for
`t-20260903-add-a-subtract-function`). Every line below is verbatim script output.

- `state.py new` detected `test_cmd=<toy>/.venv/bin/python -m pytest -q --tb=short` (the toy's interpreter, not Rehorse's).
- Baseline in the worktree: `REHORSE: recorded test run: 2 passed, 0 failed (edit_seq 1).`
- Tests phase, orchestrator edit of `app.py`: `permissionDecision: deny ... phase tests: only test files may be edited`.
  Subagent's `tests/test_sub.py`: allowed. Red run (collection error, pytest `1 error`): `recorded test run: 0 passed, 1 failed`.
- SubagentStop with the tests uncommitted: `{"decision": "block", "reason": "REHORSE: uncommitted changes in the worktree
  (tests/test_sub.py). Run \`cd <wt> && git add -A && git commit -m \"tests: red for <id>\"\`, then stop again. (block 1 of 7)"}`;
  after the commit the same event printed nothing.
- `progress.py plan "Add sub() to app.py"` -> `Next: run step 1 (Add sub() to app.py) as a rehorse-step subagent.`
- Implement: main-thread edit of `app.py` denied (`the orchestrator does not edit files`), subagent edit of
  `tests/test_sub.py` denied (`test paths are locked`), subagent edit of `app.py` allowed.
- SubagentStop before a test run: `block ... 1 edit(s) since the last recorded test run. Run \`cd <wt> && <toy>/.venv/bin/python -m pytest -q --tb=short\``;
  after the run (`recorded test run: 4 passed, 0 failed (edit_seq 3)`) but before the commit: `block ... git commit -m "step 1: Add sub() to app.py" ... (block 2 of 7)`;
  after the commit: nothing, and PROGRESS.md shows `- [x] 1. Add sub() to app.py — Added sub() to app.py. Tests: 4 passed, 0 failed; nothing left. (commit 0c27495)`.
- PreCompact wrote `handoff.json` (`"phase": "implement", "step": 1, "next_action": "all steps done: \`state.py advance verify\`."`);
  SessionStart(compact) summary: `REHORSE: active task <id>, phase implement, step 1/1, last tests 4 passed, 0 failed. Read rehorse-reports/PROGRESS.md before acting.`
- `git merge rehorse/<id>` without a grant: denied with the `/rehorse:merge` way out; `touch ~/.rehorse/merge-<id>`:
  `the grant directory ~/.rehorse/ is off limits to the model`.
- `report.py` rendered `rehorse-reports/2026-09-03-add-a-subtract-function.md` (banner `GREEN: 4 passed, 0 failed · unverified`;
  tests table baseline 2/0, red 0/1, green 4/0; diff stat `app.py | 4`, `tests/test_sub.py | 9`; drift `none ... (ec33914)`;
  merge/discard commands) and committed it with PROGRESS.md on the branch: `6d9cd67 rehorse: report for <id>` above
  `0c27495 step 1` and `ec33914 tests: red`.
- `merge.py <id>` without a grant: `REHORSE: no user authorization to merge <id>. Only the user grants it, by typing /rehorse:merge <id>.` (exit 1).
  UserPromptSubmit with prompt `/rehorse:merge <id>` minted `-rw------- ~/.rehorse/merge-<id>` and answered
  `REHORSE: the user authorized merge of <id>. Run \`python3 .../scripts/merge.py <id>\` now, report its output, and do nothing else.`;
  `git merge` then passed guard_bash silently. The first `merge.py` run aborted on the untracked-report flaw above
  (main unchanged, worktree kept, grant consumed); the fix is covered by
  `test_merge_succeeds_when_report_and_progress_are_still_untracked_in_the_main_checkout`.

### Live check with real Claude Code sessions (Claude Code 2.1.260, `tests/e2e_live.sh`, 2026-09-03)

The user ran the script; six `claude -p` sessions, all exit 0, empty stderr. Two toy repos under `/tmp/rehorse-e2e`
(`app.py` with `add`, two tests, own `.venv` with pytest). Lines below are from Claude Code's debug logs, the toy repos,
and the session transcripts. Allowed hooks print nothing and leave no log line (as in milestone 3).

- **Run 1, full `/rehorse:build "add a subtract function ..."`**: 12 turns, 90 s, spec -> tests -> implement (1 step) ->
  report, nothing merged. `state.py new` detected `/private/tmp/rehorse-e2e/live1/.venv/bin/python -m pytest -q --tb=short`
  (the toy's interpreter). Hook lines: baseline `recorded test run: 2 passed, 0 failed`; red `PostToolUseFailure ...
  recorded test run: 2 passed, 4 failed`; one run in the main checkout answered `test run ignored: it did not run inside
  the worktree. Run \`cd <wt> && ...\``; green `recorded test run: 7 passed, 0 failed`. Rehearsal branch:
  `e8f9a21 rehorse: report` / `9181c1e step 1: add sub(a, b) to app.py` / `f1d9329 tests: red for <id>` / `72635cb init`.
  The orchestrator's final message described the phases and ended without merging.
- **Run 1b, `/rehorse:merge` typed as the user in a new session**: `Hook UserPromptSubmit ... REHORSE: the user
  authorized merge of t-20260903-add-sub-function. Run \`python3 .../scripts/merge.py t-20260903-add-sub-function\` now,
  report its output, and do nothing else.`; the model ran it once and quoted
  `{"merged": ..., "into": "main", "sha": "e8f9a21...", "report": "rehorse-reports/2026-09-03-add-sub-function.md"}`.
  `main` is now the four commits above, fast-forwarded; worktree and branch gone; `~/.rehorse/` empty (grant consumed).
- **Run 2 (first attempt), two-step task with `--max-turns 30`**: finished the whole rehearsal in 14 turns, so the cap
  never cut it; compaction and resume were proven only in the `report` phase. The script was changed to drive the task
  to `implement` with a two-step plan first (hook JSON piped through the scripts) and cut with `--max-turns 3`.
- **Confirmed**: the orchestrator passed `subagent_type: "rehorse:rehorse-step"` (4 Agent calls in the live1 transcripts),
  SubagentStop carried `agent_type: "rehorse:rehorse-step"`, and every step was marked done by `progress.py --step-done`
  (no block was needed: each agent ran the tests and committed before stopping).
- **Found and fixed**: every hook line says `(edit_seq 0)`. The step agents used Bash and Read only (12 Bash, 6 Read,
  zero Edit/Write in the subagent transcripts) and wrote files with `printf '...' >> app.py`, which never passes through
  `guard_edit.py`: no isolation, no test-path lock, no `edit_seq`, so the Stop guard had nothing to guard. That is a
  shortcut, not an attack, so it belongs to the hooks: `guard_bash.py` now denies shell file writes into the repo or
  worktree (redirection other than to `/dev/null` or another descriptor, `tee`, `cp`, `mv`, `dd`, `truncate`, `install`,
  `patch`, `sed -i`, `perl -i`) with the reason "use the Edit or Write tool on <path>"; writes outside the repo and
  `touch`/`mkdir` stay allowed. 18 tests added before the fix (`test_file_writes_from_bash_are_denied_...`).
- Debug logs are appended across invocations: the user ran the script twice, so `run2*.log` also hold lines from an
  earlier task (`...-to-app`, phase tests); only the later timestamps were used above.

### Second live run, after the Bash-write rule (Claude Code 2.1.260, `tests/e2e_live.sh`, fresh `/tmp/rehorse-e2e`, 2026-09-03)

Six sessions again, all exit 0 and empty stderr except run 2a, whose `is_error: true` is the intended `--max-turns` cut.

- **The Bash-write rule works and the agents adapt.** Run 1 logged three denials, one per phase: the orchestrator's
  `cat > REHORSE_SPEC.md` in spec, the tests-phase agent's write to `tests/test_sub.py`, the implement agent's write to
  `app.py`, each answered `REHORSE: writing files from the shell bypasses the phase lock; use the Edit or Write tool on
  <path> instead (redirects to /dev/null or outside the repo are fine).` After each denial the same agent used Write or
  Edit (subagent transcripts: 1 Write, 1 Edit in live1; 2 Edit in live2), so `edit_seq` finally moved: hook lines read
  `recorded test run: 2 passed, 0 failed (edit_seq 1)`, `3 passed, 5 failed (edit_seq 2)`, `8 passed, 0 failed (edit_seq 3)`.
  Full build: 15 turns, 123 s, green, nothing merged. Run 1b: user-typed `/rehorse:merge` minted the grant, `merge.py`
  fast-forwarded `main` to `b5cd8ce rehorse: report` / `2614ca0 step 1` / `ec3fe7d tests: red` / `b59e534 init`.
- **Compaction mid-implement, proven.** Run 2a started at `phase implement, step 1/2` (SessionStart line), ran step 1
  (`recorded test run: 3 passed, 1 failed (edit_seq 1)`, step marked done, commit 473ec86) and was cut by `--max-turns 3`
  with step 2 open. `/compact --resume` then wrote `handoff.json` with `"phase": "implement", "step": 1, "plan": [done,
  not done], "next_action": "run step 2 (add mul(a, b) to app.py) as a rehorse-step subagent."` and the compact-source
  SessionStart injected `REHORSE: active task t-20260903-add-sub-and-mul, phase implement, step 2/2, last tests 3 passed,
  1 failed. Read rehorse-reports/PROGRESS.md before acting.` Run 2c (the compacted session) reported "task was in the
  implement phase at step 2 of 2", spawned a fresh rehorse-step agent, which was denied a shell write, used Edit,
  ran the tests (`4 passed, 0 failed (edit_seq 2)`), committed 4e6fceb, and the orchestrator advanced to verify and
  rendered the report (drift `none`, banner `GREEN: 4 passed, 0 failed · unverified`). Run 2d (fresh session,
  `/rehorse:build` with no text) read `phase report` and started nothing. No SubagentStop block was needed in either run:
  every agent tested and committed before stopping.

## Before milestone 5: user fixes (2026-09-03)

- **Dependencies are symlinked into the worktree.** A fresh worktree has no `.venv`, `venv`, `node_modules`, `target/`
  or `.tox` (all gitignored), so the baseline run failed on any real repo, including this one. `worktree.create` now
  symlinks each of those that exists in the main checkout and not in the worktree (never copies; a copy would be slow,
  stale, and double the disk), records the names as `linked_deps` in `state.json`, and the report prints them on a
  "Worktree setup" line. The linked names go into `.git/info/exclude` as bare names: the user's own `.venv/` pattern
  matches directories only, and a symlink is a file, so without that `worktree.dirty()` listed the links and the
  step-done refusal would have fired on them. Proven with `tests/fixtures/repo_with_venv/` plus a real venv: the
  worktree's `.venv/bin/python` reports the main checkout's venv as `sys.prefix`.
- **Weak-test flag.** In `red_check`, `on_bash_done.py` computes tests added in the tests phase (red total minus
  baseline total) and how many of those already pass (red passed minus baseline passed, clamped to 0..added), stores
  `weak_tests: N`, and the report renders "N new test(s) passed before implementation and may not test anything."
  The gate itself is unchanged (one failing test still advances), because a step that adds one real test and one
  guard test (say, "add is unchanged") is legitimate; the warning tells the reader which reports to distrust. A
  collection error (`1 error`, nothing else runs) clamps to 0 rather than going negative.
- **MIT license**, copyright 2026 Neelesh Seerapu, referenced at the bottom of README.md, so the repo is usable and
  forkable before the marketplace listing (milestone 8) makes that question unavoidable.
- **README says a test suite is required for now** and names the planned no-tests path (a characterization test first;
  IDEAS.md), instead of implying Rehorse works on any repo. A "Testing Rehorse on your own project" note under
  Contributing asks early users for one small task and an issue with the report attached, because the eval
  (milestones 6 and 7) covers three repos and real projects will find what a toy repo cannot.

## Repo hygiene before milestone 5 (2026-09-03)

- `PROMPT.md` renamed to `SPEC.md` (`git mv`, history kept) with a one-line header saying what it is; every reference
  in README, CLAUDE.md, DECISIONS.md and IDEAS.md updated. "Prompt" described how the file was first used; "spec" is
  what it is.
- Tracked-file audit (`git ls-files`, 68 files): nothing to remove. No scratch files, no e2e output, nothing under
  `.venv/` or `.rehorse/`. `tests/fixtures/repo_with_venv/` stays: it is the fixture behind the venv-detection and
  dependency-symlink tests, not a leftover. `CLAUDE.md` at the plugin root stays: it is development context for this
  repo; the validator's warning only says it is not shipped as plugin context, which is intended. `.gitignore` already
  covered `.venv/`, `.rehorse/`, `__pycache__/`, `.pytest_cache/`; `rehorse-e2e/` added in case the live script is
  pointed inside the repo (its default output is `/tmp/rehorse-e2e`).

## After the Milo run: three changes before milestone 5 (2026-09-03)

Milo is a Swift desktop app with no git history and no test harness. Its Rehorse report (task `t-20260903-journal-tab`,
20 passed after 3 baseline) showed three things the toy repos could not: the initial commit on `main` "also split the model
into Model.swift and added the make test harness", made while no task existed and the hooks were dormant; the red row read
`0 passed, 1 failed` against a baseline of 3, which was a compile failure, not a failing test; and the model's closing
prose ("What you get on merge ... The UI was type-checked and built, not clicked") was the most useful part of the report
and the only part not generated from state.

- **Setup happens inside the rehearsal.** Before any task exists the main checkout may receive exactly one change: if the
  folder is not a git repo, `git init` (with the user's permission) and one as-is commit. `state.py new` runs next, so
  the hooks are live for everything else. When no test command is detectable the task starts in a new optional `setup`
  phase (`[setup →] spec → ...`) in which a `rehorse-step` subagent adds the minimal harness and any refactor needed to
  make the code testable, inside the worktree, committed on the rehearsal branch; `testcmd.py set` records the command
  and `state.py advance spec` continues to the baseline. Isolation is the only rule in `setup`; the step-done hook
  requires the commit (`setup: test harness for <id>`) but no test run, since no command exists yet. The user can now
  discard the harness and the refactor along with the task, which was impossible when they lived in the initial commit.
- **Red by compile failure.** In `red_check`, `on_bash_done.py` records `red_kind: "build_failed"` when the runner output
  matches a compiler/build error (`file:line:col: error:`, `error[E0425]:`, `could not compile`, `[build failed]`,
  `** BUILD FAILED **`, `error TS1234:`) or when fewer tests ran than at baseline (pytest's `1 error` collection failure).
  It still counts as red (the new tests cannot pass before the symbols exist), the weak-test computation is skipped
  (nothing ran, so nothing "passed early"), and the report's red row says "build failed (new tests reference symbols
  that don't exist yet)" instead of misleading counts. A build failure with no summary line at all is now recorded as a
  run of 0/0 with `build_failed: true`, so the Stop guard does not loop on a step whose build is broken. Fixtures:
  `tests/fixtures/runner_output/{swift,cargo}_build_failed.txt` (compiler output shapes, not captured hook payloads)
  and `swift_tests_red.txt`. Swift joined the runners (`Package.swift` -> `swift test`, XCTest `Executed N tests, with
  M failures`), since a Swift project is what surfaced this; `Tests/` is now a test dir, matched by exact name because
  macOS's case-insensitive filesystem made `isdir("Tests")` true whenever `tests/` existed.
