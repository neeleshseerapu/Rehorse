#!/usr/bin/env python3
"""SubagentStop hook for rehorse-step agents (phases setup, tests, implement); matched on the agent type in hooks.json and here.

In order: a reply line starting `CONTRADICTS SPEC:` -> the tests phase when it names a test id, else needs-attention
(see contradicts()); edits newer than the last test run -> block, naming the command; uncommitted worktree -> block,
naming the commit; in the tests phase, no coverage block or an acceptance criterion with no new test -> block, naming
them (the mapping is recorded as task["coverage"]), and an existing test changed with no reason in the reply -> block,
naming it (declared ones become task["expected_test_changes"]); else the plan step is marked done with the reply's
first two lines and the commit; when HEAD did not move since an earlier step, the step is recorded as satisfied_by that
step (no edits) rather than as work. The 8th consecutive block -> needs-attention.
"""
import json
import sys

import coverage
import guard_stop
import progress
import state
import worktree

from rehorse_lib import verdict as vd

AGENT = "rehorse-step"
COVERAGE_HINT = ('end your reply with a ```json block {"coverage": [{"criterion": "<acceptance criterion or its number>", '
                 '"ref": "<test file>::<test name>"}]} mapping every acceptance criterion in REHORSE_SPEC.md to a test you added')
CHANGED_HINT = ('Either restore it, or, if REHORSE_SPEC.md says the behaviour it pins is wrong, add to the same json block '
                '"expected_test_changes": [{"test": "<file>::<test>", "why": "<one line: which criterion says so>"}] for each')


def contradicts(root, s, task, c):
    """A step says an existing test contradicts the spec.

    From `implement` a named test buys the same trip a verifier `pins_bug` finding buys: back to `tests`, where a
    rewrite is a declared decision, at the cost of one round against the same cap. The step agent is not granted the
    edit -- it is granted a second opinion. Everywhere else the task stops for the user: in `tests` that second opinion
    has come back disagreeing, and both claims belong in the banner; with no test id there is nothing to route."""
    n = task.get("verify_round", 0) + 1
    if task["phase"] == "implement" and c["test"] and n < vd.MAX_ROUNDS:
        return revise(root, s, task, c, n)
    return guard_stop.attention(root, s, task, c["line"] + stopped_because(task, c, n))


def stopped_because(task, c, n):
    """Why this contradiction stopped the task instead of buying a round trip; appended to the needs-attention banner."""
    prior = [r["why"] for h in task.get("verify_history") or [] for r in h.get("revision") or []]
    if task["phase"] == "tests":
        return " | THE CLAIM IT WAS SENT TO ANSWER: %s" % prior[-1] if prior else ""
    if task["phase"] != "implement":
        return ""
    return (" | no test id named, so it could not be routed to the tests phase" if not c["test"] else
            " | round %d of %d: the trips back to the tests phase are spent" % (n, vd.MAX_ROUNDS))


def revise(root, s, task, c, n):
    """Route to `tests` and say so. The open plan step stays open, to resume at once the test question is settled."""
    task["verify_history"] = (task.get("verify_history") or []) + [vd.contradiction_round(c, n)]
    task.update(verify_round=n, stop_blocks=0)
    state.advance(s, task["id"], "tests")
    state.save(root, s)
    progress.render(root, s)
    json.dump({"systemMessage": "REHORSE: step %d says %s pins behaviour the spec calls a bug. Back to tests (round %d of %d) for a "
                                "second opinion: it rewrites the test with a declared reason, or replies CONTRADICTS SPEC: and the "
                                "task stops for you. Then `state.py advance implement` and resume at that step."
                                % (task["step"] + 1, c["test"], n, vd.MAX_ROUNDS)}, sys.stdout)
    return 0


def main():
    hook = json.load(sys.stdin)
    root, s, task = state.active(hook.get("cwd"))
    if not task or task["phase"] not in ("setup", "tests", "implement") or (hook.get("agent_type") or "").split(":")[-1] != AGENT:
        return 0
    wt, plan, i = progress.wt_path(root, task), task["plan"], task["step"]
    message = hook.get("last_assistant_message") or ""
    said = [l.strip() for l in message.splitlines() if l.strip()]
    contra = vd.contradiction(message)
    if contra:  # a test (the verifier's included) disagrees with the spec; the implementer never works around it
        return contradicts(root, s, task, contra)
    title = plan[i]["title"] if task["phase"] == "implement" and i < len(plan) else None
    pending = task["edit_seq"] - (task.get("last_test_run") or {}).get("after_edit_seq", 0)
    if pending > 0 and task["test_cmd"]:
        return guard_stop.block(root, s, task, "%d edit(s) since the last recorded test run. Run `cd %s && %s`, then stop again."
                                % (pending, wt, task["test_cmd"]), "step-done")
    dirty = worktree.dirty(root, task["id"])
    if dirty:
        msg = "step %d: %s" % (i + 1, title) if title else ("setup: test harness for %s" if task["phase"] == "setup" else "tests: red for %s") % task["id"]
        return guard_stop.block(root, s, task, "uncommitted changes in the worktree (%s). Run `cd %s && git add -A && git commit -m \"%s\"`, "
                                "then stop again." % (", ".join(dirty[:5]), wt, msg), "step-done")
    if task["phase"] == "tests":
        mapping = coverage.entries(coverage.json_block(message))
        if mapping is None:
            return guard_stop.block(root, s, task, "no coverage block found; %s, then stop again." % COVERAGE_HINT, "step-done")
        task["coverage"] = mapping
        un = coverage.uncovered(root, task)
        if un:
            return guard_stop.block(root, s, task, "acceptance criteria without a new test: %s. Add tests for them (test paths only), run "
                                    "the test command, commit, and stop again with the updated coverage block." % "; ".join(un), "step-done")
        declared = coverage.declared_changes(coverage.json_block(message))
        fresh = {d["test"] for d in declared}  # a revision round re-enters this phase; reasons already recorded stand,
        declared += [d for d in task.get("expected_test_changes") or [] if d["test"] not in fresh]  # a new one wins
        undeclared = coverage.undeclared_changes(root, task, declared)
        if undeclared:  # rewriting a test the repo already had is a spec decision, not a tests-phase liberty
            return guard_stop.block(root, s, task, "existing test(s) changed with no reason given: %s. %s, then run the test command, "
                                    "commit, and stop again." % (", ".join(undeclared), CHANGED_HINT), "step-done")
        task["expected_test_changes"] = [d for d in declared if d["test"] in set(coverage.changed_existing_tests(root, task))]
    task["stop_blocks"] = 0
    if title:
        head = worktree.git(wt, "rev-parse", "HEAD").strip()[:7]
        by = next((n for n, p in enumerate(plan[:i], 1) if p["done"] and p["commit"] == head and not p.get("satisfied_by")), None)
        plan[i].update(done=True, summary="\n".join(said[:2]), commit=head, satisfied_by=by)
        task["step"] = i + 1
    state.save(root, s)
    progress.render(root, s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
