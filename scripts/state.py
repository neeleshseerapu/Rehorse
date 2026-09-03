#!/usr/bin/env python3
"""Rehorse state: <repo>/.rehorse/state.json is the single source of truth. Phases move only through advance().
Library (load/save/new_task/advance/summary) plus CLI:
  --summary (SessionStart hook: JSON in, additionalContext out) | new "<title>" [--date D] |
  advance <phase> [--task ID] [--reason R] | show [--task ID]
"""
import datetime
import json
import os
import re
import sys
import tempfile

PHASES = ["spec", "tests", "implement", "verify", "report"]
TERMINAL = ("merged", "discarded")
ATTENTION = "needs-attention"
STATE_REL = os.path.join(".rehorse", "state.json")


def find_root(start):
    """Main checkout that owns .rehorse/. Inside a worktree (.../.rehorse/worktrees/<id>/...) that is the parent of .rehorse."""
    p = os.path.realpath(start)
    parts = p.split(os.sep)
    if ".rehorse" in parts:
        return os.sep.join(parts[:parts.index(".rehorse")]) or os.sep
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def empty():
    return {"active_task": None, "tasks": {}}


def load(root):
    try:
        with open(os.path.join(root, STATE_REL)) as f:
            return json.load(f)
    except FileNotFoundError:
        return empty()


def save(root, state):
    """Atomic write: a hook killed mid-write must never leave a half-written state file."""
    path = os.path.join(root, STATE_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix="state.", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def task_id(title, date=None):
    date = date or datetime.date.today().strftime("%Y%m%d")
    words = re.sub(r"[^a-z0-9]+", " ", title.lower()).split()[:6]
    return "t-%s-%s" % (date, "-".join(words) or "task")


def new_task(state, tid):
    base, n = tid, 1
    while tid in state["tasks"]:  # re-rehearsal: t-...-r2, -r3
        n += 1
        tid = "%s-r%d" % (base, n)
    task = {
        "id": tid, "phase": PHASES[0], "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "worktree": ".rehorse/worktrees/" + tid, "branch": "rehorse/" + tid, "base_sha": None,
        "test_cmd": None, "test_paths": [], "baseline": None, "red_check": None, "last_test_run": None,
        "edit_seq": 0, "stop_blocks": 0, "attention": None, "plan": [], "step": 0,
        "verifier": None, "report_path": None,
    }
    state["tasks"][tid] = task
    state["active_task"] = tid
    return task


def advance(state, tid, to, reason=None):
    """The only legal phase transitions. Raises ValueError with the allowed next phase(s)."""
    task = state["tasks"][tid]
    cur = task["phase"]
    if cur in TERMINAL:
        allowed = []
    elif cur == ATTENTION:
        allowed = [task["attention"]["prior_phase"], "discarded"]
    else:
        allowed = PHASES[PHASES.index(cur) + 1:][:1] + ["discarded", ATTENTION]
        if cur == "report":
            allowed.append("merged")
    if to not in allowed:
        raise ValueError("cannot advance %s from %r to %r; allowed: %s" % (tid, cur, to, ", ".join(allowed) or "none"))
    task["attention"] = {"reason": reason or "unspecified", "prior_phase": cur} if to == ATTENTION else None
    if cur == ATTENTION:
        task["stop_blocks"] = 0
    task["phase"] = to
    if to in TERMINAL and state["active_task"] == tid:
        state["active_task"] = None
    return task


def summary(state):
    """One line for SessionStart injection: enough to resume, never a transcript."""
    tid = state["active_task"]
    if not tid:
        return "REHORSE: no active task."
    t = state["tasks"][tid]
    if t["phase"] == ATTENTION:
        return "REHORSE: task %s NEEDS ATTENTION (was in %s): %s. Run /rehorse:status." % (
            tid, t["attention"]["prior_phase"], t["attention"]["reason"])
    parts = ["REHORSE: active task %s, phase %s" % (tid, t["phase"])]
    if t["plan"]:
        parts.append("step %d/%d" % (min(t["step"] + 1, len(t["plan"])), len(t["plan"])))
    if t["last_test_run"]:
        parts.append("last tests %(passed)d passed, %(failed)d failed" % t["last_test_run"])
    return ", ".join(parts) + ". Read rehorse-reports/PROGRESS.md before acting."


def main(argv):
    if argv[:1] == ["--summary"]:
        hook = json.load(sys.stdin)
        root = find_root(hook.get("cwd") or os.getcwd())
        text = summary(load(root)) if root else summary(empty())
        json.dump({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}, sys.stdout)
        return 0
    root = find_root(os.getcwd())
    if not root:
        sys.exit("state.py: not inside a git repository")
    state = load(root)
    opts = {a[2:]: argv[i + 1] for i, a in enumerate(argv[:-1]) if a.startswith("--")}  # --key value
    tid = opts.get("task") or state["active_task"]
    if argv[0] == "new":
        print(new_task(state, task_id(argv[1], opts.get("date")))["id"])
    elif argv[0] == "advance":
        try:
            advance(state, tid, argv[1], opts.get("reason"))
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
