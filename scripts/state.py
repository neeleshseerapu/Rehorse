#!/usr/bin/env python3
"""Rehorse state: <repo>/.rehorse/state.json is the single source of truth; phases move only through advance(), which
gates tests -> implement on a red run. CLI: --summary (SessionStart) | new "<title>" [--date D] | advance <phase> [--task ID] [--reason R] | show"""
import datetime
import json
import os
import sys
import tempfile

PHASES = ["setup", "spec", "tests", "implement", "verify", "report"]  # setup only when no test command was detected
TERMINAL = ("merged", "discarded")
ATTENTION = "needs-attention"
STATE_REL = os.path.join(".rehorse", "state.json")


def find_root(start):
    """Main checkout that owns .rehorse/. Inside a worktree (.../.rehorse/worktrees/<id>/...) that is the parent of .rehorse."""
    p = os.path.realpath(start)
    parts = p.split(os.sep)
    if ".rehorse" in parts:
        return os.sep.join(parts[:parts.index(".rehorse")]) or os.sep
    while not os.path.exists(os.path.join(p, ".git")) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p if os.path.exists(os.path.join(p, ".git")) else None


def empty():
    return {"active_task": None, "tasks": {}}


def load(root):
    path = os.path.join(root, STATE_REL)
    return json.load(open(path)) if os.path.exists(path) else empty()


def active(cwd):
    """(root, state, task) for the hook scripts. task is None when Rehorse is dormant here (no repo or no active task)."""
    root = find_root(cwd or os.getcwd())
    s = load(root) if root else empty()
    return root, s, (s["tasks"].get(s["active_task"]) if s["active_task"] else None)


def save(root, state):
    """Atomic write: a hook killed mid-write must never leave a half-written state file."""
    path = os.path.join(root, STATE_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix="state.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def new_task(state, tid):
    base, n = tid, 1
    while tid in state["tasks"]:  # re-rehearsal: t-...-r2, -r3
        n += 1
        tid = "%s-r%d" % (base, n)
    task = {"id": tid, "phase": "spec", "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "worktree": ".rehorse/worktrees/" + tid, "branch": "rehorse/" + tid, "base_sha": None, "test_cmd": None, "test_paths": [],
            "baseline": None, "red_check": None, "red_kind": None, "weak_tests": 0, "last_test_run": None, "tests_sha": None, "summary": None,
            "edit_seq": 0, "stop_blocks": 0, "attention": None, "plan": [], "step": 0, "report_path": None, "linked_deps": [],
            "verifier": None, "verify_round": 0, "verify_run": None, "verify_history": [], "coverage": []}
    state["tasks"][tid] = task
    state["active_task"] = tid
    return task


def gate(task, to, root=None):
    """Evidence a transition needs, or None: red before implement (a failing new test, or a failed build) and, given a root to
    read the spec from, every acceptance criterion mapped to a new test (coverage.py); a verdict before report."""
    r = task.get("red_check") or {"passed": 0, "failed": 0}
    if (task["phase"], to) == ("tests", "implement") and not (task.get("red_kind") == "build_failed" or r.get("new_failed", 0)):
        return ("no red run recorded; run the test command inside the worktree after the tests are written (at least one must fail)"
                if not task.get("red_check") else "the red run ran 0 tests; fix test discovery and run it again" if not r["passed"] + r["failed"] else
                "nothing failed in the red run: tests that pass before the feature exists test nothing; make at least one fail" if not r["failed"] else
                "no new failure: the %d failing test(s) also fail at baseline; write a test that fails because the feature is missing" % r["failed"])
    if (task["phase"], to) == ("tests", "implement") and root:
        import coverage  # lazy: the SessionStart path must not pay for git
        if coverage.uncovered(root, task):
            return "acceptance criteria without a new test: %s" % "; ".join(coverage.uncovered(root, task))
    if (task["phase"], to) == ("verify", "report") and not task.get("verifier"):
        return "no verifier verdict recorded; run `verify.py brief` and spawn the rehorse-verifier subagent with its output"


def advance(state, tid, to, reason=None, root=None):
    """The only legal phase transitions. Raises ValueError naming the allowed next phase(s) or the gate that objected."""
    task = state["tasks"][tid]
    cur = task["phase"]
    allowed = ([] if cur in TERMINAL else [task["attention"]["prior_phase"], "discarded"] if cur == ATTENTION else
               PHASES[PHASES.index(cur) + 1:][:1] + ["discarded", ATTENTION] + {"report": ["merged"], "verify": ["implement"]}.get(cur, []))
    if to not in allowed:
        raise ValueError("cannot advance %s from %r to %r; allowed: %s" % (tid, cur, to, ", ".join(allowed) or "none"))
    why = gate(task, to, root)
    if why:
        raise ValueError("cannot advance %s to %s: %s" % (tid, to, why))
    if (cur, to) == ("verify", "implement"):  # round-trip: the verdict is archived, the next round must earn a new one
        task["verify_history"] = task.get("verify_history", []) + [task["verifier"]]
        task["verifier"] = task["verify_run"] = None
    task["attention"] = {"reason": reason or "unspecified", "prior_phase": cur} if to == ATTENTION else None
    task["stop_blocks"], task["phase"] = (0 if cur == ATTENTION else task["stop_blocks"]), to  # a resumed task restarts its block count
    state["active_task"] = None if to in TERMINAL and state["active_task"] == tid else state["active_task"]
    return task


def summary(state):
    """One line for SessionStart injection: enough to resume, never a transcript."""
    tid = state["active_task"]
    if not tid:
        return "REHORSE: no active task."
    t = state["tasks"][tid]
    if t["phase"] == ATTENTION:
        return "REHORSE: task %s NEEDS ATTENTION (was in %s): %s. Run /rehorse:status." % (tid, t["attention"]["prior_phase"], t["attention"]["reason"])
    parts = ["REHORSE: active task %s, phase %s" % (tid, t["phase"])]
    parts += ["step %d/%d" % (min(t["step"] + 1, len(t["plan"])), len(t["plan"]))] if t["plan"] else []
    parts += ["last tests %(passed)d passed, %(failed)d failed" % t["last_test_run"]] if t["last_test_run"] else []
    return ", ".join(parts) + ". Read rehorse-reports/PROGRESS.md before acting."


def main(argv):
    if argv[:1] == ["--summary"]:
        json.dump({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": summary(active(json.load(sys.stdin).get("cwd"))[1])}}, sys.stdout)
        return 0
    root, state, _ = active(os.getcwd())
    if not root:
        sys.exit("state.py: not inside a git repository")
    opts = {a[2:]: argv[i + 1] for i, a in enumerate(argv[:-1]) if a.startswith("--")}  # --key value
    tid = opts.get("task") or state["active_task"]
    if argv[0] == "new":
        import testcmd, worktree  # noqa: E401 (lazy: the SessionStart path must not pay for git)
        task = new_task(state, worktree.task_id(argv[1], opts.get("date")))
        task.update(worktree.create(root, task["id"]), **{k: v for k, v in (testcmd.detect(root) or {}).items() if k != "runner"})
        task["phase"] = "spec" if task["test_cmd"] else "setup"  # no runnable suite: build the harness inside the rehearsal first
        json.dump(task, sys.stdout, indent=2)
    elif argv[0] == "advance":
        try:
            advance(state, tid, argv[1], opts.get("reason"), root)
        except (ValueError, KeyError) as e:
            sys.exit("state.py: %s" % e)
    elif argv[0] == "show":
        json.dump(state["tasks"].get(tid) or state, sys.stdout, indent=2)
        return 0
    else:
        sys.exit(__doc__)
    save(root, state)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
