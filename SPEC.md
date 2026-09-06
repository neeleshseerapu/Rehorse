This is the build spec. Claude Code reads it before each milestone; humans can too.

# Rehorse — build spec for Claude Code

You are building **Rehorse**, an open-source Claude Code plugin. Read this whole file before touching anything. Do not widen scope beyond what is written here; if you think something is missing, ask before adding it.

## One line

Auto mode you can actually walk away from: every task rehearses on a git worktree, must go red-then-green on tests, gets checked by an independent verifier, and stops with a report. Nothing reaches the user's real branch until they say `merge`.

## Why it exists

Existing Claude Code workflow harnesses (GSD and its forks) enforce their workflow with markdown prompts. The model can skip steps. Rehorse enforces the workflow with **hooks**, which run whether or not the model wants them to. The pitch is not "structured workflow"; it is "the agent can't touch main and can't grade its own homework."

## Non-negotiables

1. **Zero cost to run.** No API keys, no external services. Runs entirely on the user's existing Claude Code subscription plus git and Python 3 stdlib. No pip dependencies for anything that runs at hook time.
2. **Ship as a Claude Code plugin.** Skills, agents, hooks, and scripts live in the plugin directory. Never rely on `~/.claude/commands/` or any undocumented directory layout. Before writing plugin or hook code, fetch and read the current docs:
   - Plugins: https://code.claude.com/docs/en/plugins
   - Hooks reference: https://code.claude.com/docs/en/hooks
   - Skills: https://code.claude.com/docs/en/skills
   Use the exact JSON schemas from the docs (for example, PreToolUse decisions use `hookSpecificOutput.permissionDecision`; Stop hooks use root-level `decision`/`reason`). Do not write hook output formats from memory.
3. **Deterministic enforcement.** Anything that is a safety guarantee must be implemented in a hook script, not in a skill's prose. Prose guides; hooks enforce.
4. **Hook scripts are plain Python 3 (stdlib only), invoked as `python3 script.py`.** Cross-platform, no jq, no bash-isms. Each script reads JSON on stdin, writes JSON on stdout, exits 0. Every hook script has pytest tests that pipe sample JSON through it.
5. **The user's real branch is never modified by the agent.** Only the `merge` command touches it, and only after the user runs it.

## Architecture

```
rehorse/
  .claude-plugin/plugin.json      # plugin manifest (schema from docs)
  skills/
    rehorse-build/SKILL.md        # /rehorse:build "<task>"
    rehorse-status/SKILL.md       # /rehorse:status
    rehorse-merge/SKILL.md        # /rehorse:merge [task-id]
    rehorse-discard/SKILL.md      # /rehorse:discard [task-id]
  agents/
    rehorse-step.md               # step worker: one tests-phase or implement step per fresh subagent
    rehorse-verifier.md           # independent verifier subagent
  hooks/
    hooks.json                    # wires events to scripts
  scripts/
    state.py                      # read/write .rehorse/state.json, phase transitions
    worktree.py                   # create / list / diff / remove worktrees
    guard_edit.py                 # PreToolUse for Edit|Write|MultiEdit
    guard_bash.py                 # PreToolUse for Bash
    guard_read.py                 # PreToolUse for Read|Grep|Glob: the verifier's inputs
    authorize.py                  # UserPromptSubmit: mints the one-shot merge/discard grant when the user types the command
    grant.py                      # ~/.rehorse/<action>-<id> grant files: mint / present / take / clear
    on_bash_done.py               # PostToolUse for Bash (records test runs)
    guard_stop.py                 # Stop hook
    step_done.py                  # SubagentStop for rehorse-step: tests run, commit, tests-phase coverage, step closed
    verify.py                     # verifier brief (CLI) + SubagentStop for rehorse-verifier: records the verdict
    coverage.py                   # acceptance criteria -> new tests mapping, checked before implement
    testcmd.py                    # detect test command + affected-test heuristics
    report.py                     # render the rehearsal report
    progress.py                   # maintain rehorse-reports/PROGRESS.md
    handoff.py                    # PreCompact: write a handoff snapshot, inject summary
    merge.py / discard.py         # called by the merge/discard skills
  tests/                          # pytest for every script
  eval/
    tasks.json                    # SWE-bench-style tasks (see Eval)
    run_eval.py                   # runs tasks via `claude -p` inside worktrees
  README.md
```

### State

Per-repo state file at `<repo>/.rehorse/state.json` (add `.rehorse/` to the user's `.gitignore` on first run). Worktrees live at `<repo>/.rehorse/worktrees/<task-id>/`.

Human-readable artifacts live in `<repo>/rehorse-reports/` and are **committed** (they are the evidence trail):

- `rehorse-reports/PROGRESS.md` — one section per task: spec summary, plan steps with `[ ]`/`[x]`, decisions made, current phase, next step. Rewritten by `progress.py`, never free-formed by the model.
- `rehorse-reports/<YYYY-MM-DD>-<slug>.md` — the rehearsal report for one task, e.g. `2026-09-03-add-dark-mode-toggle.md`. The slug is derived from the task title (kebab-case, ≤ 6 words). If a task is re-rehearsed, append `-r2`, `-r3`.
- `rehorse-reports/verifier/<same-name>.md` — the verifier's full findings when they exceed one screen; the main report links to it.

Task IDs are `t-<YYYYMMDD>-<slug>` so state, branch, worktree, and report names all match.

```json
{
  "active_task": "t-20260903-dark-mode",
  "tasks": {
    "t-20260903-dark-mode": {
      "phase": "implement",
      "worktree": ".rehorse/worktrees/t-20260903-dark-mode",
      "branch": "rehorse/t-20260903-dark-mode",
      "base_sha": "abc123",
      "test_cmd": "pytest -q",
      "test_paths": ["tests/"],
      "baseline": {"passed": 41, "failed": 0},
      "red_check": {"passed": 41, "failed": 2},
      "last_test_run": {"at": "...", "passed": 43, "failed": 0, "after_edit_seq": 17, "output": "<tail of the runner output>"},
      "tests_sha": "def456",
      "plan": [{"title": "Add the toggle", "done": true, "summary": "two lines", "commit": "0c27495"}],
      "step": 1,
      "edit_seq": 17,
      "stop_blocks": 0,
      "attention": null,
      "verifier": null,
      "report_path": null
    }
  }
}
```

**Phases advance only via scripts, never via the model:** `[setup →] spec → tests → implement → verify → report → (merged | discarded)`. `setup` exists only when no test command is detectable at task creation (`state.py new` starts the task there); otherwise the task starts in `spec`. Any non-terminal phase may drop to `needs-attention` (a hook gave up, e.g. the Stop-block cap); `state.py` records the reason and the prior phase, and the user resumes it explicitly. `discarded` is reachable from any non-terminal phase; `merged` only from `report`.

### The phase machine (what `/rehorse:build` does)

0. **Before any task exists, the main checkout may receive exactly one kind of change:** if the folder is not a git repository, ask the user's permission, `git init`, and make one commit of the current files as-is. No refactor, no harness, no ignore rules. Then create the task and worktree immediately (`state.py new`) so the hooks are live for everything that follows. (Decided after the Milo run, whose initial commit on `main` carried a model split and a `make test` harness made while the hooks were dormant.)
0b. **setup** (only when `state.py new` found no test command): a `rehorse-step` subagent, inside the worktree, adds the minimal test harness and, only if needed, the minimal refactor that makes the code testable (a seam, a module split), committed on the rehearsal branch; the orchestrator records the command with `testcmd.py set` and advances to `spec`. Isolation is enforced (`guard_edit.py`); no path lock applies in this phase.
1. **spec**: Ask the user clarifying questions only if the task is ambiguous. Write `.rehorse/worktrees/<id>/REHORSE_SPEC.md` (goal, acceptance criteria, files likely involved). Detect the test command (`testcmd.py`, from the **target repo only**: its `.venv`/`venv` interpreter by absolute path, pyproject/pytest.ini, package.json scripts, Makefile, Cargo.toml, go.mod, Package.swift; never Rehorse's own interpreter; quiet flags such as `-q --tb=short` / `--reporter=dot` are appended; ask the user if undetectable, or record one with `testcmd.py set`). Record the baseline test result on the untouched worktree. A baseline that runs 0 tests (no summary line, or a summary reporting 0 tests) sends the task to `needs-attention`: the test command or test discovery is wrong, and nothing downstream can be trusted.
2. **tests**: The model writes or extends tests from the spec **only**. It must not touch non-test files (enforced by `guard_edit.py`). Then `red_check`: run the tests; **at least one test must fail that was not failing at baseline**. `on_bash_done.py` records the failing test ids of the baseline and of the red run (pytest `-rfE` `FAILED`/`ERROR` lines; jest `●`, go `--- FAIL`, cargo, XCTest and vitest `FAIL`/`×` lines) and `red_check.new_failed` is the count of ids not in the baseline's; when a runner prints counts but no ids, the count difference is used and `ids_unavailable` is set (the hook and the report warn). Pre-existing failures are reported apart, as "N failing at baseline (ignored)". **Guards:** a new test the agent expects to pass before the implementation (a regression guard) carries `# rehorse: guard` / `// rehorse: guard` on the line above its definition; `coverage.guards()` records their ids in `task["guards"]`, a failing guard is not red, and the weak-test line reads "N guard(s) expected to pass; M unexpected pass(es)", a warning only when M > 0. If nothing new fails, the phase does not advance, and the model is told why. (A test that passes before the feature exists tests nothing.) `red_check` also fails if the run parses no summary line or reports 0 tests. **Coverage gate:** the tests subagent's reply ends with a ```json `{"coverage": [{"criterion", "ref": "<file>::<test>"}]}` block mapping every acceptance criterion in `REHORSE_SPEC.md` to a test it added; `step_done.py` records it and holds the subagent while a criterion has no entry whose ref names a real test in a new or changed test file, and `state.advance(tests -> implement)` refuses with the uncovered criteria named. The gate checks that the mapped tests exist, not what they assert; the verifier judges that. **Red by compile failure:** when the red run's output shows a build/compile error (swift, cargo, go, tsc, xcodebuild) or reports fewer total tests than the baseline, the new tests reference symbols that do not exist yet; `on_bash_done.py` records `red_kind: "build_failed"`, counts it as red, skips the weak-test computation, and the report renders "build failed (new tests reference symbols that don't exist yet)" instead of counts. (Milo's red row read `0 passed, 1 failed` against a baseline of 3.)
3. **implement**: The orchestrator splits the spec into 1–6 plan steps and writes them to `PROGRESS.md`. Each step runs as a **fresh subagent** (see Context management) that edits non-test files only. Test paths are locked (enforced). Edits outside the active worktree are denied (enforced). Each Bash test run is recorded by `on_bash_done.py`. After each step, `progress.py` marks it done and records a two-line summary; the orchestrator never reads the step's transcript, only that summary. **Every step ends in a commit**: `progress.py --step-done` refuses to mark a step complete while `worktree.dirty()` is non-empty, with a reason naming the exact `git add`/`git commit` command to run.
4. **verify**: `verify.py brief` writes the verifier's brief with **only**: `REHORSE_SPEC.md`, `git diff base_sha..HEAD`, the last test output (and, from round 2, the verifier's own earlier findings), and prints the prompt the orchestrator hands the `rehorse-verifier` subagent verbatim. It never receives the implementer's transcript or step summaries. It may write additional tests into one file of its own (named per runner by `testcmd.verify_file`, e.g. `tests/test_rehorse_verify_<id>.py`; `guard_edit.py` allows nothing else in this phase), must run the test command, commits, and ends with a JSON verdict (`pass | concerns | fail`, `findings[]`, `tests_added[]`, `coverage[]` mapping each acceptance criterion to `test | build_only | none`). `verify.py --verdict` (SubagentStop, matched on the verifier's agent type) records it; the orchestrator never copies a verdict, and `state.advance(verify -> report)` refuses without one. A `fail` verdict or a failing verifier run returns the task to `implement` with the findings appended as plan steps (the verifier's file is then locked like every test), at most twice; a third failing round sets `needs-attention` with the findings. A step reply whose line starts `CONTRADICTS SPEC:` sets `needs-attention` too.
5. **report**: `report.py` renders `rehorse-reports/<date>-<slug>.md` and updates `PROGRESS.md`: files changed, diff stat, tests baseline → red → green counts, test-file drift check (diff of test paths vs. `tests_sha`, the worktree HEAD when `progress.py plan` was run; any drift is flagged), verifier verdict and findings, and the exact merge/discard commands. Both files are written in the main checkout (where the user looks) and committed as copies on the rehearsal branch, so `merge` carries the evidence into the real branch. **The agent's turn ends here.** It must not merge.
6. **merge / discard**: User-invoked skills. When the user types `/rehorse:merge <id>` or `/rehorse:discard <id>`, the `UserPromptSubmit` hook (`authorize.py`) writes a one-shot grant file to `~/.rehorse/<action>-<id>` (outside the repo; `merge` only for a task in `report`, `discard` for any non-terminal task). `merge.py` consumes the grant, fast-forwards or merges the rehearsal branch into the user's current branch, and removes the worktree; `discard.py` consumes it and removes the worktree and branch. Both refuse without a grant, and are the only code paths allowed to modify the real branch. The model cannot mint or read a grant: `UserPromptSubmit` fires only for user-typed text, and `guard_bash.py`/`guard_edit.py` deny anything that names `~/.rehorse/`. A grant is cleared on the next user prompt and expires after an hour.

### Hooks (the guarantees)

| Event | Matcher | Script | Enforces |
|---|---|---|---|
| PreToolUse | Edit, Write, MultiEdit | `guard_edit.py` | If a task is active: deny edits outside its worktree (in `setup`, `spec`, `verify`, `report` that is the only rule). In `tests` phase: deny edits to non-test paths. In `implement` phase: deny edits to test paths, and deny any call with no `agent_id` (the main thread / orchestrator) unless the path is under `.rehorse/` or `rehorse-reports/`. Increment `edit_seq`. |
| UserPromptSubmit | — | `authorize.py` | Clear this repo's grants (a grant lasts one turn). If the prompt is `/rehorse:merge [id]` (task in `report`) or `/rehorse:discard [id]` (any non-terminal task), mint `~/.rehorse/<action>-<id>` and tell the model which script to run; otherwise say why not. |
| PreToolUse | Read, Grep, Glob | `guard_read.py` | When the call comes from the `rehorse-verifier` subagent: deny paths outside its brief (`.rehorse/verify/`) and the worktree, and the worktree's `rehorse-reports/` copy, so the verifier never reads step summaries or earlier reports. |
| PreToolUse | Bash | `guard_bash.py` | Deny `git merge/rebase/reset --hard/checkout/switch/push` and anything writing to the real branch unless the user holds a grant file for the active task (`grant.present`). Deny any command naming `~/.rehorse/`. Deny `rm -rf` on the repo root or `.rehorse/`. Deny `--no-verify`. |
| PostToolUse, PostToolUseFailure | Bash | `on_bash_done.py` | If the command matches the task's test command, parse pass/fail counts from `tool_response.stdout` (PostToolUse) or `error` (PostToolUseFailure; a red run exits non-zero and only fires this event) and record `last_test_run` with the current `edit_seq`, plus the failing ids into `baseline` (spec) and `red_check.new_failed` (tests). A run is recorded **only** when `parse_counts()` returns a summary; `--collect-only`, `--version`, and grep-style matches on the runner name do not count. |
| Stop | — | `guard_stop.py` | If phase is `implement` and `last_test_run.after_edit_seq < edit_seq` (edits since last test run): block with reason "run the test command before stopping." If phase is `report`: allow. Otherwise allow. Claude Code allows at most 8 consecutive Stop blocks, so every block increments `stop_blocks` in state (reset to 0 on any allowed stop); on the 8th block the script instead sets the phase to `needs-attention` with the reason, allows the stop, and `report.py` renders that state as the banner. |
| SessionStart (all sources: `startup`, `resume`, `clear`, `compact`) | — | `state.py --summary` | Inject a one-line summary of active tasks into context via `hookSpecificOutput.additionalContext`. This is also the post-compaction re-injection path (PreCompact cannot inject). |
| PreCompact | — | `handoff.py` | Before Claude Code compacts context: write `.rehorse/handoff.json` (phase, current step, last test result, next action). The summary itself is injected by `state.py --summary` on the following `SessionStart(compact)`. |
| SubagentStop | `^rehorse:rehorse-step$` | `step_done.py` | When a step subagent finishes: a `CONTRADICTS SPEC:` line -> `needs-attention`; else verify tests were run in that step, refuse to complete the step while `worktree.dirty()` is non-empty (reason names the exact git command); in the tests phase record the reply's coverage block and refuse while an acceptance criterion has no new test; then record its summary in `PROGRESS.md` and advance the step pointer. |
| SubagentStop | `^rehorse:rehorse-verifier$` | `verify.py --verdict` | When the verifier finishes: block until it ran the test command after its last edit, committed, and ended with the JSON verdict; record the verdict; on `fail` or failing verifier tests return to `implement` with the findings as steps (third failing round -> `needs-attention`). |

Every deny returns a reason that tells the model exactly what it may do instead.

### Context management (for the user's session)

The model cannot clear its own context mid-task, so Rehorse does not "clear at milestones." It keeps context small by **delegation**, like a manager who reads standup summaries instead of every engineer's inbox:

- **The main session is an orchestrator.** Its context holds only: the spec, the `PROGRESS.md` section for the active task, and the state summary. The `rehorse-build` skill instructs it to delegate every phase and every implement step to a subagent and to never read or edit files itself during implement. It **may run the test command** (that is how it records the baseline and red runs and satisfies the Stop hook); everything else it delegates.
- **Every phase and step is a fresh subagent** (Claude Code's Task/subagent mechanism), handed only artifacts: `REHORSE_SPEC.md`, the step description, the list of files the step may touch, and the previous step's two-line summary. It returns a two-line summary. Its transcript is discarded.
- **`PROGRESS.md` is the durable memory.** It is rewritten by `progress.py` from `state.json`, so it is always consistent and never drifts into prose. A user (or a resumed session) can read it and know exactly where the task is.
- **Compaction is survivable.** `handoff.py` runs on PreCompact so the orchestrator re-learns phase, step, and next action from the injected summary instead of from whatever survived compaction.
- **Resume is first-class.** `/rehorse:build` with an active task, or a new session after SessionStart injection, continues from `PROGRESS.md` rather than starting over.
- **Steps are sized for one context.** The orchestrator is told: a step is something one subagent can finish, test, and summarize without reading more than ~15 files. If a step summary reports it could not finish, the orchestrator splits it and appends the new steps to `PROGRESS.md`.

Hook input carries `agent_id` only when the call comes from a subagent (docs: "use this to distinguish subagent hook calls from main-thread calls"; confirmed in spike 8), so the "orchestrator never edits" rule **is hook-enforced**: during `implement`, `guard_edit.py` denies Edit/Write/MultiEdit calls that have no `agent_id`, except for paths under `.rehorse/` and `rehorse-reports/` (the orchestrator's own bookkeeping). The other guarantees (worktree isolation, test-path lock, red-before-green, no merge) hold regardless of which context did the editing.

### Verifier agent (`agents/rehorse-verifier.md`)

System prompt principles: you are adversarial; you have not seen how this was built; assume the tests were written to pass; look for untested branches, changed behavior not covered by the spec, silent error swallowing, edge cases (empty input, unicode, concurrency where relevant); write the tests the implementer would not; run them; report findings as a JSON block with `verdict`, `findings[]` (severity, file, line, one-sentence description), `tests_added[]`, and `coverage[]` (criterion, evidence `test | build_only | none`, ref). Do not fix anything.

### Report format

Markdown, one screen. Order: verdict banner (a task in `needs-attention` renders that, with its reason, as the banner instead of a verdict) → optional **Summary**, the orchestrator's own words passed as `report.py --summary "..."` and labelled as written by the model, since everything else is generated from state (what the user gets on merge, what was verified, what was not) → tests (baseline / red / green) → diff stat → verifier findings → test-file drift → plan → **Try it yourself** (the worktree path, `cd` into it, the exact test command, and how to run the project when detectable: package.json `dev`/`start`, Makefile `run`, `build.sh`, `cargo run`, `go run .`, `swift run`, or the README's run line; otherwise say so and show the path) → merge and discard commands. Recruiters and users both read this; make it the best artifact in the project.

## Eval

`eval/tasks.json` holds SWE-bench-style tasks: `{repo, base_sha, issue_title, issue_body, pr_test_files[], test_cmd}`. `run_eval.py` clones the repo at `base_sha` into a temp dir, installs Rehorse, runs `claude -p "/rehorse:build ..."` with the plugin, then checks out the PR's test files and runs them to grade. Output: a results table (task, merged-green?, verifier verdict, wall time, tokens if available). Target repos for v1: `rich`, `fastapi`, `zod`, ten tasks each. Grading is by the upstream PR's tests, never by Rehorse's own tests.

## Out of scope for v1 (do not build)

- Any model routing / proxy / fallback provider (v2)
- Codebase knowledge graph (LSP plugins already cover most of this)
- UI, web dashboard, VS Code extension
- Support for non-git repos
- Multi-task parallelism beyond "worktrees don't collide" (A/B is a stretch goal for day 12+ only)

## Working rules for you (Claude Code)

- **Day 1 is spikes, not code.** Run every spike in the "Day-1 spikes" section below with throwaway scripts and show me the evidence. If any spike fails, stop and tell me; we redesign before building.
- Write the failing pytest for a hook script before the script (we dogfood the principle).
- Keep every script free of imports outside stdlib, and keep each **hook entry script** — the file named in
  `hooks/hooks.json` — under 150 lines. The cap exists so a hook can be read whole before it is trusted; it binds the
  entry point, not the logic behind it. Shared logic goes in `scripts/rehorse_lib/` (a plain package, stdlib only, no
  install: `scripts/` is already `sys.path[0]` for an entry script, so `from rehorse_lib import x` just works). Moving
  code there to fit is the intended move; deleting a guarantee to fit is not. `tests/test_line_cap.py` checks both rules.
- After each milestone, update `README.md` and `DECISIONS.md` (one line per decision, with the reason).
- Never "improve" scope. If you notice a missing feature, add it to `IDEAS.md` and move on.
- Manually test each hook by piping sample JSON: `echo '{...}' | python3 scripts/guard_edit.py`. Keep those samples in `tests/fixtures/`.
- When something about Claude Code behaves differently from these docs, fetch the docs again and trust the docs over this file. Then tell me what changed.

## Day-1 spikes

Each spike is a throwaway script or a two-minute manual test. Record the result (pass/fail, Claude Code version, what the JSON actually looked like) in `DECISIONS.md`. A spike "passes" only with evidence I can see.

| # | Assumption | How to prove it | Kills what if it fails |
|---|---|---|---|
| 1 | A plugin from a local path loads, and a skill in it is invocable as `/rehorse:status`. | Minimal `plugin.json` + one skill that prints "hello". | Distribution format |
| 2 | Hook scripts referenced from the plugin resolve by path (whatever the docs say, e.g. a plugin-root variable), on macOS and Linux. | Wire a PreToolUse hook that logs its stdin to a file; edit a file; check the log. | Everything |
| 3 | A PreToolUse hook can deny an Edit/Write with a reason, and the model sees that reason and adapts. | Deny edits to `*.lock`; ask Claude to edit one; watch it explain and stop. | Test-path lock, worktree isolation |
| 4 | A PreToolUse hook can deny a Bash command by pattern (`git merge`, `git push`) with a reason. | Same shape as 3. | No-merge guarantee |
| 5 | A Stop hook can block the turn from ending and its reason reaches the model. | Block stop until a file `/tmp/ok` exists. | "Run tests before stopping" |
| 6 | PostToolUse for Bash receives the command and its stdout, and pytest/vitest pass/fail counts are parseable from it. | Run `pytest -q` and `vitest run`; print what the hook receives. | Test-run recording |
| 7 | `git worktree add/diff/remove` works from a Python stdlib script, and file paths in hook input are absolute enough to tell "inside worktree" from "outside." | Create a worktree; edit files in both; inspect `tool_input.file_path`. | Worktree isolation |
| 8 | A skill can spawn a subagent with a scoped prompt, the subagent's tool calls **also** pass through PreToolUse hooks, and `SubagentStop` fires with identifiable output. | Subagent tries to edit a locked path → must be denied. Check SubagentStop stdin. | Step-based implement, lock integrity |
| 9 | `PreCompact` fires and text injected by the hook is present in context after compaction. | Fill context deliberately (large file reads), trigger `/compact`, ask the model what phase it's in. | Compaction survival |
| 10 | `SessionStart` injection works on a resumed session. | Inject "ACTIVE TASK: t-test"; resume; ask. | Resume |
| 11 | `claude -p` runs non-interactively with the plugin loaded, inside a worktree directory, and exits cleanly. | `cd worktree && claude -p "/rehorse:status"`. | Eval harness |

If 8 fails on the "subagent tool calls pass through hooks" half, the step-based implement design changes: steps then run as sequential `claude -p` invocations inside the worktree instead of subagents. Tell me before choosing.



1. Day-1 spikes (section above), with evidence in `DECISIONS.md`.
2. `state.py`, `worktree.py`, `testcmd.py` + tests.
3. Hooks: `guard_edit.py`, `guard_bash.py`, `on_bash_done.py`, `guard_stop.py` + tests; `hooks.json` wired.
4. Skills: build / status / merge / discard; `report.py`, `progress.py`, `handoff.py`; step-based implement via subagents; end-to-end on a toy repo with a tiny pytest suite, including a forced compaction and a resume from a fresh session.
5. Red-before-green check and test-path lock; verifier agent; report includes verdict and drift.
6. `eval/`: tasks.json for `rich` (10 tasks), `run_eval.py`, first results table.
7. `fastapi` and `zod` tasks; results in README; demo recording of "type one command, walk away, come back to a report."
8. Publish: plugin marketplace entry, install instructions, CONTRIBUTING with an AI-disclosure section.

Start with milestone 1. Show me the spike results before writing any production code.