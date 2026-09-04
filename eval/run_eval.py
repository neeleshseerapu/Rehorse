#!/usr/bin/env python3
"""Run the eval: for each task in eval/tasks.json, clone the repo at base_sha, run its setup, run
`claude -p "/rehorse:build ..."` with the plugin loaded, then grade with the upstream PR's own tests.

  python3 eval/run_eval.py [--tasks eval/tasks.json] [--only ID ...] [--rerun] [--work /tmp/rehorse-eval]
                           [--max-turns 150] [--timeout 3600]

One result file per task in eval/results/<id>.json (plus a copy of Rehorse's report as <id>.report.md); a task with a
result file is skipped, so a stopped run resumes where it left off (--rerun redoes it). A failure in one task is recorded
in its result and the run goes on. eval/results.md is re-rendered from every result file after each task.

Grading is by the upstream PR's tests, never Rehorse's own: the PR's test files are checked out (from refs/pull/N/head)
into the rehearsal worktree and run with the task's test command; `upstream_pass` is that run being green.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # the plugin: what --plugin-dir loads
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import testcmd  # noqa: E402

RESULTS = os.path.join(HERE, "results")
COLUMNS = ["task", "merged-green", "upstream-tests-pass", "verifier", "rounds", "wall", "turns", "report"]


def prompt(task):
    text = task["issue_title"] + "\n\n" + task["issue_body"]
    return '/rehorse:build "%s"' % text.replace('"', '\\"')


def outcome(state):
    """What Rehorse itself says happened, read from .rehorse/state.json (never parsed out of the report's prose)."""
    t = (state or {}).get("tasks", {}).get((state or {}).get("active_task")) or next(iter((state or {}).get("tasks", {}).values()), None)
    if not t:
        return {"merged_green": False, "verdict": None, "rounds": 0, "phase": None, "report_path": None, "worktree": None, "attention": None,
                "baseline": None, "last_test_run": None}
    last = t.get("last_test_run") or {}
    green = t["phase"] == "report" and bool(last) and last["failed"] == 0 and last["passed"] > 0
    return {"merged_green": green, "verdict": (t.get("verifier") or {}).get("verdict"), "rounds": t.get("verify_round", 0),
            "phase": t["phase"], "report_path": t.get("report_path"), "worktree": t.get("worktree"),
            "attention": (t.get("attention") or {}).get("reason"), "baseline": t.get("baseline"), "last_test_run": last or None}


def pending(tasks, results_dir, rerun=False, only=None):
    wanted = [t for t in tasks if not only or t["id"] in only]
    return [t for t in wanted if rerun or not os.path.exists(os.path.join(results_dir, t["id"] + ".json"))]


def sh(cmd, cwd, log=None, timeout=None):
    """Run a shell string, tee its output to a log file, return (exit code, output)."""
    p = subprocess.run(cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    if log:
        with open(log, "a") as f:
            f.write("$ %s\n%s\n[exit %d]\n" % (cmd, p.stdout, p.returncode))
    return p.returncode, p.stdout


def grade(task, clone, wt):
    """Check the PR's test files out of refs/pull/N/head into the worktree (the clone when there is none) and run them."""
    where = wt if wt and os.path.isdir(wt) else clone
    pr = task["pr_url"].rstrip("/").rsplit("/", 1)[1]
    subprocess.run(["git", "fetch", "-q", "origin", "refs/pull/%s/head" % pr], cwd=where, check=True)  # FETCH_HEAD is per worktree
    subprocess.run(["git", "checkout", "-q", "FETCH_HEAD", "--", *task["pr_test_files"]], cwd=where, check=True)
    cmd = "%s %s" % (task["test_cmd"], " ".join(task["pr_test_files"]))
    code, out = sh(cmd, where, timeout=1800)
    counts = testcmd.parse_counts(out)
    return {"upstream_pass": bool(counts) and counts["failed"] == 0 and counts["passed"] > 0 and code == 0,
            "counts": counts, "command": cmd, "where": where, "output_tail": out[-3000:]}


def run_claude(task, clone, log, max_turns, timeout):
    """claude -p with the plugin, permissions bypassed, stdin closed (else -p waits on it); returns (envelope, wall seconds, error)."""
    args = ["claude", "--plugin-dir", ROOT, "--dangerously-skip-permissions", "--output-format", "json", "--debug-file", log,
            "--max-turns", str(max_turns), "-p", prompt(task)]
    t0 = time.time()
    try:
        p = subprocess.run(args, cwd=clone, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, time.time() - t0, "claude timed out after %ds" % timeout
    wall = time.time() - t0
    try:
        return json.loads(p.stdout), wall, None if p.returncode == 0 else "claude exit %d: %s" % (p.returncode, p.stderr[-500:])
    except ValueError:
        return None, wall, "claude exit %d, no JSON envelope: %s" % (p.returncode, (p.stdout + p.stderr)[-500:])


def run_task(task, work, max_turns, timeout):
    tid, clone = task["id"], os.path.join(work, task["id"])
    row = {"id": tid, "merged_green": False, "upstream_pass": False, "verdict": None, "rounds": 0, "wall_s": 0, "turns": None, "report": None}
    log = os.path.join(work, tid + ".log")
    shutil.rmtree(clone, ignore_errors=True)
    for f in (log, os.path.join(work, tid + ".claude.json")):
        os.path.exists(f) and os.remove(f)
    subprocess.run(["git", "clone", "-q", "https://github.com/%s.git" % task["repo"], clone], check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "eval", task["base_sha"]], cwd=clone, check=True)
    code, _ = sh(task["setup_cmd"], clone, log)
    if code:
        row["error"] = "setup_cmd failed (exit %d)" % code
        return row
    env, wall, err = run_claude(task, clone, log, max_turns, timeout)
    row["wall_s"] = round(wall, 1)
    if env:
        json.dump(env, open(os.path.join(work, tid + ".claude.json"), "w"), indent=1)
        row.update(turns=env.get("num_turns"), session_id=env.get("session_id"), cost_usd=env.get("total_cost_usd"), is_error=env.get("is_error"))
    if err:
        row["error"] = err
    sp = os.path.join(clone, ".rehorse", "state.json")
    o = outcome(json.load(open(sp)) if os.path.exists(sp) else None)
    row.update({k: o[k] for k in ("merged_green", "verdict", "rounds", "phase", "attention", "baseline", "last_test_run")})
    if o["report_path"] and os.path.exists(os.path.join(clone, o["report_path"])):
        shutil.copy(os.path.join(clone, o["report_path"]), os.path.join(RESULTS, tid + ".report.md"))
        row["report"] = "results/%s.report.md" % tid
    try:
        row["grade"] = grade(task, clone, os.path.join(clone, o["worktree"]) if o["worktree"] else None)
        row["upstream_pass"] = row["grade"]["upstream_pass"]
    except subprocess.CalledProcessError as e:
        row["error"] = (row.get("error") or "") + " grade failed: %s" % e
    return row


def fmt_wall(s):
    s = int(s or 0)
    return "%dm%02ds" % divmod(s, 60) if s >= 60 else "%ds" % s


def render(rows):
    lines = ["# Eval results", "", "Graded by the upstream PR's tests (checked out into the rehearsal worktree), never by Rehorse's own. "
             "merged-green: Rehorse reached its report with a green run; verifier: its verdict and how many rounds it took.", "",
             "| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for r in rows:
        report = "[report](%s)" % r["report"] if r.get("report") else r.get("error") or "–"
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r["id"], "yes" if r["merged_green"] else "no", "**yes**" if r["upstream_pass"] else "no", r.get("verdict") or "–",
            r.get("rounds", 0), fmt_wall(r.get("wall_s")), r["turns"] if r.get("turns") is not None else "–", report))
    n = len(rows)
    lines += ["", "%d of %d tasks pass the upstream PR's tests; %d self-reported green; %d errored." % (
        sum(r["upstream_pass"] for r in rows), n, sum(r["merged_green"] for r in rows), sum(1 for r in rows if r.get("error")))]
    return "\n".join(lines) + "\n"


def write_results(results_dir):
    rows = [json.load(open(os.path.join(results_dir, f))) for f in sorted(os.listdir(results_dir)) if f.endswith(".json")]
    with open(os.path.join(HERE, "results.md"), "w") as f:
        f.write(render(rows))
    return rows


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", default=os.path.join(HERE, "tasks.json"))
    ap.add_argument("--only", nargs="*", help="task ids to run")
    ap.add_argument("--rerun", action="store_true", help="redo tasks that already have a result")
    ap.add_argument("--work", default="/tmp/rehorse-eval", help="clones and logs (outside this repo, so its CLAUDE.md is not picked up)")
    ap.add_argument("--max-turns", type=int, default=150)
    ap.add_argument("--timeout", type=int, default=3600, help="seconds per claude run")
    a = ap.parse_args(argv)
    os.makedirs(a.work, exist_ok=True)
    os.makedirs(RESULTS, exist_ok=True)
    todo = pending(json.load(open(a.tasks)), RESULTS, a.rerun, a.only)
    print("%d task(s) to run" % len(todo))
    for task in todo:
        print("== %s: %s" % (task["id"], task["issue_title"]), flush=True)
        try:
            row = run_task(task, a.work, a.max_turns, a.timeout)
        except Exception as e:  # one task's failure never aborts the run
            row = {"id": task["id"], "merged_green": False, "upstream_pass": False, "verdict": None, "rounds": 0, "wall_s": 0, "turns": None,
                   "report": None, "error": "%s: %s" % (type(e).__name__, e)}
        json.dump(row, open(os.path.join(RESULTS, task["id"] + ".json"), "w"), indent=1)
        write_results(RESULTS)
        print("   merged-green %s, upstream %s, verifier %s, %s, %s turn(s)%s" % (
            row["merged_green"], row["upstream_pass"], row.get("verdict"), fmt_wall(row.get("wall_s")), row.get("turns"),
            "; error: " + row["error"] if row.get("error") else ""), flush=True)
    print(open(os.path.join(HERE, "results.md")).read())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
