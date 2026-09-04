# IDEAS.md

Out-of-scope ideas noticed while building. Not to be built without a decision.

- SessionStart `initialUserMessage` can seed the first turn in `-p` mode; `run_eval.py` could use it instead of passing the prompt on the CLI.
- `claude plugin init` scaffolds a skills-directory plugin that auto-loads without `--plugin-dir`; an alternative install path for users who dislike marketplaces.
- Hook input carries `agent_id` for subagent calls, so per-step file allowlists could be enforced per subagent rather than per phase.
- `guard_edit.py` could also guard `NotebookEdit` (`tool_input.notebook_path`); v1 matches only Edit|Write|MultiEdit.
- Lock the `spec` phase to `REHORSE_SPEC.md` and the `verify` phase to `tests/rehorse_verify_*`; v1 enforces isolation only in those phases, per the spec's hook table.
- `guard_bash.py` could add a whole-string regex fallback for `git merge|push|...` to catch shell constructs its tokenizer misses, at the cost of false positives on commit messages and echo strings.
- Per-step file allowlists: `edit_seq` could be bumped only for non-report paths (done) and the Stop guard could name the files edited since the last run.
- `UserPromptExpansion` (matcher on `command_name`, structured `command_args`) is a purpose-built alternative to parsing `/rehorse:merge` out of the raw `UserPromptSubmit` prompt; switch if the raw-prompt regex proves brittle.
- `testcmd.detect()` could prefer `uv run pytest` / `poetry run pytest` when `uv.lock` / `poetry.lock` exist and no venv does.
- Src-layout packages installed editable in the main checkout's venv resolve imports to the main checkout, not the worktree; `python -m pytest` from the worktree wins only for flat layouts. A `PYTHONPATH=<worktree>/src` prefix or a per-worktree `pip install -e` would fix it (matters for `rich`/`fastapi` in milestone 6).
- JS worktrees have no `node_modules`; `npx vitest` there needs an install or a symlink to the main checkout's `node_modules` (matters for `zod` in milestone 7).
- The red gate could compare failing test ids against the baseline instead of counts, so a collection error in a new test file (pytest reports `1 error`, runs nothing else) is distinguished from a real red run (milestone 5).
- `worktree.create` appends `.rehorse/` to the user's `.gitignore` and leaves that change uncommitted; `merge.py` could include it in the merge commit.
