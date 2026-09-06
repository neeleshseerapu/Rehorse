#!/usr/bin/env python3
"""Verifier plumbing. `verify.py brief` writes .rehorse/verify/<id>-round<n>.md and prints the prompt for the
rehorse-verifier subagent, so what the verifier sees is decided in rehorse_lib/brief.py, not by the orchestrator.
`verify.py --verdict` is the SubagentStop hook for that agent: it blocks the stop until the verifier ran the test command
after its last edit, committed its test file, and ended its reply with the JSON verdict block; then it records the verdict
in state. The orchestrator never copies a verdict by hand, so it cannot soften one, and a `fail` whose findings cite no
acceptance criterion is recorded as `concerns`: a stop points at the spec, not at the verifier's taste. A `fail`, or a failing
verifier test, sends the task back to implement with the findings as plan steps (the verifier's file is then locked like every
test); a finding that says an existing test pins the very behaviour the spec calls a bug goes back to `tests` instead,
where rewriting a test is a declared decision. The third failing round sets needs-attention whichever way it would have gone. The report shows the round count and earlier rounds' findings.
The verdict vocabulary, the parser and the round-trip steps live in rehorse_lib/verdict.py.
"""
import datetime
import json
import os
import sys

import guard_stop
import progress
import state
import testcmd
import worktree

from rehorse_lib import brief, verdict as vd

AGENT = "rehorse-verifier"
MAX_ROUNDS = vd.MAX_ROUNDS


def verdict(hook):
    root, s, task = state.active(hook.get("cwd"))
    if not task or task["phase"] != "verify" or (hook.get("agent_type") or "").split(":")[-1] != AGENT:
        return 0
    wt, tid, n = progress.wt_path(root, task), task["id"], task.get("verify_round", 0) + 1
    pending = task["edit_seq"] - (task.get("last_test_run") or {}).get("after_edit_seq", 0)
    if pending > 0 or not task.get("verify_run"):
        return guard_stop.block(root, s, task, "the verifier must run the test command%s: `cd %s && %s`, then stop again."
                                % (" after its last edit" if pending > 0 else "", wt, task["test_cmd"]), "verify")
    dirty = worktree.dirty(root, tid)
    if dirty:
        return guard_stop.block(root, s, task, "uncommitted changes in the worktree (%s). Run `cd %s && git add -A && git commit -m "
                                "\"verify: round %d tests for %s\"`, then stop again." % (", ".join(dirty[:5]), wt, n, tid), "verify")
    v = vd.parse(hook.get("last_assistant_message") or "")
    if not v:
        return guard_stop.block(root, s, task, "no verdict found. End your reply with exactly one ```json block of this shape "
                                "(verdict must be pass|concerns|fail): %s" % vd.SHAPE, "verify")
    run, rev = task["verify_run"], vd.revisions(v)
    task.update(verify_round=n, stop_blocks=0, verifier=dict(
        v, round=n, tests=run, at=datetime.datetime.now().isoformat(timespec="seconds"),
        revision=[{"test": f["test"], "why": f["description"]} for f in rev]))
    msg = "REHORSE: verifier round %d: %s%s, %d finding(s); its run: %d passed, %d failed." % (
        n, v["verdict"].upper(), " (fail recorded as concerns: no finding cited a criterion)" if v["downgraded"] else "", len(v["findings"]), run["passed"], run["failed"])
    failing = v["verdict"] == "fail" or run["failed"] > 0
    if failing and n >= MAX_ROUNDS:
        why = "verifier failed %d rounds; round %d found: %s" % (n, n, "; ".join(f["description"] for f in v["findings"][:3]) or "its tests fail")
        guard_stop.attention(root, s, task, why)  # prints the systemMessage; the verdict stays recorded for the report
        progress.render(root, s)
        return 0
    if failing:
        steps = vd.round_trip_steps(v, run, testcmd.verify_file(task, wt), n)
        state.advance(s, tid, "tests" if rev else "implement")  # archives the verdict into verify_history and clears verify_run
        task["plan"] += [{"title": t, "done": False, "summary": None, "commit": None} for t in steps]
        msg += (" Back to tests to revise %s (an existing test pinning behaviour the spec calls a bug): rewrite it and declare "
                "why, then implement" % ", ".join(f["test"] for f in rev) if rev else " Back to implement") + \
               " with %d new step(s); round %d of %d follows once they are green." % (len(steps), n + 1, MAX_ROUNDS)
    state.save(root, s)
    progress.render(root, s)
    json.dump({"systemMessage": msg}, sys.stdout)
    return 0


def main(argv):
    if argv[:1] == ["--verdict"]:
        return verdict(json.load(sys.stdin))
    root, s, task = state.active(os.getcwd())
    if not task:
        sys.exit("verify.py: no active task")
    if argv[:1] != ["brief"]:
        sys.exit(__doc__)
    if task["phase"] != "verify":
        sys.exit("verify.py brief: task %s is in phase %s; the brief is written in phase verify." % (task["id"], task["phase"]))
    sys.stdout.write(brief.write(root, task))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
