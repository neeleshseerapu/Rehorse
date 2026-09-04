#!/usr/bin/env python3
"""PreToolUse hook for Read|Grep|Glob: the verifier's inputs are its brief and the worktree, nothing else.

Reads the hook JSON on stdin. Prints a deny decision, or nothing. Exits 0. Acts only when the call comes from the
rehorse-verifier subagent (agent_type) while a task is active. Allowed: paths inside the active worktree except its
rehorse-reports/ copy, and the briefs under <repo>/.rehorse/verify/. Denied with a reason: rehorse-reports/ (step
summaries, earlier reports), the rest of .rehorse/ (state.json, handoff.json), and anything outside the worktree.
A Grep/Glob with no `path` searches the tool's cwd, which is the main checkout unless the verifier cd'ed into the
worktree, so it is judged by that cwd.
"""
import json
import os
import sys

import state
import worktree

AGENT = "rehorse-verifier"


def check(root, task, path):
    """Denial reason, or None to allow."""
    wt = os.path.realpath(os.path.join(root, task["worktree"]))
    brief_dir = os.path.realpath(os.path.join(root, ".rehorse", "verify"))
    if worktree.contains(brief_dir, path) and path != brief_dir:
        return None
    if worktree.contains(wt, path) and not worktree.contains(os.path.join(wt, "rehorse-reports"), path):
        return None
    return ("the verifier reads only its brief (%s/) and the worktree (%s), never rehorse-reports/, .rehorse/ or the main "
            "checkout; what the implementer wrote about its own work is not evidence. Use a path under %s." % (brief_dir, wt, wt))


def main():
    hook = json.load(sys.stdin)
    if (hook.get("agent_type") or "").split(":")[-1] != AGENT:
        return 0
    root, _, task = state.active(hook.get("cwd"))
    if not task:
        return 0
    inp = hook.get("tool_input") or {}
    cwd = hook.get("cwd") or os.getcwd()
    target = inp.get("file_path") if hook.get("tool_name") == "Read" else (inp.get("path") or cwd)
    reason = check(root, task, os.path.realpath(os.path.join(cwd, target or cwd)))
    if reason:
        if hook.get("tool_name") != "Read" and not inp.get("path"):
            reason = "%s without a `path` searches %s; " % (hook["tool_name"], cwd) + reason
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                          "permissionDecisionReason": "REHORSE: " + reason}}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
