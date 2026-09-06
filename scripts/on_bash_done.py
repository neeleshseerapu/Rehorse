#!/usr/bin/env python3
"""PostToolUse + PostToolUseFailure hook for Bash: record a real test run against the current edit_seq.

A run counts only if the command runs the task's test runner (not --collect-only/--version/--help), it ran inside
the task's worktree, and the output parses to the runner's own summary line (grep hits never do). A passing run
arrives as PostToolUse (tool_response.stdout/stderr); a failing one as PostToolUseFailure (error). By phase:
spec -> baseline with the failing test ids (0 tests => needs-attention), tests -> red_check with new_failed (failing ids that
were not failing at baseline; counts with ids_unavailable when the runner printed none), red_kind ("build_failed" when the
output shows a compiler error or fewer tests ran than at baseline: the new tests reference symbols that do not exist yet)
and weak_tests (new tests that already pass and are not marked `# rehorse: guard`; a warning, not a gate; guards are recorded
in task["guards"] and a failing guard is not red either), verify -> verify_run, always -> last_test_run.

A run narrowed to part of the suite (paths, node ids, -k / -m: testcmd.scope) is none of that. It goes to
diagnostic_runs, and only there: a slice of the suite cannot show red, cannot show green, and must not release the Stop
guard, because "the tests I was looking at pass" is exactly the claim a rehearsal exists to disbelieve.
"""
import datetime
import json
import os
import sys

import coverage
import report
import state
import testcmd
import worktree

MAX_DIAGNOSTIC = 20  # the report shows a count; keeping every one of them would grow state.json without telling anyone more


def note(hook, text):
    json.dump({"hookSpecificOutput": {"hookEventName": hook["hook_event_name"], "additionalContext": "REHORSE: " + text}},
              sys.stdout)
    return 0


def red_by_ids(red, ids, base, guards):
    """Fill red['new_failed'] (and new_failing / preexisting / failing_guards / ids_unavailable): red means a failure the
    baseline did not have and that is not a guard."""
    base_ids = base.get("failing") if base.get("failed") else []  # a green baseline needs no ids
    red["failing_guards"] = sorted(set(ids or []) & set(guards))
    if ids is not None and base_ids is not None:
        new = sorted(set(ids) - set(base_ids) - set(guards))
        red.update(new_failing=new, new_failed=len(new), preexisting=len(set(ids) & set(base_ids)))
        note = ""
    else:
        red.update(new_failed=max(0, red["failed"] - base["failed"]), preexisting=min(base["failed"], red["failed"]), ids_unavailable=True)
        note = "; WARNING: no test ids in the runner output, judged by counts"
    return "%d new failing test(s)%s%s%s%s." % (
        red["new_failed"], "; %d failing at baseline (ignored)" % red["preexisting"] if red["preexisting"] else "",
        "; %d guard(s) failing (a guard is expected to pass and is not red)" % len(red["failing_guards"]) if red["failing_guards"] else "",
        " (the failures also fail at baseline; write a test that fails because the feature is missing)" if red["preexisting"] and not red["new_failed"] else "", note)


def diagnostic(root, s, task, hook, counts, command, wt):
    """A narrowed run: recorded so the report can say how many there were, and nowhere else. No output is kept -- the
    verifier and the report read last_test_run, and a slice's output there would be a slice presented as the suite."""
    runs = (task.get("diagnostic_runs") or [])[-(MAX_DIAGNOSTIC - 1):]
    task["diagnostic_runs"] = runs + [dict(counts, at=datetime.datetime.now().isoformat(timespec="seconds"),
                                           after_edit_seq=task["edit_seq"], command=command)]
    state.save(root, s)
    return note(hook, "diagnostic run recorded (%d passed, %d failed): this command runs part of the suite, so it is not a "
                      "test run — it cannot show red or green and does not let the turn end. Run `cd %s && %s` for that."
                      % (counts["passed"], counts["failed"], wt, task["test_cmd"]))


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
    counts, broken, ids = testcmd.parse_counts(text), testcmd.build_failed(text), testcmd.failing_ids(text)
    if counts is None:
        if not broken:
            return 0
        counts = {"passed": 0, "failed": 0}  # the build failed before any test ran; the attempt still counts as a run
    if testcmd.scope(command, task["test_cmd"]) == "partial":
        return diagnostic(root, s, task, hook, counts, command, wt)
    task["last_test_run"] = dict(counts, at=datetime.datetime.now().isoformat(timespec="seconds"), build_failed=broken,
                                 after_edit_seq=task["edit_seq"], command=command, output=text[-4000:])  # tail: verifier + report
    msg = "recorded test run: %d passed, %d failed%s (edit_seq %d)." % (
        counts["passed"], counts["failed"], ", build failed" if broken else "", task["edit_seq"])
    if task["phase"] == "spec":
        task["baseline"] = dict(counts, failing=ids)
        if counts["failed"]:
            msg += " %d failing at baseline (ignored in the red check)." % counts["failed"]
        if counts["passed"] + counts["failed"] == 0:
            state.advance(s, task["id"], state.ATTENTION, reason="baseline ran 0 tests with `%s`" % command)
            msg = ("baseline ran 0 tests, so task %s moved to needs-attention (report: %s). Fix the test command or "
                   "test discovery, then resume via /rehorse:status." % (task["id"], report.write_stop(root, s, task)))
    elif task["phase"] == "tests" and task.get("tests_sha"):  # a revision round re-entered this phase; the red it earned stands
        msg += " red stands from the first tests phase (%s); this run is a revision." % task["tests_sha"][:7]
    elif task["phase"] == "tests":
        task["red_check"] = dict(counts)
        base = task.get("baseline") or {"passed": 0, "failed": 0}
        added = counts["passed"] + counts["failed"] - base["passed"] - base["failed"]
        task["guards"] = guards = coverage.guards(wt, coverage.changed_tests(root, task))
        red_note = red_by_ids(task["red_check"], ids, base, guards)
        if broken or added < 0:
            task["red_kind"], task["weak_tests"] = "build_failed", 0
            msg += " red: build failed (new tests reference symbols that don't exist yet); that counts as red."
        else:
            task["red_kind"] = "tests"
            passing_guards = len(guards) - len(task["red_check"]["failing_guards"])
            task["weak_tests"] = max(0, min(added, counts["passed"] - base["passed"]) - passing_guards)
            msg += " red: " + red_note
        if guards or task["weak_tests"]:
            msg += " %s%d guard(s) expected to pass; %d unexpected pass(es)%s." % (
                "WARNING: " if task["weak_tests"] else "", len(guards), task["weak_tests"],
                " that may not test anything; make them fail first, or mark regression guards with `# rehorse: guard`" if task["weak_tests"] else "")
    elif task["phase"] == "verify":
        task["verify_run"] = dict(counts)
    state.save(root, s)
    return note(hook, msg)


if __name__ == "__main__":
    sys.exit(main())
