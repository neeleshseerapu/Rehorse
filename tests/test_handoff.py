"""handoff.py (PreCompact): snapshot phase, step, last test result and next action to .rehorse/handoff.json;
refresh PROGRESS.md. Injection itself happens on SessionStart(compact) via state.py --summary."""
import json

from conftest import hook_input, hook_out, run_script, task_in


def test_dormant_without_an_active_task(repo):
    payload = dict(hook_input("precompact_manual"), cwd=str(repo))
    assert hook_out(run_script("handoff", stdin=payload, cwd=str(repo))) is None
    assert not (repo / ".rehorse" / "handoff.json").exists()


def test_writes_handoff_and_progress_before_compaction(repo):
    task_in(repo, "implement", plan=[{"title": "A", "done": True, "summary": "did A", "commit": "c"},
                                     {"title": "B", "done": False, "summary": None, "commit": None}], step=1,
            last_test_run={"passed": 2, "failed": 0, "after_edit_seq": 1})
    payload = dict(hook_input("precompact_manual"), cwd=str(repo))
    assert hook_out(run_script("handoff", stdin=payload, cwd=str(repo))) is None  # no output: PreCompact cannot inject
    h = json.load(open(repo / ".rehorse" / "handoff.json"))
    assert h["task"] == "t-1" and h["phase"] == "implement" and h["step"] == 1 and h["trigger"] == "manual"
    assert h["last_test_run"]["passed"] == 2 and "B" in h["next_action"] and h["at"]
    assert "- [ ] 2. B" in (repo / "rehorse-reports" / "PROGRESS.md").read_text()
