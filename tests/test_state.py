"""state.py: the single source of truth. Phases move only through advance()."""
import json
import os

import pytest
from conftest import git, hook_input, run_script

import state


def test_task_id_is_date_and_kebab_slug_capped_at_six_words():
    tid = state.task_id("Add a Dark Mode toggle to the settings page!", date="20260903")
    assert tid == "t-20260903-add-a-dark-mode-toggle-to"


def test_new_task_sets_defaults_and_becomes_active():
    s = state.empty()
    task = state.new_task(s, "t-20260903-dark-mode")
    assert s["active_task"] == "t-20260903-dark-mode"
    assert task["phase"] == "spec"
    assert task["edit_seq"] == 0 and task["stop_blocks"] == 0
    assert task["attention"] is None and task["last_test_run"] is None
    assert task["worktree"] == ".rehorse/worktrees/t-20260903-dark-mode"
    assert task["branch"] == "rehorse/t-20260903-dark-mode"


def test_new_task_with_existing_id_gets_rehearsal_suffix():
    s = state.empty()
    state.new_task(s, "t-20260903-x")
    assert state.new_task(s, "t-20260903-x")["id"] == "t-20260903-x-r2"
    assert state.new_task(s, "t-20260903-x")["id"] == "t-20260903-x-r3"


def test_save_and_load_roundtrip_creates_rehorse_dir(tmp_path):
    s = state.empty()
    state.new_task(s, "t-1")
    state.save(str(tmp_path), s)
    assert os.path.exists(tmp_path / ".rehorse" / "state.json")
    assert state.load(str(tmp_path)) == s


def test_load_missing_file_returns_empty_state(tmp_path):
    assert state.load(str(tmp_path)) == {"active_task": None, "tasks": {}}


def test_advance_walks_the_phase_order_only():
    s = state.empty()
    state.new_task(s, "t-1")
    for phase in ["tests", "implement", "verify", "report", "merged"]:
        state.advance(s, "t-1", phase)
        assert s["tasks"]["t-1"]["phase"] == phase
    assert s["active_task"] is None  # terminal phase clears the active pointer


@pytest.mark.parametrize("bad", ["implement", "verify", "spec", "merged", "bogus"])
def test_advance_rejects_skips_and_unknown_phases(bad):
    s = state.empty()
    state.new_task(s, "t-1")  # phase: spec
    with pytest.raises(ValueError):
        state.advance(s, "t-1", bad)


def test_merged_only_from_report_but_discarded_from_anywhere():
    s = state.empty()
    state.new_task(s, "t-1")
    state.advance(s, "t-1", "tests")
    with pytest.raises(ValueError):
        state.advance(s, "t-1", "merged")
    state.advance(s, "t-1", "discarded")
    assert s["tasks"]["t-1"]["phase"] == "discarded"
    with pytest.raises(ValueError):  # terminal is terminal
        state.advance(s, "t-1", "discarded")


def test_needs_attention_records_reason_and_resumes_to_prior_phase():
    s = state.empty()
    state.new_task(s, "t-1")
    state.advance(s, "t-1", "tests")
    state.advance(s, "t-1", "implement")
    s["tasks"]["t-1"]["stop_blocks"] = 8
    state.advance(s, "t-1", "needs-attention", reason="8 consecutive Stop blocks without a test run")
    t = s["tasks"]["t-1"]
    assert t["phase"] == "needs-attention"
    assert t["attention"] == {"reason": "8 consecutive Stop blocks without a test run", "prior_phase": "implement"}
    with pytest.raises(ValueError):
        state.advance(s, "t-1", "verify")  # may not skip ahead out of attention
    state.advance(s, "t-1", "implement")
    assert t["phase"] == "implement" and t["attention"] is None and t["stop_blocks"] == 0


def test_find_root_from_inside_a_worktree_is_the_main_checkout(tmp_path):
    (tmp_path / ".git").mkdir()
    wt = tmp_path / ".rehorse" / "worktrees" / "t-1" / "src" / "pkg"
    wt.mkdir(parents=True)
    assert state.find_root(str(wt)) == os.path.realpath(tmp_path)
    assert state.find_root(str(tmp_path / "src")) == os.path.realpath(tmp_path)


def test_find_root_returns_none_outside_any_repo(tmp_path):
    assert state.find_root(str(tmp_path)) is None


def test_summary_line_for_no_task_active_and_attention():
    s = state.empty()
    assert state.summary(s) == "REHORSE: no active task."
    t = state.new_task(s, "t-20260903-dark-mode")
    state.advance(s, "t-20260903-dark-mode", "tests")
    state.advance(s, "t-20260903-dark-mode", "implement")
    t["plan"] = ["a", "b", "c"]
    t["step"] = 1
    t["last_test_run"] = {"passed": 41, "failed": 2, "after_edit_seq": 3}
    line = state.summary(s)
    assert "t-20260903-dark-mode" in line and "implement" in line and "step 2/3" in line
    assert "41 passed, 2 failed" in line and "\n" not in line
    state.advance(s, "t-20260903-dark-mode", "needs-attention", reason="stop cap hit")
    assert "NEEDS ATTENTION" in state.summary(s) and "stop cap hit" in state.summary(s)


@pytest.mark.parametrize("fixture", ["sessionstart_startup", "sessionstart_resume", "sessionstart_compact"])
def test_summary_hook_emits_sessionstart_additional_context(tmp_path, fixture):
    """Real SessionStart inputs, cwd pointed at a repo with an active task."""
    (tmp_path / ".git").mkdir()
    s = state.empty()
    state.new_task(s, "t-20260903-dark-mode")
    state.save(str(tmp_path), s)
    payload = dict(hook_input(fixture), cwd=str(tmp_path))
    r = run_script("state", ["--summary"], stdin=payload, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "t-20260903-dark-mode" in out["hookSpecificOutput"]["additionalContext"]


def test_summary_hook_outside_a_repo_still_exits_zero_with_valid_json(tmp_path):
    payload = dict(hook_input("sessionstart_startup"), cwd=str(tmp_path))
    r = run_script("state", ["--summary"], stdin=payload, cwd=str(tmp_path))
    assert r.returncode == 0
    assert json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] == "REHORSE: no active task."


def test_cli_new_advance_show(repo):
    r = run_script("state", ["new", "Dark mode toggle", "--date", "20260903"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "t-20260903-dark-mode-toggle"
    r = run_script("state", ["advance", "tests"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    r = run_script("state", ["advance", "verify"], cwd=str(repo))
    assert r.returncode == 1 and "tests" in r.stderr
    r = run_script("state", ["show"], cwd=str(repo))
    assert json.loads(r.stdout)["phase"] == "tests"


def test_active_returns_root_state_and_task_for_hooks(tmp_path):
    (tmp_path / ".git").mkdir()
    root, s, task = state.active(str(tmp_path))
    assert root == os.path.realpath(tmp_path) and s == state.empty() and task is None
    state.new_task(s, "t-1")
    state.save(str(tmp_path), s)
    root, s, task = state.active(str(tmp_path / ".rehorse" / "worktrees" / "t-1"))
    assert root == os.path.realpath(tmp_path) and task["id"] == "t-1"
    state.advance(s, "t-1", "discarded")
    state.save(str(tmp_path), s)
    assert state.active(str(tmp_path))[2] is None  # terminal phase: dormant


def test_active_outside_a_repo_is_dormant(tmp_path):
    assert state.active(str(tmp_path)) == (None, state.empty(), None)
