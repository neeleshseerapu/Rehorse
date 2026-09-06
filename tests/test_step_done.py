"""step_done.py (SubagentStop for rehorse-step agents): closes a plan step only when tests ran after the last edit and the
worktree is committed; in the tests phase also requires the reply's coverage block to map every acceptance criterion to a
new test; a `CONTRADICTS SPEC:` line sends the task to needs-attention."""
import json
import os
import shutil
import sys

import pytest
from conftest import PINNED_FIXTURE as FIXTURE, commit_in, git, hook_input, hook_out, run_script, task_in, task_state

import progress
import state


def plan_task(repo, phase="implement", **fields):
    wt = task_in(repo, phase, baseline={"passed": 1, "failed": 0}, red_check={"passed": 1, "failed": 1, "new_failed": 1}, **fields)
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
    assert t["plan"][0] == {"title": "Add sub()", "done": True, "summary": "Added sub() to app.py.\nTests: 2 passed, 0 failed.", "commit": sha[:7],
                            "satisfied_by": None}
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


def test_a_contradicts_spec_line_naming_a_test_routes_the_task_to_the_tests_phase(repo):
    """The implementer cannot edit a test, so the claim goes where the decision belongs. The step stays open: it is the
    step the task resumes at once the test question is settled, and the plan it belongs to must survive the trip."""
    plan_task(repo, plan=[{"title": "Fix (verifier round 1): reject strings", "done": False, "summary": None, "commit": None}],
              edit_seq=1, last_test_run={"passed": 3, "failed": 1, "after_edit_seq": 1, "output": ""})
    line = "CONTRADICTS SPEC: tests/test_rehorse_verify_t-1.py::test_strings expects TypeError, acceptance criterion 2 says ValueError"
    out = step_done(repo, "I could not make this pass without breaking the spec.\n" + line)
    t = task_state(repo)
    assert t["phase"] == "tests" and t["attention"] is None
    assert t["verify_round"] == 1 and t["plan"][0]["done"] is False and t["step"] == 0
    h = t["verify_history"][-1]
    assert h["from"] == "implement" and h["round"] == 1 and h["verdict"] == "contradicts spec"
    assert h["revision"] == [{"test": "tests/test_rehorse_verify_t-1.py::test_strings", "why": line}]
    assert "decision" not in out and "back to tests" in out["systemMessage"].lower() and "round 1 of 3" in out["systemMessage"]
    assert "tests/test_rehorse_verify_t-1.py::test_strings" in progress_md(repo)


def test_the_tests_phase_is_told_who_claimed_what_and_that_it_may_disagree(repo):
    """A second opinion is worth nothing if it only hears "rewrite this": PROGRESS.md carries the claim verbatim and
    both answers open to it."""
    plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}], edit_seq=1,
              last_test_run={"passed": 1, "failed": 1, "after_edit_seq": 1, "output": ""})
    line = "CONTRADICTS SPEC: tests/test_app.py::test_add pins the off-by-one criterion 1 calls the bug"
    step_done(repo, "Cannot finish.\n" + line)
    md = progress_md(repo)
    assert "step 1 sent this back to tests" in md and line in md
    assert "expected_test_changes" in md and "CONTRADICTS SPEC:" in md and "judges for itself" in md


def test_a_contradicts_spec_line_naming_no_test_stops_the_task_with_the_reason(repo):
    """A claim about a test nobody named is routable nowhere — the same rule that drops a pins_bug flag with no test id."""
    plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}], edit_seq=1,
              last_test_run={"passed": 3, "failed": 1, "after_edit_seq": 1, "output": ""})
    line = "CONTRADICTS SPEC: the suite expects TypeError, acceptance criterion 2 says ValueError"
    out = step_done(repo, "I could not make this pass without breaking the spec.\n" + line)
    t = task_state(repo)
    assert t["phase"] == "needs-attention" and t["attention"]["prior_phase"] == "implement"
    assert t["attention"]["reason"].startswith(line) and "no test id named" in t["attention"]["reason"]
    assert "needs-attention" in out["systemMessage"] and t["verify_round"] == 0


def test_the_last_round_is_not_spent_on_a_trip_to_the_tests_phase(repo):
    """The cap counts every trip back, whoever bought it. On the last one the task stops instead, with the claim."""
    plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}], edit_seq=1, verify_round=2,
              last_test_run={"passed": 3, "failed": 1, "after_edit_seq": 1, "output": ""})
    payload = dict(hook_input("subagentstop_step_contradicts"), cwd=str(repo))
    out = hook_out(run_script("step_done", stdin=payload, cwd=str(repo)))
    t = task_state(repo)
    assert t["phase"] == "needs-attention" and t["verify_round"] == 2
    assert "tests/test_columns.py::test_render" in t["attention"]["reason"]
    assert "round 3 of 3" in t["attention"]["reason"] and "spent" in t["attention"]["reason"]
    assert (repo / t["report_path"]).exists() and "decision" not in out


def test_the_tests_phase_disagreeing_stops_the_task_with_both_claims(repo):
    """The one outcome nobody can automate: two agents that have both read the spec, disagreeing about a test. The user
    gets each claim in the banner, from the agent that made it."""
    plan_task(repo, "tests", edit_seq=1, verify_round=1,
              last_test_run={"passed": 1, "failed": 1, "after_edit_seq": 1, "output": ""},
              verify_history=[{"round": 1, "verdict": "contradicts spec", "from": "implement", "tests": None, "findings": [],
                               "revision": [{"test": "tests/test_app.py::test_add", "why": "CONTRADICTS SPEC: it pins the bug"}]}])
    line = "CONTRADICTS SPEC: tests/test_app.py::test_add is right; criterion 1 is about widths, not sums"
    out = step_done(repo, "The claim does not hold.\n" + line)
    t = task_state(repo)
    assert t["phase"] == "needs-attention" and t["attention"]["prior_phase"] == "tests"
    assert t["attention"]["reason"].startswith(line)
    assert "CONTRADICTS SPEC: it pins the bug" in t["attention"]["reason"], "the claim it was sent to answer"
    assert "needs-attention" in out["systemMessage"]
    text = (repo / t["report_path"]).read_text()
    assert "Round 1: CONTRADICTS SPEC" in text and "its run" not in text, "the round is in the report; it bought no verifier run"
    assert "Round 1: test revision (tests/test_app.py::test_add" in text
    assert "Step: round 1 CONTRADICTS SPEC" in progress_md(repo)


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


# ---- a step closed with no edits is "already satisfied", not completed work ---------------------------------------------

def test_step_closed_on_an_unchanged_head_is_marked_satisfied_by_the_step_that_did_the_work(repo):
    wt = plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None},
                               {"title": "B", "done": False, "summary": None, "commit": None}], edit_seq=1,
                   last_test_run={"passed": 2, "failed": 0, "after_edit_seq": 1, "output": ""})
    sha = commit_in(wt, "app.py", "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n", "step 1: A")[:7]
    assert step_done(repo, "Added sub().\nGreen.") is None
    assert step_done(repo, "No edits: sub() from step 1 already covers it.\nGreen.") is None
    plan = task_state(repo)["plan"]
    assert plan[0]["commit"] == sha and plan[0].get("satisfied_by") is None
    assert plan[1]["done"] and plan[1]["commit"] == sha and plan[1]["satisfied_by"] == 1
    assert "2. B — already satisfied by step 1" in progress_md(repo)


# ---- tests phase: an existing test may only be changed when the reply says why ---------------------------------------

PINNED_BLOCK = ('```json\n{"coverage": [{"criterion": 1, "ref": "tests/test_app.py::test_truncate_fits_the_width"}, '
                '{"criterion": 2, "ref": "tests/test_app.py::test_short_text_is_returned_unchanged"}], '
                '"expected_test_changes": [{"test": "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis", '
                '"why": "it pins the off-by-one the spec calls the bug (criterion 1)"}]}\n```')


def pinned_task(repo, tests):
    """The tests phase of that repo, having rewritten the pinned assertion and added a test for criterion 1."""
    wt = plan_task(repo, "tests", edit_seq=1, last_test_run={"passed": 1, "failed": 1, "after_edit_seq": 1, "output": ""})
    shutil.copy(os.path.join(FIXTURE, "REHORSE_SPEC.md"), os.path.join(wt, "REHORSE_SPEC.md"))
    commit_in(wt, "tests/test_app.py", tests, "tests: red for t-1")
    return wt


ORIGINAL = open(os.path.join(FIXTURE, "tests", "test_app.py")).read()
NEW_TEST = "\n\ndef test_truncate_fits_the_width():\n    assert len(truncate(\"abcdefgh\", 5)) == 5\n"
# the pinned assertion rewritten to what criterion 1 requires, plus one new test: only the first needs declaring
REWRITTEN = ORIGINAL.replace('== "abcde…"', '== "abcd…"') + NEW_TEST


def test_changing_an_existing_test_without_saying_why_is_blocked_naming_it(pinned_repo):
    pinned_task(pinned_repo, REWRITTEN)
    out = step_done(pinned_repo, "Rewrote the pinned assertion.\nOne fails.\n" + PINNED_BLOCK.replace(
        '"expected_test_changes": [{"test": "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis", '
        '"why": "it pins the off-by-one the spec calls the bug (criterion 1)"}]', '"expected_test_changes": []'))
    assert out["decision"] == "block"
    assert "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis" in out["reason"]
    assert "expected_test_changes" in out["reason"] and "REHORSE_SPEC.md" in out["reason"]
    assert task_state(pinned_repo)["expected_test_changes"] == []


def test_a_declared_change_is_recorded_with_its_reason_and_allowed(pinned_repo):
    pinned_task(pinned_repo, REWRITTEN)
    assert step_done(pinned_repo, "Rewrote the pinned assertion.\nOne fails.\n" + PINNED_BLOCK) is None
    t = task_state(pinned_repo)
    assert t["expected_test_changes"] == [{"test": "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis",
                                           "why": "it pins the off-by-one the spec calls the bug (criterion 1)"}]
    assert task_state(pinned_repo)["coverage"], "the coverage mapping is still recorded alongside it"


def test_adding_tests_without_touching_the_existing_ones_needs_no_declaration(pinned_repo):
    pinned_task(pinned_repo, ORIGINAL + NEW_TEST)
    assert step_done(pinned_repo, "Added one test.\nIt fails.\n" + PINNED_BLOCK.replace(
        '"expected_test_changes": [{"test": "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis", '
        '"why": "it pins the off-by-one the spec calls the bug (criterion 1)"}]', '"expected_test_changes": []')) is None
    assert task_state(pinned_repo)["expected_test_changes"] == []


def test_advance_also_refuses_an_undeclared_rewrite_so_the_orchestrator_cannot_skip_the_gate(pinned_repo):
    """The subagent's stop hook is not the only door: state.py re-checks, as it does for coverage."""
    pinned_task(pinned_repo, REWRITTEN)
    s = state.load(str(pinned_repo))
    s["tasks"]["t-1"]["coverage"] = [{"criterion": "1", "ref": "tests/test_app.py::test_truncate_fits_the_width"},
                                     {"criterion": "2", "ref": "tests/test_app.py::test_short_text_is_returned_unchanged"}]
    state.save(str(pinned_repo), s)  # coverage satisfied, so the rewrite is the only thing left to object to
    r = run_script("state", ["advance", "implement"], cwd=str(pinned_repo))
    assert r.returncode != 0 and "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis" in (r.stdout + r.stderr)
    s = state.load(str(pinned_repo))
    s["tasks"]["t-1"]["expected_test_changes"] = [{"test": "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis", "why": "criterion 1"}]
    state.save(str(pinned_repo), s)
    r = run_script("state", ["advance", "implement"], cwd=str(pinned_repo))
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_second_tests_phase_keeps_the_first_rounds_declarations(pinned_repo):
    """A test-revision round trip re-enters the tests phase, and changed_existing_tests() still sees every rewrite made
    since base_sha. The reply only has to declare what it changed this round; reasons already recorded stand."""
    wt = pinned_task(pinned_repo, REWRITTEN)
    assert step_done(pinned_repo, "Rewrote the pinned assertion.\nOne fails.\n" + PINNED_BLOCK) is None
    commit_in(wt, "tests/test_app.py", REWRITTEN.replace('truncate("abc", 5) == "abc"', 'truncate("abc", 9) == "abc"'), "tests: round 2")
    later = PINNED_BLOCK.replace(
        '{"test": "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis", '
        '"why": "it pins the off-by-one the spec calls the bug (criterion 1)"}',
        '{"test": "tests/test_app.py::test_short_text_is_returned_unchanged", "why": "criterion 2 says any width over the length"}')
    assert step_done(pinned_repo, "Widened the short-text case.\nOne fails.\n" + later) is None
    recorded = {c["test"]: c["why"] for c in task_state(pinned_repo)["expected_test_changes"]}
    assert set(recorded) == {"tests/test_app.py::test_long_text_is_cut_with_an_ellipsis",
                             "tests/test_app.py::test_short_text_is_returned_unchanged"}
    assert recorded["tests/test_app.py::test_long_text_is_cut_with_an_ellipsis"].startswith("it pins the off-by-one")


def test_a_contradicts_spec_stop_during_implement_leaves_the_user_a_report(repo):
    """The rich-3871 shape, from its own captured hook input, on its last round: the claim can buy no further trip to
    the tests phase, so the task stops and the turn ends there. Nobody is left to run report.py, so the hook renders
    it: the report exists, its banner is the reason, and the systemMessage points at it."""
    wt = plan_task(repo, plan=[{"title": "Make _get_padding_width honor pad_edge", "done": False, "summary": None, "commit": None}],
                   edit_seq=8, verify_round=2, last_test_run={"passed": 931, "failed": 1, "after_edit_seq": 8, "output": ""})
    payload = dict(hook_input("subagentstop_step_contradicts"), cwd=str(repo))
    out = hook_out(run_script("step_done", stdin=payload, cwd=str(repo)))
    t = task_state(repo)
    line = t["attention"]["reason"]
    assert line.startswith("CONTRADICTS SPEC: `tests/test_columns.py::test_render`")
    assert t["phase"] == "needs-attention" and t["attention"]["prior_phase"] == "implement"
    report_path = repo / t["report_path"]
    assert report_path.exists(), "a needs-attention stop must never leave the user without a report"
    text = report_path.read_text()
    assert "## NEEDS ATTENTION: %s (was in implement)" % line in text
    assert "## Verifier: not run" in text and "cd %s" % wt in text  # the unfinished phases still render
    assert str(report_path) in out["systemMessage"] and "needs-attention" in out["systemMessage"]


def test_the_report_of_a_stop_is_committed_on_the_rehearsal_branch_like_any_other(repo):
    """The evidence trail does not depend on how the task ended: /rehorse:merge carries a stop's report too."""
    plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}],
              edit_seq=1, last_test_run={"passed": 1, "failed": 0, "after_edit_seq": 1, "output": ""})
    step_done(repo, "Cannot proceed.\nCONTRADICTS SPEC: no test named here, so there is nothing to route")
    name = os.path.basename(task_state(repo)["report_path"])
    committed = git(repo / ".rehorse" / "worktrees" / "t-1", "show", "--stat", "HEAD")
    assert "rehorse: report for t-1" in committed and name in committed


# ---- end to end: a step finds the pinned test, the tests phase settles it, the suite goes green -------------------

PINNED = "tests/test_app.py::test_long_text_is_cut_with_an_ellipsis"
CORRECT_FIX = ("def truncate(text, width):\n    if len(text) <= width:\n        return text\n"
               "    return text[:width - 1] + \"…\"\n")


def pytest_in(wt):
    """A real run of the fixture's suite in the worktree: (passed, failed)."""
    import re
    import subprocess
    out = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=wt, capture_output=True, text=True).stdout
    return (int((re.search(r"(\d+) passed", out) or [0, 0])[1]), int((re.search(r"(\d+) failed", out) or [0, 0])[1]))


def implementing(repo, **fields):
    """That repo mid-implementation: the red tests committed, the correct fix committed, the pinned test still failing."""
    wt = plan_task(repo, "implement", test_paths=["tests/"],
                   plan=[{"title": "keep the ellipsis inside the budget", "done": False, "summary": None, "commit": None}],
                   edit_seq=2, last_test_run={"passed": 2, "failed": 1, "after_edit_seq": 2, "output": ""}, **fields)
    shutil.copy(os.path.join(FIXTURE, "REHORSE_SPEC.md"), os.path.join(wt, "REHORSE_SPEC.md"))
    tests_sha = commit_in(wt, "tests/test_app.py", ORIGINAL + NEW_TEST, "tests: red for t-1")
    commit_in(wt, "app.py", CORRECT_FIX, "step 1: keep the ellipsis inside the budget")
    s = state.load(str(repo))
    s["tasks"]["t-1"]["tests_sha"] = tests_sha
    state.save(str(repo), s)
    return wt


def revise(repo, wt):
    """The tests phase doing what it was sent back to do: rewrite the pinned assertion and declare why."""
    commit_in(wt, "tests/test_app.py", REWRITTEN, "tests: revise the pinned assertion")
    s = state.load(str(repo))
    s["tasks"]["t-1"]["last_test_run"]["after_edit_seq"] = s["tasks"]["t-1"]["edit_seq"]
    state.save(str(repo), s)
    return step_done(repo, "Revised the pinned assertion.\nGreen.\n" + PINNED_BLOCK)


def test_a_step_can_send_the_pinned_test_back_and_the_task_goes_green(pinned_repo):
    """rich-3871's shape end to end, and rich-3577's from the other side. The tests phase missed that an existing test
    pinned the bug; the implementer hits it, may not touch it, and says so naming the test. That used to end the run
    with a sentence of homework. Now the tests phase decides, declares the rewrite, and implementation resumes."""
    wt = implementing(pinned_repo)
    assert pytest_in(wt) == (2, 1), "the correct fix leaves the pinned test failing: that is the whole problem"
    out = step_done(pinned_repo, "The fix matches criterion 1.\nThe suite is red on a test I may not touch.\n"
                    "CONTRADICTS SPEC: %s asserts the six-cell result criterion 1 calls the bug" % PINNED)
    assert task_state(pinned_repo)["phase"] == "tests" and PINNED in out["systemMessage"]

    assert revise(pinned_repo, wt) is None
    assert task_state(pinned_repo)["expected_test_changes"] == [
        {"test": PINNED, "why": "it pins the off-by-one the spec calls the bug (criterion 1)"}]

    r = run_script("state", ["advance", "implement"], cwd=str(pinned_repo))
    assert r.returncode == 0, r.stdout + r.stderr
    t = task_state(pinned_repo)
    assert t["phase"] == "implement" and t["step"] == 0 and t["plan"][0]["done"] is False, "resumes at the step it left"
    assert pytest_in(wt) == (3, 0), "green once the test that pinned the bug says what the spec says"


def test_the_plan_survives_the_trip_to_the_tests_phase(pinned_repo):
    """`progress.py plan` would reset the plan and drop the step the task is meant to resume at. It already refuses once
    a round trip has been recorded, and a step's trip is recorded where the verifier's is, so it refuses this one too."""
    wt = implementing(pinned_repo)
    step_done(pinned_repo, "Cannot finish.\nCONTRADICTS SPEC: %s pins the bug (criterion 1)" % PINNED)
    assert revise(pinned_repo, wt) is None
    assert run_script("state", ["advance", "implement"], cwd=str(pinned_repo)).returncode == 0
    r = run_script("progress", ["plan", "B"], cwd=str(pinned_repo))
    assert r.returncode != 0 and "would drop the round-trip steps" in (r.stdout + r.stderr)
    assert task_state(pinned_repo)["plan"][0]["title"] == "keep the ellipsis inside the budget"
