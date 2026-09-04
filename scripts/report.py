#!/usr/bin/env python3
"""Render the rehearsal report: rehorse-reports/<date>-<slug>.md, one screen, in the spec's order
(banner -> tests -> diff stat -> verifier -> test-file drift -> plan -> merge/discard commands).

Runs after verify (advances verify -> report itself) or on a task in needs-attention (renders the reason as the banner,
phase unchanged). Writes the report and PROGRESS.md in the main checkout, where the user looks, then commits copies of
both on the rehearsal branch so /rehorse:merge carries the evidence into the real branch. Prints the report path.
CLI: report.py [--task ID]
"""
import os
import re
import shutil
import sys

import progress
import state
import testcmd
import worktree

REPORTS = "rehorse-reports"


def report_name(task):
    m = re.match(r"^t-(\d{4})(\d{2})(\d{2})-(.+)$", task["id"])
    date, slug = ("%s-%s-%s" % m.groups()[:3], m.group(4)) if m else (task["created"][:10], task["id"][2:] or task["id"])
    return "%s-%s.md" % (date, slug)


def row(label, c):
    return "| %s | %s | %s |" % (label, c["passed"] if c else "–", c["failed"] if c else "–")


def drift(wt, task):
    """Test files changed after the tests phase ended (tests_sha..HEAD): the implementer weakening its own tests."""
    if not task.get("tests_sha"):
        return None
    names = worktree.git(wt, "diff", "--name-only", task["tests_sha"] + "..HEAD").split()
    return [n for n in names if testcmd.is_test_path(n, task["test_paths"])]


def banner(task):
    last = task.get("last_test_run")
    if task["phase"] == state.ATTENTION:
        return "## NEEDS ATTENTION: %s (was in %s)" % (task["attention"]["reason"], task["attention"]["prior_phase"])
    if not last:
        return "## NO TEST RUN RECORDED"
    if last["failed"]:
        return "## RED: %d failed, %d passed · unverified" % (last["failed"], last["passed"])
    return "## GREEN: %d passed, 0 failed · unverified" % last["passed"]


def render(root, task):
    wt, tid = progress.wt_path(root, task), task["id"]
    stat = worktree.diff(root, tid, task["base_sha"], stat=True).strip() if task["base_sha"] else ""
    d = drift(wt, task)
    if d is None:
        drift_text = "unknown: no tests_sha recorded (the plan was never set)."
    elif d:
        drift_text = "**DRIFT**: test files changed after the tests phase: " + ", ".join(d)
    else:
        drift_text = "none: test files unchanged since the tests phase (`%s`)." % task["tests_sha"][:7]
    plan = ["- [%s] %d. %s%s" % ("x" if p["done"] else " ", n, p["title"],
                                 " — " + " ".join((p["summary"] or "").splitlines()) if p["done"] else "")
            for n, p in enumerate(task["plan"], 1)] or ["(no plan recorded)"]
    lines = [
        "# Rehearsal report: %s" % (progress.goal(root, task) or tid), "",
        "Task `%s` · branch `%s` · base `%s` · %s" % (tid, task["branch"], (task["base_sha"] or "")[:7], task["created"][:10]), "",
        "Worktree setup: " + ("linked " + ", ".join(task["linked_deps"]) + " from the main checkout" if task.get("linked_deps")
                              else "nothing linked (no .venv, node_modules, target or .tox in the main checkout)"), "",
        banner(task), "",
        "## Tests", "", "| stage | passed | failed |", "|---|---|---|", row("baseline", task["baseline"]),
        row("red (tests written, no implementation)", task["red_check"]), row("green (last run)", task["last_test_run"]), "",
        "Command: `%s`" % task["test_cmd"], "",
        "## Changes (base..HEAD)", "", "```", stat or "(no commits)", "```", "",
        "## Verifier", "", "not run (the verifier arrives in milestone 5).", "",
        "## Test-file drift", "", drift_text, "",
        "## Plan", "", *plan, "",
        "## Next", "", "```",
        "/rehorse:merge %s      merge %s into your branch and remove the worktree" % (tid, task["branch"]),
        "/rehorse:discard %s    drop the worktree and the branch" % tid, "```", "",
    ]
    return "\n".join(lines)


def commit_evidence(root, task, files):
    """Copy the report and the PROGRESS.md snapshot into the worktree and commit them on the rehearsal branch."""
    wt = progress.wt_path(root, task)
    if not os.path.isdir(wt):
        return
    os.makedirs(os.path.join(wt, REPORTS), exist_ok=True)
    for f in files:
        shutil.copy(os.path.join(root, REPORTS, f), os.path.join(wt, REPORTS, f))
    worktree.git(wt, "add", "--", REPORTS)
    if worktree.git(wt, "status", "--porcelain", "--", REPORTS).strip():
        worktree.git(wt, "commit", "-q", "-m", "rehorse: report for %s" % task["id"])


def main(argv):
    root, s, task = state.active(os.getcwd())
    if not root:
        sys.exit("report.py: not inside a git repository")
    if "--task" in argv:
        task = s["tasks"].get(argv[argv.index("--task") + 1])
    if not task:
        sys.exit("report.py: no active task")
    if task["phase"] == "verify":
        state.advance(s, task["id"], "report")
    elif task["phase"] not in ("report", state.ATTENTION):
        sys.exit("report.py: task %s is in phase %s; the report is rendered after verify." % (task["id"], task["phase"]))
    name = report_name(task)
    task["report_path"] = "%s/%s" % (REPORTS, name)
    path = os.path.join(root, REPORTS, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(render(root, task))
    state.save(root, s)
    progress.render(root, s)
    commit_evidence(root, task, [name, "PROGRESS.md"])
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
