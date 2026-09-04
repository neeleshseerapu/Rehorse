#!/usr/bin/env python3
"""Verifier plumbing. `verify.py brief` writes .rehorse/verify/<id>-round<n>.md (spec, base_sha..HEAD diff, last test output,
and for round 2+ the verifier's own earlier findings; never the implementer's transcript or step summaries) and prints the
prompt for the rehorse-verifier subagent, so what the verifier sees is decided here, not by the orchestrator.
`verify.py --verdict` is the SubagentStop hook for that agent: it blocks the stop until the verifier ran the test command
after its last edit, committed its test file, and ended its reply with the JSON verdict block; then it records the verdict
in state. The orchestrator never copies a verdict by hand, so it cannot soften one.
"""
import datetime
import json
import os
import re
import sys

import guard_stop
import progress
import state
import testcmd
import worktree

AGENT = "rehorse-verifier"
VERDICTS = ("pass", "concerns", "fail")
EVIDENCE = ("test", "build_only", "none")
MAX_ROUNDS = 3
DIFF_CAP = 200000
SHAPE = ('{"verdict": "pass|concerns|fail", "findings": [{"severity": "high|medium|low", "file": "<path>", "line": 0, '
         '"description": "..."}], "tests_added": ["<file>::<test>"], "coverage": [{"criterion": "<acceptance criterion>", '
         '"evidence": "test|build_only|none", "ref": "<test id or file>"}]}')


def findings_text(v):
    return "\n".join("- [%s] %s:%s %s" % (f["severity"], f["file"], "?" if f["line"] is None else f["line"], f["description"])
                     for f in v["findings"]) or "- (none)"


def brief(root, task):
    """Write the brief and return the subagent prompt (which names it)."""
    wt, tid, n = progress.wt_path(root, task), task["id"], task.get("verify_round", 0) + 1
    try:
        spec = open(os.path.join(wt, "REHORSE_SPEC.md")).read()
    except OSError:
        spec = "(no REHORSE_SPEC.md in the worktree)"
    diff = worktree.diff(root, tid, task["base_sha"]) if task["base_sha"] else ""
    if len(diff) > DIFF_CAP:
        diff = diff[:DIFF_CAP] + "\n... (diff truncated at %d characters)" % DIFF_CAP
    vfile = testcmd.verify_file(task, wt)
    lines = ["# Rehorse verifier brief: %s, round %d" % (tid, n), "", "Worktree: %s" % wt,
             "Test command: cd %s && %s" % (wt, task["test_cmd"]), "The only file you may write: %s/%s" % (wt, vfile), "",
             "## Spec (REHORSE_SPEC.md)", "", spec.strip(), "", "## Diff (base %s..HEAD)" % (task["base_sha"] or "")[:7], "",
             "```diff", diff.strip() or "(no commits)", "```", "", "## Last test output", "", "```",
             ((task.get("last_test_run") or {}).get("output") or "(none recorded)").strip(), "```", ""]
    for v in task.get("verify_history") or []:
        lines += ["## Round %d: your earlier verdict was %s; check whether each finding is fixed" % (v["round"], v["verdict"].upper()),
                  "", findings_text(v), ""]
    path = os.path.join(root, ".rehorse", "verify", "%s-round%d.md" % (tid, n))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return ("Rehorse verify, round %d of %d, task %s.\nRead %s first: it holds the spec, the diff and the last test output. "
            "That is all you get; do not read rehorse-reports/ or PROGRESS.md.\nWorktree: %s. The only file you may write: %s/%s "
            "(any other edit is denied).\nTest command: cd %s && %s   (run it even if you add no test; only runs made there count).\n"
            "Commit your file if you wrote one: cd %s && git add -A && git commit -m \"verify: round %d tests for %s\"\n"
            "End your reply with the JSON block your instructions describe. Fix nothing.\n"
            % (n, MAX_ROUNDS, tid, path, wt, wt, vfile, wt, task["test_cmd"], wt, n, tid))


def parse(text):
    """The last ```json block (else the outermost {...}) as a verdict, fields normalised; None when absent or not pass|concerns|fail."""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S) or [text[text.find("{"):text.rfind("}") + 1]]
    try:
        v = json.loads(blocks[-1])
    except ValueError:
        return None
    if not isinstance(v, dict) or str(v.get("verdict", "")).lower() not in VERDICTS:
        return None
    findings = [{"severity": str(f.get("severity") or "medium").lower(), "file": str(f.get("file") or ""), "line": f.get("line"),
                 "description": str(f.get("description") or "")} for f in v.get("findings") or [] if isinstance(f, dict)]
    coverage = [{"criterion": str(c.get("criterion") or ""), "evidence": c.get("evidence") if c.get("evidence") in EVIDENCE else "none",
                 "ref": str(c.get("ref") or "")} for c in v.get("coverage") or [] if isinstance(c, dict)]
    return {"verdict": v["verdict"].lower(), "findings": findings, "coverage": coverage,
            "tests_added": [str(t) for t in v.get("tests_added") or []]}


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
    v = parse(hook.get("last_assistant_message") or "")
    if not v:
        return guard_stop.block(root, s, task, "no verdict found. End your reply with exactly one ```json block of this shape "
                                "(verdict must be pass|concerns|fail): %s" % SHAPE, "verify")
    task.update(verify_round=n, stop_blocks=0,
                verifier=dict(v, round=n, tests=task["verify_run"], at=datetime.datetime.now().isoformat(timespec="seconds")))
    state.save(root, s)
    progress.render(root, s)
    json.dump({"systemMessage": "REHORSE: verifier round %d: %s, %d finding(s); its run: %d passed, %d failed." % (
        n, v["verdict"].upper(), len(v["findings"]), task["verify_run"]["passed"], task["verify_run"]["failed"])}, sys.stdout)
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
    sys.stdout.write(brief(root, task))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
