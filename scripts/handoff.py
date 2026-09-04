#!/usr/bin/env python3
"""PreCompact hook: snapshot what the orchestrator must re-learn after compaction.

Writes .rehorse/handoff.json (task, phase, step, plan, last test result, next action, trigger) and refreshes
PROGRESS.md, the durable memory. PreCompact cannot inject context; the SessionStart(compact) hook (state.py --summary)
does that and points the model at PROGRESS.md. Prints nothing.
"""
import datetime
import json
import os
import sys

import progress
import state


def main():
    hook = json.load(sys.stdin)
    root, s, task = state.active(hook.get("cwd"))
    if not task:
        return 0
    progress.render(root, s)
    snap = {"task": task["id"], "phase": task["phase"], "step": task["step"],
            "plan": [{"title": p["title"], "done": p["done"]} for p in task["plan"]],
            "last_test_run": task["last_test_run"], "next_action": progress.next_action(task),
            "trigger": hook.get("trigger"), "at": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(os.path.join(root, ".rehorse", "handoff.json"), "w") as f:
        json.dump(snap, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
