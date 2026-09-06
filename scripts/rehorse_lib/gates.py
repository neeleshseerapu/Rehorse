#!/usr/bin/env python3
"""The evidence each phase transition must show, kept out of state.py so both can grow without crowding the line cap.

One function, called by state.advance() and by nothing else: red before implement, every acceptance criterion mapped
to a new test and no existing test rewritten unasked, a recorded verdict before the report. A gate returns the reason
it objects, in words aimed at the model that must satisfy it, or None to let the transition through.
"""


def gate(task, to, root=None):
    """Evidence a transition needs, or None: red before implement (a failing new test, or a failed build) and, given a root to
    read the spec from, every criterion mapped to a new test and no existing test rewritten unasked (coverage.py); a verdict before report."""
    r = task.get("red_check") or {"passed": 0, "failed": 0}
    if (task["phase"], to) == ("tests", "implement") and not (task.get("red_kind") == "build_failed" or r.get("new_failed", 0)):
        return ("no red run recorded; run the test command inside the worktree after the tests are written (at least one must fail)"
                if not task.get("red_check") else "the red run ran 0 tests; fix test discovery and run it again" if not r["passed"] + r["failed"] else
                "nothing failed in the red run: tests that pass before the feature exists test nothing; make at least one fail" if not r["failed"] else
                "no new failure: the %d failing test(s) also fail at baseline; write a test that fails because the feature is missing" % r["failed"])
    if (task["phase"], to) == ("tests", "implement") and root:
        import coverage  # lazy: the SessionStart path must not pay for git
        un, rewritten = coverage.uncovered(root, task), coverage.undeclared_changes(root, task, task.get("expected_test_changes") or [])
        return ("acceptance criteria without a new test: %s" % "; ".join(un) if un else
                "existing test(s) changed with no reason recorded: %s" % ", ".join(rewritten) if rewritten else None)
    if (task["phase"], to) == ("verify", "report") and not task.get("verifier"):
        return "no verifier verdict recorded; run `verify.py brief` and spawn the rehorse-verifier subagent with its output"
