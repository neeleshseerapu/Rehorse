# IDEAS.md

Out-of-scope ideas noticed while building. Not to be built without a decision.

- SessionStart `initialUserMessage` can seed the first turn in `-p` mode; `run_eval.py` could use it instead of passing the prompt on the CLI.
- `claude plugin init` scaffolds a skills-directory plugin that auto-loads without `--plugin-dir`; an alternative install path for users who dislike marketplaces.
- Hook input carries `agent_id` for subagent calls, so per-step file allowlists could be enforced per subagent rather than per phase.
