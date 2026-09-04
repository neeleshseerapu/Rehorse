---
name: discard
description: Drop a Rehorse rehearsal - remove its worktree and branch, leaving the current branch untouched. Only the user can run this; the script refuses without the user's grant.
argument-hint: "[task-id]"
disable-model-invocation: true
---

Run exactly this, once:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/discard.py $ARGUMENTS
```

Show its output to the user verbatim: JSON on success (`discarded`, `branch`, `report`), or the refusal message. Then
stop. No other git command, no retry, no edit. If it refused for lack of authorization, the grant is minted only when
the user types `/rehorse:discard` themselves; say so and stop.
