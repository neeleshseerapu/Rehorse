"""guard_stop.py (Stop): during implement, block the turn until tests ran after the last edit; cap at 8 blocks."""
from conftest import hook_input, hook_out, run_script, task_in, task_state


def stop(repo, fixture="stop_first"):
    payload = dict(hook_input(fixture), cwd=str(repo))
    return hook_out(run_script("guard_stop", stdin=payload, cwd=str(repo)))


def test_dormant_without_an_active_task(repo, tmp_path):
    assert stop(repo) is None


def test_blocks_when_edits_are_newer_than_the_last_test_run(repo):
    wt = task_in(repo, "implement", edit_seq=2, last_test_run={"passed": 2, "failed": 0, "after_edit_seq": 1})
    out = stop(repo)
    assert out["decision"] == "block"
    assert "cd %s && python3 -m pytest -q" % wt in out["reason"]
    assert out["reason"].startswith("REHORSE: ")
    assert task_state(repo)["stop_blocks"] == 1


def test_blocks_when_no_run_was_ever_recorded_after_an_edit(repo):
    task_in(repo, "implement", edit_seq=1)
    assert stop(repo)["decision"] == "block"


def test_allows_and_resets_counter_once_tests_ran_after_the_last_edit(repo):
    task_in(repo, "implement", edit_seq=2, stop_blocks=3, last_test_run={"passed": 2, "failed": 0, "after_edit_seq": 2})
    assert stop(repo, "stop_after_block") is None
    assert task_state(repo)["stop_blocks"] == 0


def test_allows_with_no_edits_at_all(repo):
    task_in(repo, "implement")
    assert stop(repo) is None


def test_only_the_implement_phase_is_guarded(repo):
    for phase in ["spec", "tests", "verify", "report"]:
        task_in(repo, phase, edit_seq=5)
        assert stop(repo) is None, phase
        import worktree
        worktree.remove(str(repo), "t-1")


def test_eighth_block_moves_the_task_to_needs_attention_and_allows_the_stop(repo):
    task_in(repo, "implement", edit_seq=1, stop_blocks=7)
    out = stop(repo, "stop_after_block")
    assert (out or {}).get("decision") != "block"
    assert "needs-attention" in out["systemMessage"]
    t = task_state(repo)
    assert t["phase"] == "needs-attention" and t["attention"]["prior_phase"] == "implement"
    assert "8" in t["attention"]["reason"]
