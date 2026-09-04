#!/usr/bin/env python3
"""PostToolUse + PostToolUseFailure hook for Bash: record a real test run against the current edit_seq.

A run counts only if the command runs the task's test runner (not --collect-only/--version/--help), it ran inside
the task's worktree, and the output parses to the runner's own summary line (grep hits never do). A passing run
arrives as PostToolUse (tool_response.stdout/stderr); a failing one as PostToolUseFailure (error). By phase:
spec -> baseline (0 tests => needs-attention), tests -> red_check plus red_kind ("build_failed" when the output shows a
compiler error or fewer tests ran than at baseline: the new tests reference symbols that do not exist yet) and
weak_tests (new tests that already pass; a warning, not a gate), verify -> verify_run (the verifier's own run), always -> last_test_run.
"""
import datetime
import json
import os
import sys

import state
import testcmd
import worktree


def note(hook, text):
    json.dump({"hookSpecificOutput": {"hookEventName": hook["hook_event_name"], "additionalContext": "REHORSE: " + text}},
              sys.stdout)
    return 0


def main():
    hook = json.load(sys.stdin)
    root, s, task = state.active(hook.get("cwd"))
    command = (hook.get("tool_input") or {}).get("command") or ""
    if not task or not task.get("test_cmd") or not testcmd.is_test_command(command, task["test_cmd"]):
        return 0
    wt = os.path.realpath(os.path.join(root, task["worktree"]))
    if not worktree.contains(wt, testcmd.effective_cwd(command, hook.get("cwd") or os.getcwd())):
        return note(hook, "test run ignored: it did not run inside the worktree. Run `cd %s && %s`." % (wt, task["test_cmd"]))
    resp = hook.get("tool_response") or {}
    text = hook.get("error") or "\n".join(filter(None, [resp.get("stdout"), resp.get("stderr")]))  # jest reports on stderr
    counts, broken = testcmd.parse_counts(text), testcmd.build_failed(text)
    if counts is None:
        if not broken:
            return 0
        counts = {"passed": 0, "failed": 0}  # the build failed before any test ran; the attempt still counts as a run
    task["last_test_run"] = dict(counts, at=datetime.datetime.now().isoformat(timespec="seconds"), build_failed=broken,
                                 after_edit_seq=task["edit_seq"], command=command, output=text[-4000:])  # tail: verifier + report
    msg = "recorded test run: %d passed, %d failed%s (edit_seq %d)." % (
        counts["passed"], counts["failed"], ", build failed" if broken else "", task["edit_seq"])
    if task["phase"] == "spec":
        task["baseline"] = dict(counts)
        if counts["passed"] + counts["failed"] == 0:
            state.advance(s, task["id"], state.ATTENTION, reason="baseline ran 0 tests with `%s`" % command)
            msg = ("baseline ran 0 tests, so task %s moved to needs-attention. Fix the test command or test discovery, "
                   "then resume via /rehorse:status." % task["id"])
    elif task["phase"] == "tests":
        task["red_check"] = dict(counts)
        base = task.get("baseline") or {"passed": 0, "failed": 0}
        added = counts["passed"] + counts["failed"] - base["passed"] - base["failed"]
        if broken or added < 0:
            task["red_kind"], task["weak_tests"] = "build_failed", 0
            msg += " red: build failed (new tests reference symbols that don't exist yet); that counts as red."
        else:
            task["red_kind"] = "tests"
            task["weak_tests"] = max(0, min(added, counts["passed"] - base["passed"]))
        if task["weak_tests"]:
            msg += (" WARNING: %d new test(s) passed before implementation and may not test anything; make them fail "
                    "first or say why they cannot." % task["weak_tests"])
    elif task["phase"] == "verify":
        task["verify_run"] = dict(counts)
    state.save(root, s)
    return note(hook, msg)


if __name__ == "__main__":
    sys.exit(main())
