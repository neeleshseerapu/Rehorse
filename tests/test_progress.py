"""progress.py: PROGRESS.md is regenerated from state, never free-formed; `plan` and `add` maintain the plan."""
import json
import os

import pytest
from conftest import commit_in, git, run_script, task_in, task_state

import progress
import state


def plan_task(repo, phase="implement", **fields):
    wt = task_in(repo, phase, baseline={"passed": 1, "failed": 0}, red_check={"passed": 1, "failed": 1, "new_failed": 1}, **fields)
    return wt


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
    for phase, needle in [("spec", "baseline"), ("tests", "red"), ("verify", "verify.py brief"), ("report", "/rehorse:merge t-1")]:
        s = state.load(str(repo))
        s["tasks"]["t-1"]["phase"] = phase
        assert needle in progress.next_action(s["tasks"]["t-1"]), phase
    s["tasks"]["t-1"].update(phase="verify", verifier={"round": 1, "verdict": "concerns", "findings": [], "tests_added": [], "coverage": []})
    assert "report.py" in progress.next_action(s["tasks"]["t-1"]) and "concerns" in progress.next_action(s["tasks"]["t-1"])


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


