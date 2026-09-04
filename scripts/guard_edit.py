#!/usr/bin/env python3
"""PreToolUse hook for Edit|Write|MultiEdit: worktree isolation, phase path lock, orchestrator rule, edit_seq.

Reads the hook JSON on stdin. Prints a deny decision, or nothing (normal permission flow). Exits 0.
Rules, in order: no active task -> dormant; rehorse-reports/ -> always allowed (evidence trail, not code);
outside the worktree -> deny; phase `tests` -> test paths only; phase `implement` -> test paths locked and
main-thread (no agent_id) edits denied; phase `verify` -> only the verifier's own test file (testcmd.verify_file).
Every allowed edit inside the worktree bumps edit_seq.
"""
import json
import os
import re
import sys

import state
import testcmd
import worktree

REPORTS = "rehorse-reports/"
PLUGIN = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_HINT = "under a test dir or named test_*.py, *_test.py, conftest.py, *.test.ts"


def check(root, task, inside, rel, from_subagent):
    """Denial reason, or None to allow. `rel` is relative to the worktree when inside, else to the repo root."""
    wt = os.path.realpath(os.path.join(root, task["worktree"]))
    if not inside:
        if rel == ".rehorse" or rel.startswith(".rehorse/"):
            return (".rehorse/ is managed by Rehorse scripts and never edited directly. Change state with "
                    "`python3 %s/scripts/state.py ...`." % PLUGIN)
        target = wt if rel.startswith("..") else os.path.join(wt, rel)
        return "edits outside the active worktree are denied. Task %s rehearses in %s; edit %s instead." % (
            task["id"], wt, target)
    is_test = testcmd.is_test_path(rel, task.get("test_paths") or [])
    phase = task["phase"]
    if phase == "tests" and not is_test:
        return ("phase tests: only test files may be edited (%s). Write the failing tests first; %s is an implementation "
                "file and unlocks in the implement phase, after red_check." % (TEST_HINT, rel))
    if phase == "implement" and is_test:
        return ("phase implement: test paths are locked (%s). Edit implementation files only; if a test is wrong, say so "
                "in your step summary instead of changing it." % rel)
    if phase == "implement" and not from_subagent:
        return ("phase implement: the orchestrator does not edit files. Delegate this edit to a step subagent with the "
                "Agent tool; only %s may be edited directly." % REPORTS)
    if phase == "verify" and not (is_test and re.search(r"rehorse_verify_%s(?:[._]|$)" % re.escape(task["id"]), os.path.basename(rel))):
        return ("phase verify: the verifier fixes nothing and writes only its own tests. Write them to %s; every other "
                "file is locked until the report." % testcmd.verify_file(task, wt))
    return None


def main():
    hook = json.load(sys.stdin)
    root, s, task = state.active(hook.get("cwd"))
    if not task:
        return 0
    path = os.path.realpath((hook.get("tool_input") or {}).get("file_path") or "")
    wt = os.path.realpath(os.path.join(root, task["worktree"]))
    inside = worktree.contains(wt, path)
    rel = os.path.relpath(path, wt if inside else os.path.realpath(root)).replace(os.sep, "/")
    if rel.startswith(REPORTS):
        return 0
    reason = check(root, task, inside, rel, bool(hook.get("agent_id")))
    if reason:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                          "permissionDecisionReason": "REHORSE: " + reason}}, sys.stdout)
        return 0
    task["edit_seq"] += 1
    state.save(root, s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
