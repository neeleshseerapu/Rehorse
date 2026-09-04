---
name: merge
description: Merge a finished Rehorse rehearsal into the current branch and remove its worktree. Only the user can run this; the script refuses without the user's grant.
argument-hint: "[task-id]"
disable-model-invocation: true
---

Run exactly this, once:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/merge.py $ARGUMENTS
```

Show its output to the user verbatim: JSON on success (`merged`, `into`, `sha`, `report`, `verifier_tests`,
`verifier_files`), or the refusal / conflict message. On success add one line: how many verifier tests were merged and
in which file(s) (`verifier_tests`, `verifier_files`); they are now part of the user's suite. Then stop. No other git command, no retry, no edit. If it refused for lack of authorization, the grant is
minted only when the user types `/rehorse:merge` themselves; say so and stop.
