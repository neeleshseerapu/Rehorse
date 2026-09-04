#!/usr/bin/env python3
"""Stop hook: in the implement phase, the turn may not end while edits are newer than the last recorded test run.

The block reason names the exact command. stop_blocks counts consecutive blocks and resets on any allowed stop;
Claude Code overrides a Stop hook after 8 consecutive blocks, so on the 8th the task drops to needs-attention
instead and the stop is allowed with a visible systemMessage, rather than silently ending an unfinished task.
"""
import json
import os
import sys

import state

CAP = 8


def main():
    hook = json.load(sys.stdin)
    root, s, task = state.active(hook.get("cwd"))
    if not task:
        return 0
    pending = task["edit_seq"] - (task.get("last_test_run") or {}).get("after_edit_seq", 0)
    if task["phase"] != "implement" or pending <= 0 or not task.get("test_cmd"):
        if task.get("stop_blocks"):
            task["stop_blocks"] = 0
            state.save(root, s)
        return 0
    if task["stop_blocks"] + 1 >= CAP:
        reason = "%d consecutive Stop blocks without a test run after edit_seq %d" % (CAP, task["edit_seq"])
        state.advance(s, task["id"], state.ATTENTION, reason=reason)
        state.save(root, s)
        json.dump({"systemMessage": "REHORSE: task %s moved to needs-attention: %s. Run /rehorse:status." % (task["id"], reason)},
                  sys.stdout)
        return 0
    task["stop_blocks"] += 1
    state.save(root, s)
    cmd = "cd %s && %s" % (os.path.realpath(os.path.join(root, task["worktree"])), task["test_cmd"])
    json.dump({"decision": "block", "reason": "REHORSE: %d edit(s) since the last recorded test run (block %d of %d). "
               "Run this exact command before stopping: %s" % (pending, task["stop_blocks"], CAP - 1, cmd)}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
