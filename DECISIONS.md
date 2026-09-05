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
- **"Try it yourself" and a labelled Summary.** The report now ends its evidence with the worktree path, `cd` into it,
  the exact test command, and how to run the project when `testcmd.run_cmd()` can tell (package.json `dev`/`start`,
  Makefile `run`, `build.sh`, `cargo run`, `go run .`, `swift run`, or the first run-looking line in a README code
  block; otherwise it says so and shows the path), because Milo's report told the user what changed but not where to
  go and what to type to see it. The orchestrator may pass `report.py --summary "..."`; it renders right after the
  banner under a line saying it was written by the model at report time. Milo's most useful paragraphs ("The UI was
  type-checked and built, not clicked") were exactly this kind of text, and they were indistinguishable from the
  generated parts; now the reader knows which sentences came from state and which from the model.

## Milestone 5: red gate, verifier agent, verify round-trip (2026-09-04)

Docs re-fetched before writing (hooks, sub-agents, plugins). Confirmed: Stop and SubagentStop answer with top-level
`decision: "block"` / `reason` (plus optional `hookSpecificOutput.additionalContext`, which keeps the subagent running, so it is
not used on an accepted stop); SubagentStop `matcher` filters on `agent_type`, including plugin-scoped names
(`^my-plugin:reviewer$`); plugin agents ignore `permissionMode` and `hooks`. Nothing contradicted SPEC.md.

- **Red gate moved into `state.advance`** (chunk 1). `tests -> implement` now raises unless `red_check` has at least one failure
  or `red_kind` is `build_failed`; the message says which of "no red run", "0 tests ran", "nothing failed" it is and what to do.
  Until now the gate was prose in the build skill ("at least one test must fail") and `state.py advance implement` accepted
  anything. The weak-test flag and `red_kind: build_failed` were already implemented and rendered (milestone 4 fixes); the
  Swift and Cargo compiler-output fixtures existed, and `swift_tests_red.txt` (a compiled-language red that *fails tests*
  rather than the build) is now also pushed through `on_bash_done.py` to prove it records `red_kind: "tests"` with counts.
  The conftest phase walker sets a failing `red_check` when a test asks for a phase past `tests` and gave none.
- **The verifier's input is fixed by code, not by the orchestrator** (chunk 2). `verify.py brief` writes
  `.rehorse/verify/<id>-round<n>.md` (spec, `base_sha..HEAD` diff capped at 200 kB, last test output, and from round 2 the
  verifier's own earlier findings) and prints the subagent prompt, which the build skill passes through verbatim. The
  orchestrator therefore never holds the diff in its context and cannot slip step summaries or its own reading of the code
  into the verifier's prompt. The agent's prose forbids reading `rehorse-reports/`, `PROGRESS.md` and `.rehorse/`; there is
  no PreToolUse hook on Read, so that part is prose-guided and README says so.
- **The verdict is recorded by a hook, never copied by the model.** `verify.py --verdict` runs on SubagentStop (matched
  on `rehorse-verifier` in `hooks.json`, and re-checked in the script, since the step-done hook proved the compact summarizer
  and other agents fire the same event). It blocks the verifier's stop, with the exact command, until the test command ran
  inside the worktree after its last edit (`verify_run`, recorded separately by `on_bash_done.py` in phase `verify`), the
  worktree is committed (`verify: round N tests for <id>`), and the reply ends with a ```json block whose `verdict` is
  pass|concerns|fail; findings, coverage and tests_added are normalised with defaults. Same 8-block cap into
  `needs-attention` as the other stop hooks.
- **`verify -> report` is gated in `state.advance` on a recorded verdict**, any verdict. Before this, "checked by an
  independent verifier" was prose: `state.py advance report` and `report.py` accepted a task nobody had verified. A `fail`
  still reaches the report (the user decides at merge time); what cannot happen is a report with no verdict.
- **In phase `verify` the edit lock is one file.** `guard_edit.py` allows only a test path whose basename is
  `rehorse_verify_<id>` plus the runner's suffix. The spec said `tests/rehorse_verify_<task-id>.<ext>`; pytest does not
  collect a file that does not match `test_*.py`, so `testcmd.verify_file` names it per runner: `tests/test_rehorse_verify_<id>.py`
  (pytest, checked: pytest collects the hyphenated task id), `<dir>/rehorse_verify_<id>.test.ts|js` (vitest/jest, `.ts` when a
  tsconfig exists), `tests/rehorse_verify_<id>.rs`, `rehorse_verify_<id>_test.go`, `Tests/<target>/rehorse_verify_<id>.swift`.
  The denial reason names that exact path.
- The verifier agent gets `Read, Write, Edit, Bash, Grep, Glob` (it must read the worktree to write tests that import
  the right things) and no `Agent`; `model: inherit`.
- **Report** (chunk 3). The banner's `unverified` becomes `verifier PASS` / `verifier CONCERNS (n findings)`; a `fail`
  verdict leads the banner (`FAIL: verifier found n issues · tests N passed, M failed`) so it is the first thing read, and
  the merge command is still offered below it, since a fail informs the user's decision rather than making it. The
  Verifier section (after Changes) shows the verdict with `round N of 3`, the verifier's own run, the tests it added, the
  findings as `[severity] file:line description`, the coverage table (criterion / evidence / ref), and for round 2+ what each
  earlier round found. More than five findings go to `rehorse-reports/verifier/<same-name>.md`, linked from the report and
  committed with it (the spec's "when they exceed one screen"). "Try it yourself" ends with the criteria whose evidence is
  `none` or `build_only`, labelled as what to try by hand. The drift check ignores `rehorse_verify_*` files, which are the
  verifier's and always land after `tests_sha`. `PROGRESS.md` carries one `Verifier:` line per round.
- **The verifier's SubagentStop is never a step-done** (chunk 4). `progress.py --step-done` acts only on `agent_type` ending
  in `rehorse-step` (unchanged, now tested against `rehorse:rehorse-verifier`), and `verify.py --verdict` is the second
  SubagentStop entry in `hooks.json`, with matcher `rehorse-verifier` (the docs' agent-name matching; first use of a
  SubagentStop matcher here, so the live check must show it firing) and the same name check inside the script. Both hooks
  run on every SubagentStop and each answers only for its own agent, so a verifier stop can never close a plan step and a
  step stop can never record a verdict.
- **Verify round-trip** (chunk 5). In `verify.py --verdict`, a `fail` verdict or a failing verifier run (`verify_run.failed > 0`)
  sends the task back to `implement`: `state.advance(verify -> implement)`, now a legal edge, archives the verdict into
  `verify_history` and clears `verifier`/`verify_run` (so the next round must earn a new verdict and `report.py` cannot
  reuse the old one), and the hook appends plan steps: one `Fix (verifier round N): <description> (<file>:<line>)` per
  `high` finding (every finding when the verdict is `fail` and none is high), one `Make the verifier's tests pass: <file>
  (<k> failing)` when its run failed, and a generic step when a `fail` came with nothing else. The step pointer already
  sits at the end of the old plan, so `Next:` names the first new step. The verifier's file is under a test path, so
  `guard_edit.py` locks it in `implement` with no new rule. `verify_round` counts recorded verdicts; the report shows
  `round N of 3` and, from round 2, what each earlier round found; the brief carries the earlier findings so the verifier
  checks them.
- **Two round-trips, then the user.** "Maximum two rounds; a third failure sets needs-attention" is read as: failures in
  rounds 1 and 2 return to implement, a failing round 3 sets `needs-attention` with the reason `verifier failed 3 rounds;
  round 3 found: ...`, the verdict kept (not archived) so `report.py` renders the findings under the NEEDS ATTENTION
  banner. `/rehorse:build resume` then puts the task back in `verify` where the recorded verdict makes `Next:` say
  `report.py`, which renders the FAIL banner and offers merge/discard: a fail never blocks the user, it stops the model.
- **`CONTRADICTS SPEC:`** in a step reply (any line starting with it) makes `progress.py --step-done` move the task to
  `needs-attention` with that line as the reason, before the test-run and commit checks, leaving the step open. This is
  the implementer's only honest exit when a locked test (the verifier's included) disagrees with the spec; without it the
  round-trip could loop on a wrong verifier test. `guard_stop.attention()` is the shared exit used by the 8-block cap,
  this rule, and the third verifier failure.
- `progress.goal` moved to `worktree.spec_goal` (worktree.py has no line cap) to keep `progress.py` under 150 lines with
  the new rule; `state.py` gained the transition and its archive step at 150 lines exactly.

### Live check (Claude Code 2.1.260, `tests/e2e_live.sh <dir> 3`, 2026-09-04)

Run 3 drives a toy repo to `verify` without a model: the spec says `divide(1, 0)` raises `ValueError("division by
zero")`, the tests-phase test covers only `divide(6, 3) == 2`, and the implementation is a bare `return a / b`. One
`claude -p '/rehorse:build'` session then has to run the verifier, go back to implement on its findings, verify again
and report.

- **First attempt: the verifier caught it, the hook never ran.** The orchestrator resumed at `verify`, ran `verify.py
  brief`, spawned `rehorse:rehorse-verifier` with the printed prompt. The verifier's shell write was denied by the
  Bash-write rule, it used Write, added ten tests in `tests/test_rehorse_verify_<id>.py` (six fail: `ZeroDivisionError`
  instead of `ValueError`, message, float and negative zero), ran the suite (`PostToolUseFailure ... recorded test run: 8
  passed, 6 failed (edit_seq 2)`), committed `verify: round 1 tests for <id>`, and ended with a well-formed `fail` verdict
  mapping both criteria to its tests. State stayed `verifier: null`; the orchestrator ran it a second time, same result,
  then stopped and explained (correctly) that the hook had not fired and that it may not copy a verdict. Cause: the
  SubagentStop entry used `"matcher": "rehorse-verifier"`; the docs' matcher table says a string of only letters, digits,
  `-` and `_` is compared as an **exact string**, and a plugin agent's `agent_type` is the scoped `rehorse:rehorse-verifier`
  (the debug log shows one hook-output line per verifier stop, the silent step hook, not two). The docs even say the colon
  puts a scoped name on the regex path and to anchor it. Fixed to `^rehorse:rehorse-verifier$`; the `hooks.json` test now
  asserts the matcher is a regex that matches the scoped verifier type and not the step type. Replaying the verifier's real
  final message through `verify.py --verdict` recorded `FAIL, 2 findings; its run 8 passed, 6 failed` and returned the
  task to implement with `Fix (verifier round 1): ...` and `Make the verifier's tests pass: ...` steps, so the script was
  right and the wiring was wrong. This is what the live check is for: the summary of the docs I had read showed the
  anchored example, and I chose a looser string that landed on the exact-match path.
- **Second attempt, after the matcher fix: the whole round-trip, live.** One session, 13 turns, 324 s, exit 0. Hook lines
  in order: the verifier's shell write denied (Bash-write rule), `PostToolUseFailure ... recorded test run: 10 passed, 6
  failed (edit_seq 2)`, then `Hook SubagentStop ... {"systemMessage": "REHORSE: verifier round 1: FAIL, 3 finding(s); its
  run: 10 passed, 6 failed. Back to implement with 2 new step(s); round 2 of 3 follows once they are green."}`. The
  orchestrator read PROGRESS.md, spawned a `rehorse-step` for step 2 (`Fix (verifier round 1): divide() is a bare
  return a / b; divide(1, 0) raises ZeroDivisionError ... (app.py:6)`), which wrapped the division and re-raised
  `ValueError("division by zero")` (`16 passed, 0 failed (edit_seq 3)`, commit 598b060); step 3 (`Make the verifier's
  tests pass ... (6 failing)`) found nothing left to edit and was closed on the same commit; `state.py advance verify`;
  `verify.py brief` for round 2 carried round 1's findings; the verifier added twelve more tests (over-catching, Decimal
  and Fraction zeros, keyword arguments) and answered `Hook SubagentStop ... verifier round 2: PASS, 0 finding(s); its run:
  28 passed, 0 failed.`; `report.py --summary` rendered `GREEN: 28 passed, 0 failed · verifier PASS`, `Verifier: PASS
  (round 2 of 3)`, the coverage table with both criteria on `test`, and `Round 1: FAIL` with its three findings;
  drift `none`. Branch: `e20bec7 rehorse: report` / `91c718a verify: round 2 tests` / `598b060 step 2` / `efa3580 verify:
  round 1 tests` / `41eaafa step 1` / `e51ad94 tests: red` / `f778950 init`. Nothing merged. The report is the README's
  sample now.
- Two things the live output showed and that were changed after it: the verifier's finding descriptions ran to a
  paragraph, so as step titles they swamped PROGRESS.md (now capped at 180 characters, keeping `(file:line)`; the agent is
  asked for one sentence; the full text stays in `verify_history` and the report), and "Tests added" listed twelve test ids
  on one line (more than three are now counted per file, the ids stay in state).

## After milestone 5: four items before the first tag (2026-09-04)

- **The verifier's inputs are hook-enforced** (`guard_read.py`, PreToolUse on `Read|Grep|Glob`). When `agent_type` is the
  verifier, only two places are readable: the briefs under `.rehorse/verify/` and the worktree minus its `rehorse-reports/`
  copy; everything else (`rehorse-reports/`, `state.json`, `handoff.json`, the main checkout) is denied with a reason that
  names the worktree. A Grep or Glob with no `path` searches the tool's cwd, which is the main checkout unless the verifier
  moved into the worktree, so it is judged by that cwd and the reason says so. `.rehorse/` cannot be denied wholesale
  because the worktree lives under it. Other agents and the orchestrator are untouched, and the hook writes nothing. The
  README's "prose-guided" caveat for the verifier is gone, and so is the IDEAS.md entry.
- **Coverage gate in the tests phase** (`coverage.py`, `step_done.py`, `state.gate`). The tests-phase agent's reply ends
  with the verifier's coverage shape (`{"coverage": [{"criterion", "ref": "<file>::<test>"}]}`); `step_done.py` records it
  and blocks the stop while any acceptance criterion in `REHORSE_SPEC.md` has no entry whose ref names a real test in a new
  or changed test file (a missing `## Acceptance criteria` section counts as uncovered, so the orchestrator must write it).
  `state.py advance implement` re-checks it and names the uncovered criteria. The check is mechanical on purpose: it
  proves each criterion has *a* new test, not that the test asserts the right thing; the live run 3 drive maps the
  divide-by-zero criterion to the happy-path test to show exactly that, and the verifier is what catches it. In-process
  callers of `state.advance` with no `root` skip the coverage clause (nothing to read the spec from); only the CLI advances
  a real task. The SubagentStop hook for step agents moved from `progress.py --step-done` to `step_done.py`, matched on
  `^rehorse:rehorse-step$`, because the rule pushed `progress.py` past 150 lines and the hook and the renderer are two
  jobs; `task_id` moved to `worktree.py` for the same reason on `state.py`.
- **A step closed with no edits is "already satisfied"**. `step_done.py` compares HEAD with earlier steps' commits; when an
  earlier step's commit is HEAD, the step is recorded with `satisfied_by: <that step>` and PROGRESS.md and the report render
  `already satisfied by step N (no edits)` instead of the reply's summary. The live run showed the case: the round-trip
  appends both a `Fix ...` step and a `Make the verifier's tests pass` step, and the fix usually settles both.
- **Verifier tests are counted at merge, and asked to be few.** `merge.py` counts the tests in the branch's `rehorse_verify_*`
  files (pytest `def test_`, go/swift `func Test|test`, rust `#[test]`, vitest/jest `it(`/`test(`) and prints
  `verifier_tests` and `verifier_files`; the merge skill reports them in one line, because those tests join the user's
  suite for good. The verifier's prompt now asks for the fewest tests that demonstrate each finding and none that restate a
  test in the diff (the live run added 25 tests for a two-criterion spec).

## Milestone 6: eval harness (2026-09-04)

Docs re-fetched before writing (CLI reference): `claude -p --output-format json` returns `session_id`, `num_turns`,
`duration_ms`, `total_cost_usd`, `usage`, `is_error`, `result`; `--plugin-dir` loads a plugin for one session;
`--bare` skips plugins and hooks, so the eval never passes it.

- **`find_tasks.py` uses GraphQL `closedByPullRequestsReferences`**, not the REST timeline, because it returns the
  linked PRs of an issue with `merged`, `changedFiles`, `files` and `mergeCommit` in one query (50 issues a page). A
  candidate is a closed issue whose first merged PR touches 1-5 files, at least one a test path (`testcmd.is_test_path`)
  and at least one not: a PR that only edits tests leaves nothing to implement. `base_sha` is the merge commit's first
  parent, which is the base branch the moment before the fix landed for both true merges and squashes (`rich` uses both);
  the PR's `baseRefOid` is the fallback, and can be months stale (`rich#3180`: baseRefOid `e76f3c3`, merge parent
  `b32e42b`). Records are written in the `tasks.json` schema to `eval/candidates-<repo>.json` so picking ten is a
  copy; the eval task id is `<repo>-<issue>`. Per-repo `setup_cmd`/`test_cmd` defaults create the target's own venv
  (`python3 -m venv .venv && .venv/bin/pip install -e . pytest`), so `testcmd.detect()` finds that interpreter and
  never Rehorse's.
- **`run_eval.py` grades in the rehearsal worktree with the PR's own test files**, fetched from `refs/pull/N/head` (so
  `tasks.json` needs no merge-commit field beyond `pr_url`) and checked out whole, overwriting whatever Rehorse wrote in
  the same files; `upstream_pass` is that run green with at least one test. The fetch runs inside the worktree because
  `FETCH_HEAD` is per worktree (the first draft fetched in the clone and the checkout failed). A task that never made a
  worktree is graded in the clone at `base_sha`, which fails, and the result says where it ran.
- **Rehorse's own outcome is read from `.rehorse/state.json`**, never from the report's prose: `merged_green` is phase
  `report` with a last run of 0 failed and >0 passed; the verdict and round count are the state's `verifier` and
  `verify_round`. The report is copied to `eval/results/<id>.report.md` so it survives the work dir.
- **Resumable by result files**: one `eval/results/<id>.json` per task, skipped on the next run unless `--rerun`;
  `results.md` is re-rendered from all of them after every task; any exception in a task becomes its `error` column and
  the loop continues. Clones and logs live in `/tmp/rehorse-eval/` (`--work`), outside this repo, because Claude Code
  reads `CLAUDE.md` from parent directories and a clone under `eval/` would inherit Rehorse's own development
  instructions. Runs pass `< /dev/null` (spike 1), `--dangerously-skip-permissions`, `--debug-file` for the hook lines,
  `--max-turns 150` and a wall-clock timeout so a runaway session is a row, not a hang; never `--bare` (it drops plugins).
- **The `rich` setup pins pygments from `poetry.lock` and installs `attrs`.** With the latest pygments, seven syntax
  tests (golden ANSI output) fail at every base; with the lock's version the 2025 bases run green (931 passed at
  `rich-3881`'s base, from a clean venv). `attrs` is a dev dependency `tests/test_pretty.py` imports. Bases from 2023
  (`rich` 13.x) keep nine failures that are Python 3.13's own (dataclass and builtin reprs); this machine has 3.13 and
  3.9 only, so `rich` tasks are picked from bases that support the running Python (14.x, 2025), and the result JSON
  records the baseline counts so a task whose baseline was never green cannot pass for a Rehorse failure. Seen while
  checking: with any pre-existing failure the red gate is vacuous, since it counts failures rather than comparing
  failing test ids against the baseline (IDEAS.md already lists the fix); not changed in this milestone.
- **The first task is `rich-3881`** (`PromptBase.on_validate_error` should print with markup on: one source file,
  one test file, a precise issue body, 2025 base) so the harness is checked on the smallest possible rehearsal; the
  other nine are the user's pick from `eval/candidates-rich.json`.
- **Grading takes the test files from the PR's merge commit, not `refs/pull/N/head`.** The first run graded from the
  head ref and passed, but `git diff base FETCH_HEAD` showed 52 files: the author's branch predated the base by a
  Unicode-table refactor, so a test file taken from it could revert base-branch changes made in the same file before
  the merge. `run_eval.fix_ref()` asks `gh api repos/<repo>/pulls/<n>` for `merge_commit_sha` (GitHub serves any
  reachable commit by SHA to `git fetch`), falls back to the head ref when `gh` cannot answer, and the result records
  `tests_from`. `rich-3881` was re-graded from `abd5a2a` with the same outcome; the committed result is that grade.

### Evidence: first eval task end to end (`rich-3881`, Claude Code 2.1.261, 2026-09-04)

`python3 eval/run_eval.py --only rich-3881`, one session, exit 0. Clone at `12eeb42`, venv with pytest, attrs and
pygments 2.19.2 from the lock. Results row: merged-green yes, upstream-tests-pass yes, verifier pass, 1 round, 5m46s,
20 turns; `total_cost_usd` 2.62 reported by the envelope (informational; the run is on the subscription).

- Hook lines, in order: baseline `recorded test run: 931 passed, 0 failed (edit_seq 1)`; red `933 passed, 5 failed
  (edit_seq 2)` with the weak-test warning (2 of 7 new tests passed before implementation: the two regression guards);
  green `938 passed, 0 failed (edit_seq 4)`; verifier `941 passed, 0 failed (edit_seq 5)`; `SubagentStop ... verifier
  round 1: PASS, 0 finding(s)`. Four shell-write denials (spec, tests, implement, verify: one per phase, as in the
  toy runs), each followed by the same agent using Write or Edit. No Stop or SubagentStop block was needed.
- Rehearsal branch: `3ad3ec5c rehorse: report` / `3aeef898 verify: round 1 tests` / `26f7beb3 step 1` / `70749437
  tests: red` on `12eeb42c`. Rehorse's fix is the upstream one-liner exactly (`self.console.print(error, markup=True)`),
  plus a CHANGELOG line, seven tests and the verifier's three.
- Grade: the merge commit's `tests/test_prompt.py` (seven existing tests plus upstream's `test_prompt_confirm_markup`)
  ran in the worktree: `8 passed`.
- Seen: the orchestrator ran the test command as `... 2>&1 | tail -6`; `on_bash_done.py` still parsed the summary line.
  The model's Summary named a behavioural consequence the changelog line omits (unescaped brackets in a user's
  `InvalidResponse` are now parsed on `markup=False` consoles), which the verifier had turned into a test.

## Three fixes before the rich run (2026-09-04)

- **Red by test ids, not counts** (fix 1). `testcmd.failing_ids()` reads the runner's per-test failure lines (pytest
  `FAILED`/`ERROR` from `-rfE`, now appended by `detect()`; jest `●`; go `--- FAIL:`; cargo `test x ... FAILED`; XCTest
  `Test Case ... failed`; vitest `FAIL file > name`, else its `×` lines), one family per runner, first match wins.
  `on_bash_done.py` stores them as `baseline.failing` and, in the tests phase, `red_check.new_failing` / `new_failed`
  (ids not failing at baseline) and `preexisting`; a green baseline needs no ids. `state.gate` requires `new_failed > 0`
  (or a failed build) and says "the N failing test(s) also fail at baseline" when that is why. When a runner printed
  counts but no ids (`failing_ids` returns None), the count difference is used, `ids_unavailable` is set, and both the
  hook message and the report warn "judged by counts". The report lists "N failing at baseline (ignored): ids" and the
  new failures at red whenever the baseline had failures. Fixture `tests/fixtures/repo_with_preexisting_failure/` is
  driven with real pytest through the hook: the old failure alone is refused by the gate, a new failing test passes it.
  An `ERROR` collection line is an id too (pytest counts it as a failure); a new test file that fails to import still
  shows fewer tests than baseline and stays `build_failed`. IDEAS.md entry removed.
- **Guard tests** (fix 2). The tests-phase agent marks a regression guard with `# rehorse: guard` (or `// rehorse:
  guard`) on the line above its definition; `coverage.guards()` reads the marker in the tests phase's new or changed test
  files (the first test definition at or after it: python `def test_`, with the class for indented methods; `it(`/`test(`;
  go `func Test`; rust `fn` after the marker; swift `func test`) and `on_bash_done.py` records the ids in `task["guards"]`
  at the red run. The weak-test count is early passes minus passing guards; the hook and the report say "N guard(s)
  expected to pass; M unexpected pass(es)" and only M > 0 is a warning. A failing guard is excluded from `new_failing`
  (it was expected to pass, so it is not red) and reported as `failing_guards`. The rich-3881 run's "2 new tests passed
  before implementation" were two such guards; with the marker they would have read "2 guards expected to pass; 0
  unexpected passes". Marker rather than reply metadata because the marker lives next to the test, is visible in the diff
  the verifier reads, and survives a re-run of the tests phase.
- **Methodology at the top of `eval/results.md`** (fix 3): the base commit rule, grading from the merge commit rather
  than the PR head, upstream files replacing Rehorse's edits so its own tests never count, and the environment pins and
  Python 3.13 constraint, so the table cannot be read without its rules. The `tier` column comes from `tasks.json` at
  render time (not copied into result files), so re-tiering a task never leaves a stale value.

## The rich eval, ten tasks: reading the table (2026-09-05)

- **`merged-green` is now `self-green`, and `rehorse-outcome` is a column of its own.** The old name claimed a merge
  that never happens in the eval (nothing is ever merged; the column was always Rehorse's self-report), and one
  yes/no column could not tell a task that stopped at `needs-attention` from one whose session crashed: both read
  `no`. `outcome_label()` reads state's phase, never the report's prose, and renders `green` / `needs-attention` /
  `error`; any other phase renders as itself (`implement`), so a task that stalled mid-run cannot be read as a clean
  stop. The result files keep the `merged_green` key, so results written before the rename still render.
- **The headline sentence moved above the table**, with a line under it saying wall time is dominated by verify
  round-trips rather than by the size of the fix: the two slowest rows (34m23s at 3 rounds, 22m30s at 2) are the two
  the verifier sent back, and every one-round row is under 16 minutes. Reading the table without that, the wall column
  looks like a difficulty measure, which it is not.
- **`rich-3881` was re-run** after fixes 1 and 2 (red by test ids, guard markers) landed, since its first result was
  graded before either existed; the first result is kept at `eval/results/archive/rich-3881.pre-fix1.*`. Same fix,
  same upstream pass, self-green both times — but the verdict went `pass` (5m46s, 20 turns) to `concerns` (8m12s, 21
  turns) on identical code. The concern the second verifier raised is exactly the behavioural consequence the *first*
  run's model wrote in its own Summary and its verifier let through: forcing markup on makes a `str` error message
  echoing user input markup-parsed on a `markup=False` console, so a typed `[/]` can raise `MarkupError` out of
  `Prompt.ask`. So the verdict difference is run-to-run variance in the verifier, not a change in the code, and the
  variance ran in the safer direction.

## rich-3871: which failed, the verifier or the implementer (2026-09-05)

The task stopped at `needs-attention` after three `fail` verdicts while the upstream PR's tests pass, so the question
was whether (a) the verifier's test contradicted the spec, and the implementer should have replied `CONTRADICTS SPEC:`,
or (b) the objection was real but not a spec violation, so it should have been `concerns`. **Neither: the verifier was
right all three times, and the implementer is what failed.** Criterion 4 of that task's spec reads "Default tables
(`Table(...)` with `pad_edge=True`, `collapse_padding=False`) keep their current column widths and rendered output —
the fix must be a no-op whenever `pad_edge` is `True`." Rounds 2 and 3 both cite it by name. Checked, not taken on
trust: the round-3 test `test_default_expanded_ratio_table_keeps_base_widths_and_content` still fails on the final
code (`[6, 4, 3]` / `' xxx   x…  … '`), and the same three-column `expand=True` table run against the base commit
`fe55a13` gives `[5, 5, 3]` / `' xxx  xxx  … '` — exactly what the test asserts. So a default `pad_edge=True` table
really did change, which criterion 4 forbids, and `fail` was the right verdict. The upstream tests pass because they
never build that table; this is the eval's two columns measuring different things, not a contradiction.

- **What the implementer did wrong** (not fixed here; `IDEAS.md`). Round 1's finding was about `pad_edge=False`
  expanded tables, and step 2 chose to fix it in `ratio_distribute` — shared width allocation used by *every* expanded
  table — rather than in the caller's `flex_minimum`. That widened the blast radius from the spec's case to all of
  them, and rounds 2 and 3 are the same regression twice: step 4 narrowed the clamp to `sum(minimums) <= total`, which
  does not exclude the failing case (its minimums do fit). Steps 3 and 5, both "make the verifier's tests pass", were
  closed with no edits as already satisfied — true of the tests that existed at that moment, and each new round then
  found another case. The step agent's own summary reports brute-force proof that the *unsatisfiable* branch is
  unchanged: real work, aimed at the wrong half of the behaviour.
- **A `fail` must cite the acceptance criterion it violates; anything else is `concerns`** — encoded in the hook, not
  only in the prompt. A finding may carry `criterion`, and `verify.parse()` records a `fail` whose findings all lack
  it as `concerns` with `downgraded: True`, which the SubagentStop message says out loud. Downgrade rather than block
  (the other option) because the rule is about what a verdict *means*: an objection that cannot point at the spec is
  information for the user, not grounds to stop the model. Nothing is lost by it — a failing verifier test still sends
  the task back to implement whatever the verdict — so the only thing the rule removes is a round-trip bought by taste.
  rich-3871's own recurring `medium` (the `tests/test_columns.py` snapshot was rewritten) is exactly that shape: real,
  worth reading, and not a criterion violation. The generic "Address the verifier's FAIL verdict (no findings listed)"
  step is gone with it: a `fail` now always arrives with a finding, so the step was unreachable.
- **What separates `concerns` from `pass`**, from reading all ten runs' verdicts: six of ten were `concerns`, and they
  split into two kinds. Real risks — rich-3841's fix leaves the reported bug in place for `justify="center"`,
  rich-3708's group member whose `__cause__` is the group still dies with `RecursionError`, rich-3727's negative
  `code_width` collapsing a render, rich-3881's `MarkupError` escaping `Prompt.ask` — each names something the user
  should read before merging. Against that, "no test in the diff reaches this branch, so my test now pins it"
  (rich-3569, rich-3708) is the verifier reporting its own coverage work as a finding. The prompt now says a concern
  must name a specific risk with file, line and test, that style and naming notes are not concerns, and that "the diff
  did not test this, so I added a test" is a `pass`. `findings_text` moved from `verify.py` to `report.py` to pay for
  the new lines: `verify.py` is a hook script and stays at its 150-line cap.

## Existing tests may be changed only when the spec says the pinned behaviour is wrong (2026-09-05)

The tests phase could always edit any test path, so it could rewrite an assertion the repo already relied on and
nothing recorded that it had. rich-3871's verifier caught exactly this three rounds running (`tests/test_columns.py`
snapshot rewritten; "the new values are semantically correct but the edit is outside the sanctioned scope") and had no
way to tell a justified rewrite from a quiet one. Now the rewrite is legal, declared, and carried to the reader.

- **Detection is textual and lives in `coverage.py`** (no line cap there): `test_bodies()` splits a file into
  `<id> -> lines` with the parsers `guards()` already uses, dropping each body's blank tail so adding a test after
  another does not read as changing it; `changed_existing_tests()` compares every changed test file against its
  content at `base_sha` and returns the ids that differ or vanished. Tests the phase *added* are not changes. It is
  mechanical on purpose, in the same spirit as the coverage gate: a reformatting counts as a change, which is why the
  answer to it is "give a reason", not "prove intent".
- **Declared in the reply, gated at the stop.** The tests-phase agent's json block gains
  `"expected_test_changes": [{"test": "<file>::<test>", "why": "<one line>"}]`; `step_done.py` blocks the stop while a
  changed existing test has no entry, naming the test and telling the agent to restore it or declare it with the
  criterion that says so. Declarations for tests that did not actually change are dropped rather than recorded, so
  `task["expected_test_changes"]` only ever holds real ones. `state.gate` re-checks it on `tests -> implement` for the
  same reason the coverage gate is re-checked there: the SubagentStop hook is not the only door into implement, and a
  guarantee that only fires for subagents is prose. The implement-phase lock is untouched — test paths stay locked once
  the tests are in — so this widens nothing.
- **The verifier is told first.** `report.changes_block()` renders the section for both the report and the brief, and
  `verify.brief()` puts it after the diff; the verifier prompt now opens on it: those tests said something else before,
  the reason given is a claim about the spec, and checking that claim is the job. A rewrite whose reason is not in the
  spec is a `fail` citing the criterion it contradicts; one that weakens an assertion the spec never mentions is a
  `concerns` naming what is no longer pinned.
- **The report says `Existing tests changed: N` with the reason for each**, one line when there were none (the report
  has a one-screen budget and nothing happened), and **drift treats declared changes as expected**: `drift()` now asks
  which test ids actually changed in each file since `tests_sha` and excuses the file only when every one of them was
  declared. One undeclared test in the file makes it drift again, so the excuse cannot be borrowed.
- **Fixture** `tests/fixtures/repo_with_pinned_wrong_behaviour/`: `truncate()` writes its ellipsis outside the width
  budget, and `test_long_text_is_cut_with_an_ellipsis` pins that off-by-one, so a correct fix *must* change that
  assertion. The tests drive the real hook over it — undeclared rewrite blocked and named, declared rewrite recorded
  with its reason, a new test alongside untouched ones needing no declaration. Writing them caught a real property of
  the detector: changing the quote style of an untouched test is a change, and the fixture-derived test data now says
  so honestly rather than working around it.
