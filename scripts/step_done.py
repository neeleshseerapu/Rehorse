#!/usr/bin/env python3
"""SubagentStop hook for rehorse-step agents (phases setup, tests, implement); matched on the agent type in hooks.json and here.

In order: a reply line starting `CONTRADICTS SPEC:` -> needs-attention (the user decides); edits newer than the last test
run -> block, naming the command; uncommitted worktree -> block, naming the commit; in the tests phase, no coverage block
or an acceptance criterion with no new test -> block, naming them (the mapping is recorded as task["coverage"]), and an
existing test changed with no reason in the reply -> block, naming it (declared ones become task["expected_test_changes"]); else the
plan step is marked done with the reply's first two lines and the commit; when HEAD did not move since an earlier step,
the step is recorded as satisfied_by that step (no edits) rather than as work. The 8th consecutive block -> needs-attention.
"""
import json
import sys

import coverage
import guard_stop
import progress
import state
import worktree

AGENT = "rehorse-step"
COVERAGE_HINT = ('end your reply with a ```json block {"coverage": [{"criterion": "<acceptance criterion or its number>", '
                 '"ref": "<test file>::<test name>"}]} mapping every acceptance criterion in REHORSE_SPEC.md to a test you added')
CHANGED_HINT = ('Either restore it, or, if REHORSE_SPEC.md says the behaviour it pins is wrong, add to the same json block '
                '"expected_test_changes": [{"test": "<file>::<test>", "why": "<one line: which criterion says so>"}] for each')


def main():
    hook = json.load(sys.stdin)
    root, s, task = state.active(hook.get("cwd"))
    if not task or task["phase"] not in ("setup", "tests", "implement") or (hook.get("agent_type") or "").split(":")[-1] != AGENT:
        return 0
    wt, plan, i = progress.wt_path(root, task), task["plan"], task["step"]
    message = hook.get("last_assistant_message") or ""
    said = [l.strip() for l in message.splitlines() if l.strip()]
    contra = next((l for l in said if l.startswith("CONTRADICTS SPEC:")), None)
    if contra:  # a test (the verifier's included) disagrees with the spec: the user decides, the implementer does not work around it
        guard_stop.attention(root, s, task, contra)
        progress.render(root, s)
        return 0
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
