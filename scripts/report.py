#!/usr/bin/env python3
"""Render the rehearsal report: rehorse-reports/<date>-<slug>.md, one screen, in the spec's order
(banner -> summary -> tests -> diff stat -> verifier verdict, findings, coverage -> test-file drift -> plan -> try it
yourself -> merge/discard commands). More than MAX_FINDINGS findings go to rehorse-reports/verifier/<same-name>.md, linked.

Runs after verify (advances verify -> report itself) or on a task in needs-attention (renders the reason as the banner,
phase unchanged). Writes the report and PROGRESS.md in the main checkout, where the user looks, then commits copies of
both on the rehearsal branch so /rehorse:merge carries the evidence into the real branch. Prints the report path.
CLI: report.py [--task ID] [--summary "<text>"]   (the summary is the orchestrator's own words; it is labelled as such)
"""
import os
import re
import shutil
import sys

import progress
import state
import testcmd
import verify
import worktree

REPORTS = "rehorse-reports"
MAX_FINDINGS = 5
EYEBALL = {"none": "no test", "build_only": "only built or imported, never exercised"}


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
    return [n for n in names if testcmd.is_test_path(n, task["test_paths"]) and "rehorse_verify_" not in os.path.basename(n)]


def banner(task):
    last, v = task.get("last_test_run"), task.get("verifier")
    if task["phase"] == state.ATTENTION:
        return "## NEEDS ATTENTION: %s (was in %s)" % (task["attention"]["reason"], task["attention"]["prior_phase"])
    if not last:
        return "## NO TEST RUN RECORDED"
    n = len(v["findings"]) if v else 0
    tag = "verifier %s%s" % (v["verdict"].upper(), " (%d finding%s)" % (n, "" if n == 1 else "s") if n else "") if v else "unverified"
    if v and v["verdict"] == "fail":
        return "## FAIL: verifier found %d issue%s · tests %d passed, %d failed" % (n, "" if n == 1 else "s", last["passed"], last["failed"])
    if last["failed"]:
        return "## RED: %d failed, %d passed · %s" % (last["failed"], last["passed"], tag)
    return "## GREEN: %d passed, 0 failed · %s" % (last["passed"], tag)


def ids(names, cap=5):
    names = names or []
    return ", ".join(names[:cap]) + (" (+%d more)" % (len(names) - cap) if len(names) > cap else "")


def guard_line(task):
    """Guards are new tests marked as expected to pass before the implementation; any other early pass is a warning."""
    g, weak, fg = task.get("guards") or [], task.get("weak_tests") or 0, (task.get("red_check") or {}).get("failing_guards") or []
    if not g and not weak:
        return []
    return ["%s%d guard(s) expected to pass; %d unexpected pass(es)%s%s" % (
        "**Warning:** " if weak else "", len(g), weak, " (guards: %s)" % ids(g) if g else "",
        "; %d guard(s) failing at red: %s" % (len(fg), ids(fg)) if fg else ""), ""]


def red_lines(task):
    """Pre-existing failures are reported apart from red; red is judged by ids that were not failing at baseline."""
    base, red, out = task.get("baseline") or {}, task.get("red_check") or {}, []
    if base.get("failed"):
        out.append("**Pre-existing:** %d failing at baseline (ignored): %s" % (base["failed"], ids(base.get("failing")) or "ids unavailable"))
        out.append("Red: %d new failing test(s) at red: %s" % (red.get("new_failed", 0), ids(red.get("new_failing")) or "ids unavailable"))
    if red.get("ids_unavailable"):
        out.append("**Warning:** no test ids in the runner output; red was judged by counts.")
    return out + [""] if out else []


def findings_text(v):
    return "\n".join("- [%s] %s:%s %s" % (f["severity"], f["file"], "?" if f["line"] is None else f["line"], f["description"])
                     for f in v["findings"]) or "- (none)"


def coverage_table(cov):
    if not cov:
        return ["(no coverage map returned)"]
    return ["| acceptance criterion | evidence | ref |", "|---|---|---|"] + ["| %s | %s | %s |" % (c["criterion"], c["evidence"], c["ref"]) for c in cov]


def tests_added(ids):
    """A few test ids are listed; many are counted per file (the ids stay in state.json)."""
    if len(ids) <= 3:
        return ", ".join(ids) or "none"
    return "%d in %s" % (len(ids), ", ".join(sorted({i.split("::")[0] for i in ids})))


def verifier_section(task, name):
    """Report lines for the verdict; second value is the full findings file's text when the report shows only the first few."""
    v = task.get("verifier")
    if not v:
        return ["## Verifier: not run", "", "no verdict recorded.", ""], None
    n = len(v["findings"])
    lines = ["## Verifier: %s (round %d of %d)" % (v["verdict"].upper(), v["round"], verify.MAX_ROUNDS), "",
             "Its run: %s. Tests added: %s" % (progress.counts(v.get("tests")).replace(" / ", ", "), tests_added(v["tests_added"])), "",
             "Findings:" if n else "Findings: none", *([findings_text({"findings": v["findings"][:MAX_FINDINGS]})] if n else [])]
    if n > MAX_FINDINGS:
        lines.append("- ... %d more in %s/verifier/%s" % (n - MAX_FINDINGS, REPORTS, name))
    lines += ["", *coverage_table(v["coverage"]), ""]
    for h in task.get("verify_history") or []:
        lines += ["Round %d: %s (%d finding(s); its run %s)" % (h["round"], h["verdict"].upper(), len(h["findings"]), progress.counts(h.get("tests"))),
                  findings_text(h), ""]
    full = "\n".join(["# Verifier findings: %s (round %d, verdict %s)" % (task["id"], v["round"], v["verdict"]), "",
                      findings_text(v), "", *coverage_table(v["coverage"]), ""]) if n > MAX_FINDINGS else None
    return lines, full


def eyeball(task):
    """Criteria the verifier could not tie to a test: what the user should try by hand."""
    items = [c for c in (task.get("verifier") or {}).get("coverage") or [] if c["evidence"] in EYEBALL]
    return ["Eyeball these; no test covers them:", *["- %s (%s)" % (c["criterion"], EYEBALL[c["evidence"]]) for c in items], ""] if items else []


BUILD_FAILED_ROW = "| red (tests written, no implementation) | build failed (new tests reference symbols that don't exist yet) | |"


def render(root, task, name):
    wt, tid = progress.wt_path(root, task), task["id"]
    verifier, full = verifier_section(task, name)
    stat = worktree.diff(root, tid, task["base_sha"], stat=True).strip() if task["base_sha"] else ""
    d = drift(wt, task)
    if d is None:
        drift_text = "unknown: no tests_sha recorded (the plan was never set)."
    elif d:
        drift_text = "**DRIFT**: test files changed after the tests phase: " + ", ".join(d)
    else:
        drift_text = "none: test files unchanged since the tests phase (`%s`)." % task["tests_sha"][:7]
    plan = ["- [%s] %d. %s%s" % ("x" if p["done"] else " ", n, p["title"], "" if not p["done"] else
                                 " — already satisfied by step %d (no edits)" % p["satisfied_by"] if p.get("satisfied_by") else
                                 " — " + " ".join((p["summary"] or "").splitlines()))
            for n, p in enumerate(task["plan"], 1)] or ["(no plan recorded)"]
    lines = [
        "# Rehearsal report: %s" % (worktree.spec_goal(wt) or tid), "",
        "Task `%s` · branch `%s` · base `%s` · %s" % (tid, task["branch"], (task["base_sha"] or "")[:7], task["created"][:10]), "",
        "Worktree setup: " + ("linked " + ", ".join(task["linked_deps"]) + " from the main checkout" if task.get("linked_deps")
                              else "nothing linked (no .venv, node_modules, target or .tox in the main checkout)"), "",
        banner(task), "",
        *(["## Summary", "", "_Written by the model at report time; everything else in this report is generated from recorded "
           "state._", "", task["summary"], ""] if task.get("summary") else []),
        "## Tests", "", "| stage | passed | failed |", "|---|---|---|", row("baseline", task["baseline"]),
        BUILD_FAILED_ROW if task.get("red_kind") == "build_failed" else row("red (tests written, no implementation)", task["red_check"]),
        row("green (last run)", task["last_test_run"]), "",
        "Command: `%s`" % task["test_cmd"], "",
        *red_lines(task),
        *guard_line(task),
        "## Changes (base..HEAD)", "", "```", stat or "(no commits)", "```", "",
        *verifier,
        "## Test-file drift", "", drift_text, "",
        "## Plan", "", *plan, "",
        "## Try it yourself", "", "```", "cd %s" % wt, task["test_cmd"] or "# no test command recorded",
        (testcmd.run_cmd(wt) if os.path.isdir(wt) else None) or "# no run command detected (no package.json dev/start, Makefile run target, build.sh, cargo/go/swift project, or README run line)",
        "```", "", *eyeball(task),
        "## Next", "", "```",
        "/rehorse:merge %s      merge %s into your branch and remove the worktree" % (tid, task["branch"]),
        "/rehorse:discard %s    drop the worktree and the branch" % tid, "```", "",
    ]
    return "\n".join(lines), full


def commit_evidence(root, task, files):
    """Copy the report and the PROGRESS.md snapshot into the worktree and commit them on the rehearsal branch."""
    wt = progress.wt_path(root, task)
    if not os.path.isdir(wt):
        return
    os.makedirs(os.path.join(wt, REPORTS), exist_ok=True)
    for f in files:
        os.makedirs(os.path.dirname(os.path.join(wt, REPORTS, f)), exist_ok=True)
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
    if "--summary" in argv:
        task["summary"] = argv[argv.index("--summary") + 1].strip()
    if task["phase"] == "verify":
        state.advance(s, task["id"], "report")
    elif task["phase"] not in ("report", state.ATTENTION):
        sys.exit("report.py: task %s is in phase %s; the report is rendered after verify." % (task["id"], task["phase"]))
    name = report_name(task)
    task["report_path"] = "%s/%s" % (REPORTS, name)
    path = os.path.join(root, REPORTS, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text, full = render(root, task, name)
    with open(path, "w") as f:
        f.write(text)
    files = [name, "PROGRESS.md"]
    if full:
        os.makedirs(os.path.join(root, REPORTS, "verifier"), exist_ok=True)
        with open(os.path.join(root, REPORTS, "verifier", name), "w") as f:
            f.write(full)
        files.append("verifier/" + name)
    state.save(root, s)
    progress.render(root, s)
    commit_evidence(root, task, files)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
