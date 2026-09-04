# IDEAS.md

Out-of-scope ideas noticed while building. Not to be built without a decision.

- SessionStart `initialUserMessage` can seed the first turn in `-p` mode; `run_eval.py` could use it instead of passing the prompt on the CLI.
- `claude plugin init` scaffolds a skills-directory plugin that auto-loads without `--plugin-dir`; an alternative install path for users who dislike marketplaces.
- Hook input carries `agent_id` for subagent calls, so per-step file allowlists could be enforced per subagent rather than per phase.
- `guard_edit.py` could also guard `NotebookEdit` (`tool_input.notebook_path`); v1 matches only Edit|Write|MultiEdit.
- Lock the `spec` phase to `REHORSE_SPEC.md` and the `verify` phase to `tests/rehorse_verify_*`; v1 enforces isolation only in those phases, per the spec's hook table.
- `guard_bash.py` could add a whole-string regex fallback for `git merge|push|...` to catch shell constructs its tokenizer misses, at the cost of false positives on commit messages and echo strings.
- Per-step file allowlists: `edit_seq` could be bumped only for non-report paths (done) and the Stop guard could name the files edited since the last run.
