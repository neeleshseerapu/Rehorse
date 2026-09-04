#!/usr/bin/env python3
"""UserPromptSubmit hook: the only place a merge/discard grant is minted.

This event fires for text the user typed, never for anything the model does (a Skill tool call is a PreToolUse),
so a grant file proves a human asked. Every prompt first clears this repo's grants (a grant lasts one turn); then
`/rehorse:merge [id]` mints ~/.rehorse/merge-<id> for a task in phase report, and `/rehorse:discard [id]` mints
discard-<id> for any non-terminal task. The reply tells the model exactly which script to run, or why nothing was granted.
"""
import json
import os
import re
import sys

import grant
import state

CMD_RE = re.compile(r"^\s*/rehorse:(merge|discard)(?:\s+(\S+))?")
PLUGIN = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def decide(s, action, arg, session_id):
    tid = arg if arg and arg.startswith("t-") else s["active_task"]
    task = s["tasks"].get(tid)
    if not task:
        return "no task %r to %s; /rehorse:status lists tasks." % (tid, action)
    if task["phase"] in state.TERMINAL:
        return "task %s is already %s; nothing to %s." % (tid, task["phase"], action)
    if action == "merge" and task["phase"] != "report":
        return ("task %s is in phase %s; only a task in phase report can be merged. Finish the rehearsal with "
                "/rehorse:build, or /rehorse:discard %s." % (tid, task["phase"], tid))
    grant.mint(action, tid, session_id)
    return ("the user authorized %s of %s. Run `python3 %s/scripts/%s.py %s` now, report its output, and do nothing else."
            % (action, tid, PLUGIN, action, tid))


def main():
    hook = json.load(sys.stdin)
    root, s, _ = state.active(hook.get("cwd"))
    if not root or not s["tasks"]:
        return 0
    grant.clear(s["tasks"])
    m = CMD_RE.match(hook.get("prompt") or "")
    if not m:
        return 0
    text = decide(s, m.group(1), m.group(2), hook.get("session_id") or "")
    json.dump({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "REHORSE: " + text}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
