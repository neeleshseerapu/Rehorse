---
name: status
description: Show the state of the current Rehorse rehearsal - active task, phase, plan progress, last test result, next action. Read-only.
---

Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/progress.py render` and show its output to the user as is (it regenerates
`rehorse-reports/PROGRESS.md` from `.rehorse/state.json`).

- No tasks: say so, and that `/rehorse:build "<task>"` starts one.
- A task in `needs-attention`: quote the reason and the two ways out: `/rehorse:build resume` (continues from the
  phase it was in) or `/rehorse:discard <id>`.
- A task in `report`: point at the report path (`state.py show` prints `report_path`) and the merge/discard commands.

Change nothing. This skill runs no other command.
