#!/usr/bin/env python3
"""discard.py [task-id]: drop a rehearsal (worktree + branch) from any non-terminal phase. The user's branch is
untouched. Needs the user grant ~/.rehorse/discard-<id> (minted only when the user types /rehorse:discard). Prints JSON.
"""
import json
import os
import sys

import grant
import progress
import state
import worktree


def main(argv):
    root, s, _ = state.active(os.getcwd())
    if not root:
        sys.exit("discard.py: not inside a git repository")
    tid = argv[0] if argv else s["active_task"]
    task = s["tasks"].get(tid)
    if not task:
        sys.exit("discard.py: no task %r" % tid)
    if not grant.take("discard", tid):
        sys.exit("REHORSE: no user authorization to discard %s. Only the user grants it, by typing /rehorse:discard %s." % (tid, tid))
    if task["phase"] in state.TERMINAL:
        sys.exit("REHORSE: task %s is already %s." % (tid, task["phase"]))
    worktree.remove(root, tid)
    state.advance(s, tid, "discarded")
    state.save(root, s)
    progress.render(root, s)
    json.dump({"discarded": tid, "branch": task["branch"], "report": task["report_path"]}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
