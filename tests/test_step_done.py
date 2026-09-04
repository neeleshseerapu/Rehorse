"""step_done.py (SubagentStop for rehorse-step agents): closes a plan step only when tests ran after the last edit and the
worktree is committed; in the tests phase also requires the reply's coverage block to map every acceptance criterion to a
new test; a `CONTRADICTS SPEC:` line sends the task to needs-attention."""
import json
import os

import pytest
from conftest import commit_in, git, hook_input, hook_out, run_script, task_in, task_state

import progress
import state


def plan_task(repo, phase="implement", **fields):
    wt = task_in(repo, phase, baseline={"passed": 1, "failed": 0}, red_check={"passed": 1, "failed": 1}, **fields)
    return wt


def step_done(repo, message="Added sub() to app.py.\nTests: 2 passed, 0 failed.", agent_type="rehorse:rehorse-step"):
    payload = dict(hook_input("subagentstop_step"), cwd=str(repo), agent_type=agent_type, last_assistant_message=message)
    return hook_out(run_script("step_done", stdin=payload, cwd=str(repo)))


def progress_md(repo):
    return (repo / "rehorse-reports" / "PROGRESS.md").read_text()



def test_other_agents_and_other_phases_are_ignored(repo):
    plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}])
    assert step_done(repo, agent_type="general-purpose") is None
    assert step_done(repo, agent_type="") is None  # the compact summarizer
    assert task_state(repo)["plan"][0]["done"] is False
    for phase in ["spec", "verify", "report"]:
        s = state.load(str(repo))
        s["tasks"]["t-1"]["phase"] = phase
        state.save(str(repo), s)
        assert step_done(repo) is None, phase


def test_step_with_untested_edits_is_blocked_with_the_test_command(repo):
    wt = plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}], edit_seq=3,
                   last_test_run={"passed": 1, "failed": 0, "after_edit_seq": 2})
    out = step_done(repo)
    assert out["decision"] == "block" and "cd %s && python3 -m pytest -q" % wt in out["reason"]
    assert task_state(repo)["stop_blocks"] == 1 and task_state(repo)["plan"][0]["done"] is False


def test_step_with_a_dirty_worktree_is_blocked_with_the_exact_commit_command(repo):
    wt = plan_task(repo, plan=[{"title": "Add sub()", "done": False, "summary": None, "commit": None}], edit_seq=1,
                   last_test_run={"passed": 1, "failed": 0, "after_edit_seq": 1})
    (repo / ".rehorse" / "worktrees" / "t-1" / "app.py").write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    out = step_done(repo)
    assert out["decision"] == "block"
    assert 'cd %s && git add -A && git commit -m "step 1: Add sub()"' % wt in out["reason"]
    assert "app.py" in out["reason"]
    assert task_state(repo)["plan"][0]["done"] is False


def test_committed_and_tested_step_is_marked_done_with_summary_and_commit(repo):
    wt = plan_task(repo, plan=[{"title": "Add sub()", "done": False, "summary": None, "commit": None},
                               {"title": "B", "done": False, "summary": None, "commit": None}], edit_seq=1,
                   last_test_run={"passed": 1, "failed": 0, "after_edit_seq": 1}, stop_blocks=2)
    sha = commit_in(wt, "app.py", "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n", "step 1")
    assert step_done(repo, "Added sub() to app.py.\nTests: 2 passed, 0 failed.\n\nextra prose the orchestrator never sees") is None
    t = task_state(repo)
    assert t["plan"][0] == {"title": "Add sub()", "done": True, "summary": "Added sub() to app.py.\nTests: 2 passed, 0 failed.", "commit": sha[:7]}
    assert t["step"] == 1 and t["stop_blocks"] == 0
    assert "- [x] 1. Add sub()" in progress_md(repo) and "- [ ] 2. B" in progress_md(repo)


def test_step_done_after_the_last_step_leaves_the_pointer_at_the_end(repo):
    wt = plan_task(repo, plan=[{"title": "A", "done": True, "summary": "x", "commit": "c"}], step=1, edit_seq=0)
    assert step_done(repo) is None
    assert task_state(repo)["step"] == 1


def test_eighth_consecutive_block_moves_the_task_to_needs_attention(repo):
    wt = plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}], edit_seq=2, stop_blocks=7,
                   last_test_run={"passed": 1, "failed": 0, "after_edit_seq": 1})
    out = step_done(repo)
    assert (out or {}).get("decision") != "block" and "needs-attention" in out["systemMessage"]
    assert task_state(repo)["phase"] == "needs-attention"


def test_tests_phase_agent_must_commit_but_no_plan_step_is_touched(repo):
    wt = plan_task(repo, "tests", edit_seq=1, last_test_run={"passed": 1, "failed": 1, "after_edit_seq": 1})
    (repo / ".rehorse" / "worktrees" / "t-1" / "tests" / "test_sub.py").write_text("def test_sub(): assert 0\n")
    out = step_done(repo)
    assert out["decision"] == "block" and 'git commit -m "tests: ' in out["reason"]
    commit_in(wt, "tests/test_sub.py", "def test_sub(): assert 0\n", "tests: sub")
    out = step_done(repo)  # committed: the next thing missing is the coverage block (no spec section either)
    assert out["decision"] == "block" and "coverage" in out["reason"]
    assert task_state(repo)["plan"] == [] and task_state(repo)["step"] == 0


def test_setup_phase_next_action_and_step_done_require_a_commit_but_no_test_run(repo):
    wt = plan_task(repo, "setup", test_cmd=None, edit_seq=3)
    s = state.load(str(repo))
    assert "harness" in progress.next_action(s["tasks"]["t-1"]) and "testcmd.py set" in progress.next_action(s["tasks"]["t-1"])
    (repo / ".rehorse" / "worktrees" / "t-1" / "tests" / "test_harness.py").write_text("def test_smoke(): pass\n")
    out = step_done(repo, "Added a pytest harness.\nRun: python3 -m pytest -q")
    assert out["decision"] == "block" and 'git commit -m "setup: test harness for t-1"' in out["reason"]
    commit_in(wt, "tests/test_harness.py", "def test_smoke(): pass\n", "setup: test harness for t-1")
    assert step_done(repo, "Added a pytest harness.\nRun: python3 -m pytest -q") is None  # no test_cmd yet: no run required


def test_verifier_stop_is_never_a_step_done(repo):
    """The verifier fires the same SubagentStop event; its stop must not close a plan step (verify.py --verdict handles it)."""
    plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}])
    for agent in ["rehorse:rehorse-verifier", "rehorse-verifier"]:
        assert step_done(repo, agent_type=agent) is None
    t = task_state(repo)
    assert t["plan"][0]["done"] is False and t["step"] == 0 and t["stop_blocks"] == 0


def test_contradicts_spec_line_in_a_step_summary_sets_needs_attention_instead_of_continuing(repo):
    wt = plan_task(repo, plan=[{"title": "Fix (verifier round 1): reject strings", "done": False, "summary": None, "commit": None}],
                   edit_seq=1, last_test_run={"passed": 3, "failed": 1, "after_edit_seq": 1, "output": ""})
    line = "CONTRADICTS SPEC: tests/test_rehorse_verify_t-1.py::test_strings expects TypeError, acceptance criterion 2 says ValueError"
    out = step_done(repo, "I could not make this pass without breaking the spec.\n" + line)
    assert out and "decision" not in out and "needs-attention" in out["systemMessage"] and "TypeError" in out["systemMessage"]
    t = task_state(repo)
    assert t["phase"] == "needs-attention" and t["attention"] == {"reason": line, "prior_phase": "implement"}
    assert t["plan"][0]["done"] is False and t["step"] == 0
    assert line in progress_md(repo)


# ---- tests phase: the reply must map every acceptance criterion to a new test ---------------------------------------

SPEC = "Add sub and mul.\n\n## Acceptance criteria\n1. sub(5, 3) == 2\n2. mul(2, 3) == 6\n"
TESTS = "import app\n\ndef test_sub():\n    assert app.sub(5, 3) == 2\n\ndef test_mul():\n    assert app.mul(2, 3) == 6\n"
BLOCK = '```json\n{"coverage": [{"criterion": "1. sub(5, 3) == 2", "ref": "tests/test_new.py::test_sub"}, {"criterion": 2, "ref": "tests/test_new.py::test_mul"}]}\n```'


def red_task(repo):
    wt = plan_task(repo, "tests", edit_seq=1, last_test_run={"passed": 1, "failed": 2, "after_edit_seq": 1, "output": ""})
    open(os.path.join(wt, "REHORSE_SPEC.md"), "w").write(SPEC)
    commit_in(wt, "tests/test_new.py", TESTS, "tests: red for t-1")
    return wt


def test_tests_phase_reply_without_a_coverage_block_is_blocked(repo):
    red_task(repo)
    out = step_done(repo, "Added tests/test_new.py.\nBoth fail: no sub, no mul.")
    assert out["decision"] == "block" and "```json" in out["reason"] and '"coverage"' in out["reason"] and "acceptance criterion" in out["reason"]
    assert task_state(repo)["coverage"] == []


def test_tests_phase_reply_with_an_uncovered_criterion_is_blocked_naming_it(repo):
    red_task(repo)
    out = step_done(repo, 'Added tests.\nOne fails.\n```json\n{"coverage": [{"criterion": 1, "ref": "tests/test_new.py::test_sub"}]}\n```')
    assert out["decision"] == "block" and "2. mul(2, 3) == 6" in out["reason"] and "1. sub" not in out["reason"]
    assert task_state(repo)["coverage"] == [{"criterion": "1", "ref": "tests/test_new.py::test_sub"}]


def test_tests_phase_reply_with_full_coverage_is_recorded_and_allowed(repo):
    red_task(repo)
    assert step_done(repo, "Added tests/test_new.py.\nBoth fail.\n" + BLOCK) is None
    t = task_state(repo)
    assert t["coverage"] == [{"criterion": "1. sub(5, 3) == 2", "ref": "tests/test_new.py::test_sub"}, {"criterion": "2", "ref": "tests/test_new.py::test_mul"}]
    assert t["stop_blocks"] == 0
    r = run_script("state", ["advance", "implement"], cwd=str(repo))
    assert r.returncode == 0, r.stderr


def test_coverage_is_checked_after_the_test_run_and_the_commit(repo):
    wt = red_task(repo)
    open(os.path.join(wt, "tests", "test_more.py"), "w").write("def test_x():\n    assert 0\n")
    out = step_done(repo, "x\ny\n" + BLOCK)
    assert "git commit" in out["reason"]


def test_hooks_json_routes_step_stops_to_step_done():
    hooks = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "hooks.json")))["hooks"]
    entries = {h["hooks"][0]["args"][0].rsplit("/", 1)[-1]: h.get("matcher") for h in hooks["SubagentStop"]}
    assert entries == {"step_done.py": "^rehorse:rehorse-step$", "verify.py": "^rehorse:rehorse-verifier$"}
