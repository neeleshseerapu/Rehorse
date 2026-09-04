"""report.py: renders rehorse-reports/<date>-<slug>.md from state and git, advances verify -> report, and commits the
evidence (report + PROGRESS.md snapshot) on the rehearsal branch so /rehorse:merge carries it into the real branch."""
import os

from conftest import commit_in, git, run_script, task_in, task_state

import state


def verified_task(repo, **fields):
    wt = task_in(repo, "tests", baseline={"passed": 1, "failed": 0})
    tests_sha = commit_in(wt, "tests/test_sub.py", "from app import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n", "tests: sub")
    s = state.load(str(repo))
    t = s["tasks"]["t-1"]
    t.update(red_check={"passed": 1, "failed": 1}, tests_sha=tests_sha, edit_seq=1,
             last_test_run={"passed": 2, "failed": 0, "after_edit_seq": 1, "output": "2 passed in 0.01s"},
             plan=[{"title": "Add sub()", "done": True, "summary": "Added sub() to app.py.\nTests: 2 passed.", "commit": "abc"}], step=1)
    t.update(fields)
    state.advance(s, "t-1", "implement")
    state.advance(s, "t-1", "verify")
    state.save(str(repo), s)
    commit_in(wt, "app.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n", "step 1: Add sub()")
    return wt


def render(repo):
    r = run_script("report", cwd=str(repo))
    assert r.returncode == 0, r.stderr
    path = r.stdout.strip()
    assert os.path.exists(path)
    return open(path).read()


def test_report_is_one_screen_in_the_spec_order_and_advances_to_report(repo):
    wt = verified_task(repo)
    text = render(repo)
    t = task_state(repo)
    assert t["phase"] == "report" and t["report_path"].startswith("rehorse-reports/") and t["report_path"].endswith("-1.md")
    order = ["GREEN", "baseline", "1 | 0", "red", "1 | 1", "green", "2 | 0", "app.py", "Verifier", "not run", "drift", "none",
             "/rehorse:merge t-1", "/rehorse:discard t-1"]
    positions = [text.find(k) for k in order]
    assert all(p >= 0 for p in positions), dict(zip(order, positions))
    assert positions == sorted(positions), order
    assert text.count("\n") < 60
    assert "Add sub()" in text and "Added sub() to app.py." in text


def test_report_and_progress_snapshot_are_committed_on_the_rehearsal_branch(repo):
    wt = verified_task(repo)
    render(repo)
    names = git(wt, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(names) == sorted(["rehorse-reports/PROGRESS.md", "rehorse-reports/" + os.path.basename(task_state(repo)["report_path"])])
    assert git(repo, "status", "--porcelain", "app.py").strip() == ""  # main checkout untouched
    assert "phase: report" in open(os.path.join(wt, "rehorse-reports", "PROGRESS.md")).read()


def test_report_flags_test_file_drift_after_the_tests_phase(repo):
    wt = verified_task(repo)
    commit_in(wt, "tests/test_sub.py", "def test_sub():\n    assert True\n", "weaken the test")
    text = render(repo)
    assert "DRIFT" in text and "tests/test_sub.py" in text


def test_red_last_run_renders_a_red_banner(repo):
    verified_task(repo, last_test_run={"passed": 1, "failed": 1, "after_edit_seq": 1, "output": "1 failed, 1 passed in 0.01s"})
    text = render(repo)
    assert "RED" in text.splitlines()[2] or "RED" in text[:300]


def test_needs_attention_renders_the_reason_as_the_banner_without_changing_phase(repo):
    verified_task(repo)
    s = state.load(str(repo))
    state.advance(s, "t-1", "needs-attention", reason="8 consecutive Stop blocks")
    state.save(str(repo), s)
    text = render(repo)
    assert "NEEDS ATTENTION" in text[:300] and "8 consecutive Stop blocks" in text
    assert task_state(repo)["phase"] == "needs-attention"


def test_report_refuses_before_verify(repo):
    task_in(repo, "implement")
    r = run_script("report", cwd=str(repo))
    assert r.returncode != 0 and "verify" in r.stderr


def test_report_name_uses_the_task_date_and_slug_with_rehearsal_suffix(repo):
    import report
    assert report.report_name({"id": "t-20260903-add-dark-mode-toggle", "created": "2026-09-04T10:00:00"}) == "2026-09-03-add-dark-mode-toggle.md"
    assert report.report_name({"id": "t-20260903-x-r2", "created": "2026-09-04T10:00:00"}) == "2026-09-03-x-r2.md"
    assert report.report_name({"id": "t-1", "created": "2026-09-04T10:00:00"}) == "2026-09-04-1.md"


def test_report_names_the_dependency_dirs_linked_into_the_worktree(repo):
    verified_task(repo, linked_deps=[".venv", "node_modules"])
    text = render(repo)
    assert "Worktree setup: linked .venv, node_modules" in text
    import state
    s = state.load(str(repo))
    s["tasks"]["t-1"]["linked_deps"] = []
    s["tasks"]["t-1"]["phase"] = "report"
    state.save(str(repo), s)
    assert "Worktree setup: nothing linked" in render(repo)


def test_report_warns_about_weak_tests_only_when_there_are_some(repo):
    verified_task(repo, weak_tests=1)
    assert "1 new test(s) passed before implementation and may not test anything." in render(repo)
    import state
    s = state.load(str(repo))
    s["tasks"]["t-1"]["weak_tests"] = 0
    state.save(str(repo), s)
    assert "passed before implementation" not in render(repo)
