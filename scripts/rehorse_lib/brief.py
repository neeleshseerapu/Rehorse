#!/usr/bin/env python3
"""The verifier's brief: what the independent verifier is allowed to see, decided in one place.

The spec, `git diff base_sha..HEAD`, the last test output, the existing tests the change rewrote and (from round 2)
the verifier's own earlier findings — never the implementer's transcript, its step summaries, PROGRESS.md or an
earlier report. Written to .rehorse/verify/<id>-round<n>.md so the orchestrator hands over a path, not a payload it
could edit on the way past. This is also where the verifier's one writable path is derived (from the diff, so a
workspace runner will collect it) and recorded in state, so every later caller names the same file.
"""
import os

import progress
import report
import testcmd
import worktree

from rehorse_lib import verdict

DIFF_CAP = 200000


def write(root, task):
    """Write the brief and return the subagent prompt (which names it)."""
    wt, tid, n = progress.wt_path(root, task), task["id"], task.get("verify_round", 0) + 1
    try:
        spec = open(os.path.join(wt, "REHORSE_SPEC.md")).read()
    except OSError:
        spec = "(no REHORSE_SPEC.md in the worktree)"
    diff = worktree.diff(root, tid, task["base_sha"]) if task["base_sha"] else ""
    if len(diff) > DIFF_CAP:
        diff = diff[:DIFF_CAP] + "\n... (diff truncated at %d characters)" % DIFF_CAP
    vfile = task["verify_file"] = testcmd.verify_file(task, wt, testcmd.diff_paths(diff))
    lines = ["# Rehorse verifier brief: %s, round %d" % (tid, n), "", "Worktree: %s" % wt,
             "Test command: cd %s && %s" % (wt, task["test_cmd"]), "The only file you may write: %s/%s" % (wt, vfile), "",
             "## Spec (REHORSE_SPEC.md)", "", spec.strip(), "", "## Diff (base %s..HEAD)" % (task["base_sha"] or "")[:7], "",
             "```diff", diff.strip() or "(no commits)", "```", "", "## Last test output", "", "```",
             ((task.get("last_test_run") or {}).get("output") or "(none recorded)").strip(), "```", "", *report.changes_block(task), ""]
    for v in task.get("verify_history") or []:
        lines += ["## Round %d: your earlier verdict was %s; check whether each finding is fixed" % (v["round"], v["verdict"].upper()),
                  "", report.findings_text(v), ""]
    path = os.path.join(root, ".rehorse", "verify", "%s-round%d.md" % (tid, n))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return ("Rehorse verify, round %d of %d, task %s.\nRead %s first: it holds the spec, the diff and the last test output. "
            "That is all you get; do not read rehorse-reports/ or PROGRESS.md.\nWorktree: %s. The only file you may write: %s/%s "
            "(any other edit is denied).\nTest command: cd %s && %s   (run it even if you add no test; only runs made there count).\n"
            "Commit your file if you wrote one: cd %s && git add -A && git commit -m \"verify: round %d tests for %s\"\n"
            "End your reply with the JSON block your instructions describe. Fix nothing.\n"
            % (n, verdict.MAX_ROUNDS, tid, path, wt, wt, vfile, wt, task["test_cmd"], wt, n, tid))
