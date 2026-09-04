#!/usr/bin/env python3
"""merge.py [task-id]: the only code path that writes to the user's branch (with discard.py for removal).

Needs a user grant, ~/.rehorse/merge-<id>, which only the UserPromptSubmit hook mints when the user types
/rehorse:merge; the grant is consumed first, so one prompt buys one attempt. Fast-forwards the rehearsal branch into
the current branch when possible, otherwise makes a merge commit; a conflict is aborted and the rehearsal kept.
On success the worktree and branch are removed and the task becomes `merged`. Prints JSON.
"""
import json
import os
import subprocess
import sys

import grant
import progress
import state
import worktree


def main(argv):
    root, s, _ = state.active(os.getcwd())
    if not root:
        sys.exit("merge.py: not inside a git repository")
    tid = argv[0] if argv else s["active_task"]
    task = s["tasks"].get(tid)
    if not task:
        sys.exit("merge.py: no task %r" % tid)
    if not grant.take("merge", tid):
        sys.exit("REHORSE: no user authorization to merge %s. Only the user grants it, by typing /rehorse:merge %s." % (tid, tid))
    if task["phase"] != "report":
        sys.exit("REHORSE: task %s is in phase %s; only a task in phase report can be merged." % (tid, task["phase"]))
    into = worktree.git(root, "symbolic-ref", "--short", "HEAD").strip()
    sha = worktree.git(root, "rev-parse", task["branch"]).strip()
    for f in worktree.git(root, "ls-tree", "-r", "--name-only", task["branch"], "--", "rehorse-reports").split():
        if worktree.git(root, "status", "--porcelain", "--", f).startswith("??"):  # report.py's untracked copy; git will not
            os.remove(os.path.join(root, f))  # overwrite it, the branch carries the same file, PROGRESS.md is re-rendered below
    try:
        worktree.git(root, "merge", "--ff-only", task["branch"])
    except subprocess.CalledProcessError:
        try:
            worktree.git(root, "merge", "--no-ff", "-m", "Merge Rehorse rehearsal %s" % tid, task["branch"])
        except subprocess.CalledProcessError as e:
            subprocess.run(["git", "merge", "--abort"], cwd=root, capture_output=True)
            sys.exit("REHORSE: merging %s into %s hit a conflict and was aborted; %s is unchanged and the rehearsal is kept at "
                     "%s. Resolve on your side and type /rehorse:merge %s again.\n%s" % (tid, into, into, task["worktree"], tid, e.stdout))
    worktree.remove(root, tid)
    state.advance(s, tid, "merged")
    state.save(root, s)
    progress.render(root, s)
    json.dump({"merged": tid, "into": into, "sha": sha, "head": worktree.git(root, "rev-parse", "HEAD").strip(),
               "report": task["report_path"]}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
