"""verify.py: the brief handed to the rehorse-verifier subagent (spec, diff, last test output; never a transcript) and the
SubagentStop hook that records its verdict only once it ran the tests, committed, and ended with the JSON block."""
import json
import os

from conftest import commit_in, git, hook_input, hook_out, run_script, task_in, task_state

import state

SPEC = "Add sub(a, b) to app.py.\n\n## Acceptance criteria\n1. sub(3, 1) == 2\n2. sub raises TypeError on strings\n"
GOOD = ('Looked hard.\n```json\n{"verdict": "concerns", "findings": [{"severity": "medium", "file": "app.py", "line": 5, '
        '"description": "strings are concatenated, not rejected"}], "tests_added": ["tests/test_rehorse_verify_t-1.py::test_strings"], '
        '"coverage": [{"criterion": "1. sub(3, 1) == 2", "evidence": "test", "ref": "tests/test_sub.py::test_sub"}, '
        '{"criterion": "2. sub raises TypeError on strings", "evidence": "none", "ref": ""}]}\n```\n')


def verify_task(repo, **fields):
    """A task that finished implement: spec, red tests committed, one implementing commit, green run recorded, phase verify."""
    wt = task_in(repo, "implement", baseline={"passed": 1, "failed": 0}, red_check={"passed": 1, "failed": 1, "new_failed": 1})
    with open(os.path.join(wt, "REHORSE_SPEC.md"), "w") as f:
        f.write(SPEC)
    tests_sha = commit_in(wt, "tests/test_sub.py", "from app import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n", "tests: red")
    commit_in(wt, "app.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n", "step 1: Add sub()")
    s = state.load(str(repo))
    t = s["tasks"]["t-1"]
    t.update(tests_sha=tests_sha, edit_seq=2, last_test_run={"passed": 2, "failed": 0, "after_edit_seq": 2, "output": "2 passed in 0.01s"},
             plan=[{"title": "Add sub()", "done": True, "summary": "Added sub().\nGreen.", "commit": "abc"}], step=1)
    t.update(fields)
    state.advance(s, "t-1", "verify")
    state.save(str(repo), s)
    return wt


def ran(repo, passed=3, failed=0):
    """What on_bash_done.py leaves behind after the verifier's test run."""
    s = state.load(str(repo))
    t = s["tasks"]["t-1"]
    t["verify_run"] = {"passed": passed, "failed": failed}
    t["last_test_run"] = {"passed": passed, "failed": failed, "after_edit_seq": t["edit_seq"], "output": "%d passed" % passed}
    state.save(str(repo), s)


def stop(repo, message=GOOD, agent_type="rehorse:rehorse-verifier"):
    payload = dict(hook_input("subagentstop_step"), cwd=str(repo), agent_type=agent_type, last_assistant_message=message)
    return hook_out(run_script("verify", ["--verdict"], stdin=payload, cwd=str(repo)))


def blocked(out):
    assert out and out.get("decision") == "block", out
    assert out["reason"].startswith("REHORSE: ")
    return out["reason"]


# ---- brief --------------------------------------------------------------------

def test_brief_holds_spec_diff_and_last_output_and_prints_the_prompt(repo):
    wt = verify_task(repo)
    r = run_script("verify", ["brief"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    path = os.path.join(str(repo), ".rehorse", "verify", "t-1-round1.md")
    assert os.path.exists(path)
    text = open(path).read()
    assert "2. sub raises TypeError on strings" in text and "+def sub(a, b):" in text and "2 passed in 0.01s" in text
    assert "Added sub()" not in text  # never the step summaries
    prompt = r.stdout
    assert path in prompt and wt in prompt and "tests/test_rehorse_verify_t-1.py" in prompt and "python3 -m pytest -q" in prompt
    assert "round 1" in prompt and 'git commit -m "verify: round 1 tests for t-1"' in prompt


def test_brief_refuses_outside_verify(repo):
    task_in(repo, "implement")
    r = run_script("verify", ["brief"], cwd=str(repo))
    assert r.returncode != 0 and "verify" in r.stderr


def test_brief_for_a_later_round_includes_the_verifiers_own_earlier_findings(repo):
    verify_task(repo, verify_round=1, verify_history=[{"round": 1, "verdict": "fail", "findings": [
        {"severity": "high", "file": "app.py", "line": 5, "description": "strings are concatenated"}], "tests_added": [], "coverage": []}])
    r = run_script("verify", ["brief"], cwd=str(repo))
    text = open(os.path.join(str(repo), ".rehorse", "verify", "t-1-round2.md")).read()
    assert "round 2" in r.stdout and "Round 1" in text and "strings are concatenated" in text


# ---- --verdict (SubagentStop) ----------------------------------------------------

def test_hook_ignores_other_agents_and_other_phases(repo):
    verify_task(repo)
    ran(repo)
    assert stop(repo, agent_type="rehorse:rehorse-step") is None
    assert stop(repo, agent_type="") is None
    assert task_state(repo)["verifier"] is None
    s = state.load(str(repo))
    s["tasks"]["t-1"]["phase"] = "implement"
    state.save(str(repo), s)
    assert stop(repo) is None


def test_hook_blocks_until_the_verifier_ran_the_test_command(repo):
    wt = verify_task(repo)
    reason = blocked(stop(repo))
    assert "run the test command" in reason and "cd %s && python3 -m pytest -q" % wt in reason
    ran(repo)
    s = state.load(str(repo))
    s["tasks"]["t-1"]["edit_seq"] += 1  # an edit after the run
    state.save(str(repo), s)
    reason = blocked(stop(repo))
    assert "after its last edit" in reason


def test_hook_blocks_an_uncommitted_verifier_file_with_the_exact_commit_command(repo):
    wt = verify_task(repo)
    ran(repo)
    with open(os.path.join(wt, "tests", "test_rehorse_verify_t-1.py"), "w") as f:
        f.write("def test_strings():\n    assert 1\n")
    reason = blocked(stop(repo))
    assert 'git commit -m "verify: round 1 tests for t-1"' in reason and "tests/test_rehorse_verify_t-1.py" in reason


def test_hook_blocks_a_reply_without_a_valid_json_verdict(repo):
    verify_task(repo)
    ran(repo)
    reason = blocked(stop(repo, "All good, nothing to report."))
    assert "```json" in reason and "verdict" in reason and "coverage" in reason
    reason = blocked(stop(repo, '```json\n{"verdict": "maybe", "findings": []}\n```'))
    assert "pass|concerns|fail" in reason
    assert task_state(repo)["verifier"] is None and task_state(repo)["stop_blocks"] == 2


def test_hook_records_the_verdict_and_progress_shows_it(repo):
    wt = verify_task(repo)
    ran(repo)
    commit_in(wt, "tests/test_rehorse_verify_t-1.py", "def test_strings():\n    assert 1\n", "verify: round 1 tests for t-1")
    out = stop(repo)
    assert out and "decision" not in out and "CONCERNS" in out.get("systemMessage", "")
    t = task_state(repo)
    v = t["verifier"]
    assert t["phase"] == "verify" and t["verify_round"] == 1 and t["stop_blocks"] == 0
    assert v["round"] == 1 and v["verdict"] == "concerns" and v["tests"] == {"passed": 3, "failed": 0}
    assert v["findings"][0]["description"] == "strings are concatenated, not rejected" and v["findings"][0]["severity"] == "medium"
    assert v["coverage"][1]["evidence"] == "none" and v["tests_added"] == ["tests/test_rehorse_verify_t-1.py::test_strings"]
    md = (repo / "rehorse-reports" / "PROGRESS.md").read_text()
    assert "Verifier: round 1 CONCERNS (1 finding" in md and "report.py" in md.split("Next:")[1]


def test_hook_takes_the_last_json_block_and_fills_missing_fields(repo):
    verify_task(repo)
    ran(repo)
    msg = '```json\n{"verdict": "fail"}\n```\nthen, after more tests:\n```json\n{"verdict": "PASS"}\n```'
    stop(repo, msg)
    v = task_state(repo)["verifier"]
    assert v["verdict"] == "pass" and v["findings"] == [] and v["coverage"] == [] and v["tests_added"] == []


def test_eighth_consecutive_block_moves_the_task_to_needs_attention(repo):
    verify_task(repo, stop_blocks=7)
    out = stop(repo)
    assert out and "decision" not in out and "needs-attention" in out["systemMessage"]
    t = task_state(repo)
    assert t["phase"] == "needs-attention" and t["attention"]["prior_phase"] == "verify"


def test_next_action_in_verify_names_the_brief_before_and_the_report_after_a_verdict(repo):
    verify_task(repo)
    r = run_script("progress", ["render"], cwd=str(repo))
    assert "verify.py brief" in r.stdout and "rehorse-verifier" in r.stdout
    ran(repo)
    stop(repo)
    r = run_script("progress", ["render"], cwd=str(repo))
    assert "report.py" in r.stdout.split("Next:")[1]


def test_hooks_json_routes_subagent_stop_by_agent_name():
    """Both SubagentStop hooks are matched on their agent's plugin-scoped type in hooks.json and filter again in the script.
    The matcher must be a regex: a plain `rehorse-verifier` is an exact-string matcher and never equals
    `rehorse:rehorse-verifier` (live check, 2026-09-04)."""
    hooks = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "hooks.json")))["hooks"]
    entries = {h["hooks"][0]["args"][0].rsplit("/", 1)[-1]: h.get("matcher") for h in hooks["SubagentStop"]}
    assert entries["verify.py"] == "^rehorse:rehorse-verifier$"
    import re
    assert re.search(entries["verify.py"], "rehorse:rehorse-verifier") and not re.search(entries["verify.py"], "rehorse:rehorse-step")


# ---- round-trip: a failing verdict (or failing verifier tests) sends the task back to implement, at most twice ------------

FAIL = ('```json\n{"verdict": "fail", "findings": [{"severity": "high", "file": "app.py", "line": 5, "criterion": "2. sub raises '
        'TypeError on strings", "description": "strings are concatenated, not rejected"}, {"severity": "low", "file": "app.py", '
        '"line": 1, "description": "no docstring"}], "tests_added": ["tests/test_rehorse_verify_t-1.py::test_strings"], "coverage": []}\n```')
UNCITED_FAIL = FAIL.replace('"criterion": "2. sub raises TypeError on strings", ', "")


def test_fail_verdict_returns_the_task_to_implement_with_the_findings_as_new_steps(repo):
    wt = verify_task(repo)
    ran(repo, passed=3, failed=1)
    out = stop(repo, FAIL)
    assert out and "decision" not in out and "implement" in out["systemMessage"]
    t = task_state(repo)
    assert t["phase"] == "implement" and t["verifier"] is None and t["verify_run"] is None and t["verify_round"] == 1
    assert t["verify_history"][0]["round"] == 1 and t["verify_history"][0]["verdict"] == "fail"
    titles = [p["title"] for p in t["plan"]]
    assert titles == ["Add sub()", "Fix (verifier round 1): strings are concatenated, not rejected (app.py:5)",
                      "Make the verifier's tests pass: tests/test_rehorse_verify_t-1.py (1 failing)"]
    assert t["step"] == 1 and all(not p["done"] for p in t["plan"][1:])
    md = (repo / "rehorse-reports" / "PROGRESS.md").read_text()
    assert "run step 2 (Fix (verifier round 1)" in md.split("Next:")[1] and "Verifier: round 1 FAIL" in md


def test_failing_verifier_tests_return_the_task_even_on_a_concerns_verdict(repo):
    verify_task(repo)
    ran(repo, passed=3, failed=2)
    stop(repo)  # GOOD: verdict concerns, one medium finding
    t = task_state(repo)
    assert t["phase"] == "implement"
    assert [p["title"] for p in t["plan"]][1:] == ["Make the verifier's tests pass: tests/test_rehorse_verify_t-1.py (2 failing)"]


def test_fail_verdict_without_findings_is_a_concern_and_only_failing_tests_return_the_task(repo):
    """A fail with nothing listed cites no criterion, so it is a concern; the round-trip is then earned by failing tests alone."""
    verify_task(repo)
    ran(repo)
    stop(repo, '```json\n{"verdict": "fail"}\n```')
    assert task_state(repo)["verifier"]["verdict"] == "concerns" and task_state(repo)["phase"] == "verify"
    ran(repo, passed=3, failed=1)
    stop(repo, '```json\n{"verdict": "fail"}\n```')
    t = task_state(repo)
    assert t["phase"] == "implement" and [p["title"] for p in t["plan"]][1:] == [
        "Make the verifier's tests pass: tests/test_rehorse_verify_t-1.py (1 failing)"]


def test_pass_or_concerns_with_green_verifier_tests_stays_in_verify(repo):
    verify_task(repo)
    ran(repo)
    stop(repo)
    t = task_state(repo)
    assert t["phase"] == "verify" and t["verifier"]["verdict"] == "concerns" and len(t["plan"]) == 1


def test_third_failed_round_sets_needs_attention_and_keeps_the_verdict_for_the_report(repo):
    history = [{"round": n, "verdict": "fail", "findings": [], "tests_added": [], "coverage": [], "tests": {"passed": 3, "failed": 1}} for n in (1, 2)]
    verify_task(repo, verify_round=2, verify_history=history)
    ran(repo, passed=3, failed=1)
    out = stop(repo, FAIL)
    assert out and "needs-attention" in out["systemMessage"]
    t = task_state(repo)
    assert t["phase"] == "needs-attention" and t["attention"]["prior_phase"] == "verify"
    assert "3 rounds" in t["attention"]["reason"] and "strings are concatenated" in t["attention"]["reason"]
    assert t["verifier"]["round"] == 3 and t["verify_round"] == 3 and len(t["verify_history"]) == 2 and len(t["plan"]) == 1
    r = run_script("report", cwd=str(repo))
    assert r.returncode == 0, r.stderr
    text = open(r.stdout.strip()).read()
    assert "NEEDS ATTENTION" in text[:400] and "## Verifier: FAIL (round 3 of 3)" in text and "Round 1: FAIL" in text


def test_round_trip_step_titles_are_capped_but_keep_the_location(repo):
    long = "x" * 400
    verify_task(repo)
    ran(repo)
    stop(repo, '```json\n{"verdict": "fail", "findings": [{"severity": "high", "file": "app.py", "line": 6, '
         '"criterion": "1. sub(3, 1) == 2", "description": "%s"}]}\n```' % long)
    title = task_state(repo)["plan"][1]["title"]
    assert title.startswith("Fix (verifier round 1): xxxx") and title.endswith("... (app.py:6)") and len(title) < 240


def test_a_fail_that_cites_no_acceptance_criterion_is_recorded_as_concerns(repo):
    """A fail must name the criterion it violates; an objection that cannot point at one is a concern, not a stop."""
    verify_task(repo)
    ran(repo, passed=3, failed=0)
    out = stop(repo, UNCITED_FAIL)
    t = task_state(repo)
    assert t["verifier"]["verdict"] == "concerns" and t["phase"] == "verify"  # no round-trip: nothing failed and nothing was violated
    assert "concerns" in out["systemMessage"].lower() and "criterion" in out["systemMessage"]
    assert [f["description"] for f in t["verifier"]["findings"]][0] == "strings are concatenated, not rejected"


def test_a_fail_that_cites_a_criterion_is_kept_and_the_criterion_is_recorded(repo):
    verify_task(repo)
    ran(repo, passed=3, failed=0)
    stop(repo, FAIL)
    t = task_state(repo)
    assert t["verify_history"][0]["verdict"] == "fail"
    assert t["verify_history"][0]["findings"][0]["criterion"] == "2. sub raises TypeError on strings"
