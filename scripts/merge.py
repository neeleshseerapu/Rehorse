#!/usr/bin/env python3
"""merge.py [task-id]: the only code path that writes to the user's branch (with discard.py for removal).

Needs a user grant, ~/.rehorse/merge-<id>, which only the UserPromptSubmit hook mints when the user types
/rehorse:merge; the grant is consumed first, so one prompt buys one attempt. Fast-forwards the rehearsal branch into
the current branch when possible, otherwise makes a merge commit; a conflict is aborted and the rehearsal kept.
On success the worktree and branch are removed and the task becomes `merged`. Prints JSON, including how many of the
verifier's tests (rehorse_verify_* files on the branch) come along, so the user knows what the merge adds to their suite.
"""
import json
import os
import re
import subprocess
import sys

import grant
import progress
import state
import worktree


TEST_RE = re.compile(r"^\s*(?:def test_|func Test|func test|#\[test\]|(?:it|test)\()", re.M)


def verifier_tests(root, branch):
    """(count, files): tests in the verifier's files on the rehearsal branch (pytest, go, swift, rust, vitest/jest shapes)."""
    files = [f for f in worktree.git(root, "ls-tree", "-r", "--name-only", branch).split() if "rehorse_verify_" in os.path.basename(f)]
    return sum(len(TEST_RE.findall(worktree.git(root, "show", "%s:%s" % (branch, f)))) for f in files), files


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
    n_verifier, verifier_files = verifier_tests(root, task["branch"])
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
               "report": task["report_path"], "verifier_tests": n_verifier, "verifier_files": verifier_files}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
