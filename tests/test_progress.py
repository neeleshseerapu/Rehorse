"""progress.py: PROGRESS.md is regenerated from state, never free-formed; --step-done (SubagentStop) closes a plan step
only when tests ran after the last edit and the worktree is committed."""
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
    return hook_out(run_script("progress", ["--step-done"], stdin=payload, cwd=str(repo)))


def progress_md(repo):
    return (repo / "rehorse-reports" / "PROGRESS.md").read_text()


# ---- render -------------------------------------------------------------------

def test_render_writes_one_section_per_task_from_state(repo):
    plan_task(repo, plan=[{"title": "Add sub()", "done": True, "summary": "Added sub().\nTests green.", "commit": "abc1234"},
                          {"title": "Wire the CLI", "done": False, "summary": None, "commit": None}], step=1)
    text = progress.render(str(repo), state.load(str(repo)))
    assert text == progress_md(repo)
    assert "## t-1" in text and "implement" in text and "step 2/3" not in text and "step 2/2" in text
    assert "- [x] 1. Add sub()" in text and "Added sub(). Tests green." in text and "abc1234" in text
    assert "- [ ] 2. Wire the CLI" in text
    assert "baseline 1 passed / 0 failed" in text and "red 1 passed / 1 failed" in text
    assert "Next:" in text and "Wire the CLI" in text and "rehorse-step" in text


def test_next_action_per_phase(repo):
    plan_task(repo, "implement", plan=[{"title": "A", "done": True, "summary": "x", "commit": "c"}], step=1)
    assert "advance verify" in progress.next_action(state.load(str(repo))["tasks"]["t-1"])
    for phase, needle in [("spec", "baseline"), ("tests", "red"), ("verify", "report.py"), ("report", "/rehorse:merge t-1")]:
        s = state.load(str(repo))
        s["tasks"]["t-1"]["phase"] = phase
        assert needle in progress.next_action(s["tasks"]["t-1"]), phase


def test_render_shows_needs_attention_reason_and_terminal_tasks_as_one_line(repo):
    plan_task(repo)
    s = state.load(str(repo))
    state.advance(s, "t-1", "needs-attention", reason="8 consecutive Stop blocks")
    text = progress.render(str(repo), s)
    assert "NEEDS ATTENTION" in text and "8 consecutive Stop blocks" in text and "advance implement" in text
    state.advance(s, "t-1", "discarded")
    text = progress.render(str(repo), s)
    assert "discarded" in text and "- [ ]" not in text


# ---- plan -----------------------------------------------------------------------

def test_plan_records_steps_and_the_tests_sha_on_a_clean_worktree(repo):
    wt = plan_task(repo)
    sha = git(wt, "rev-parse", "HEAD").strip()
    r = run_script("progress", ["plan", "Add sub()", "Wire the CLI"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    t = task_state(repo)
    assert [p["title"] for p in t["plan"]] == ["Add sub()", "Wire the CLI"] and t["step"] == 0 and t["tests_sha"] == sha
    assert "- [ ] 1. Add sub()" in progress_md(repo)


def test_plan_refuses_a_dirty_worktree_with_the_exact_git_command(repo):
    wt = plan_task(repo)
    (repo / ".rehorse" / "worktrees" / "t-1" / "tests" / "test_new.py").write_text("def test_x(): assert 0\n")
    r = run_script("progress", ["plan", "A"], cwd=str(repo))
    assert r.returncode != 0 and "cd %s && git add -A && git commit" % wt in r.stderr
    assert task_state(repo)["plan"] == []


def test_plan_is_implement_only_and_limited_to_six_steps(repo):
    plan_task(repo, "tests")
    assert run_script("progress", ["plan", "A"], cwd=str(repo)).returncode != 0
    plan_task.__wrapped__ = None
    import worktree
    worktree.remove(str(repo), "t-1")
    plan_task(repo, "implement")
    assert run_script("progress", ["plan"] + list("ABCDEFG"), cwd=str(repo)).returncode != 0
    assert run_script("progress", ["plan"] + list("ABCDEF"), cwd=str(repo)).returncode == 0


def test_add_appends_steps_for_a_split(repo):
    plan_task(repo, plan=[{"title": "A", "done": False, "summary": None, "commit": None}], step=0)
    r = run_script("progress", ["add", "A part 2", "A part 3"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    assert [p["title"] for p in task_state(repo)["plan"]] == ["A", "A part 2", "A part 3"]


# ---- --step-done (SubagentStop) -------------------------------------------------

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
    assert step_done(repo) is None
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
