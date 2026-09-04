"""merge.py / discard.py: the only code paths that touch the user's branch, and only with a user-minted grant."""
import json
import os

from conftest import commit_in, git, run_script, task_in, task_state

import grant


def ready(repo, phase="report"):
    wt = task_in(repo, phase)
    commit_in(wt, "app.py", "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n", "step 1: sub")
    return wt


def test_merge_refuses_without_a_grant_and_changes_nothing(repo, home):
    wt = ready(repo)
    r = run_script("merge", ["t-1"], cwd=str(repo))
    assert r.returncode != 0 and "/rehorse:merge t-1" in r.stderr
    assert "sub" not in (repo / "app.py").read_text() and os.path.isdir(wt)
    assert task_state(repo)["phase"] == "report"


def test_merge_fast_forwards_removes_the_worktree_and_consumes_the_grant(repo, home):
    wt = ready(repo)
    head = git(wt, "rev-parse", "HEAD").strip()
    grant.mint("merge", "t-1", "s")
    r = run_script("merge", ["t-1"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["merged"] == "t-1" and out["into"] == "main" and out["sha"] == head
    assert git(repo, "rev-parse", "HEAD").strip() == head and "sub" in (repo / "app.py").read_text()
    assert not os.path.exists(wt) and "rehorse/t-1" not in git(repo, "branch", "--list", "rehorse/*")
    t = task_state(repo)
    assert t["phase"] == "merged" and json.load(open(repo / ".rehorse" / "state.json"))["active_task"] is None
    assert not grant.present("t-1")
    assert "merged" in (repo / "rehorse-reports" / "PROGRESS.md").read_text()


def test_merge_falls_back_to_a_merge_commit_when_main_moved_on(repo, home):
    wt = ready(repo)
    (repo / "README.md").write_text("hi\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "docs on main")
    grant.mint("merge", "t-1", "s")
    r = run_script("merge", ["t-1"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    assert "sub" in (repo / "app.py").read_text() and (repo / "README.md").exists()
    assert len(git(repo, "log", "--merges", "--oneline").splitlines()) == 1


def test_conflicting_merge_is_aborted_and_the_rehearsal_is_kept(repo, home):
    wt = ready(repo)
    (repo / "app.py").write_text("def add(a, b):\n    return b + a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "conflicting change on main")
    main_head = git(repo, "rev-parse", "HEAD").strip()
    grant.mint("merge", "t-1", "s")
    r = run_script("merge", ["t-1"], cwd=str(repo))
    assert r.returncode != 0 and "conflict" in r.stderr.lower()
    assert git(repo, "rev-parse", "HEAD").strip() == main_head and not (repo / ".git" / "MERGE_HEAD").exists()
    assert "b + a" in (repo / "app.py").read_text() and os.path.isdir(wt)
    assert task_state(repo)["phase"] == "report" and not grant.present("t-1")


def test_merge_requires_the_report_phase(repo, home):
    ready(repo, "implement")
    grant.mint("merge", "t-1", "s")
    r = run_script("merge", ["t-1"], cwd=str(repo))
    assert r.returncode != 0 and "report" in r.stderr and task_state(repo)["phase"] == "implement"


def test_discard_removes_the_rehearsal_from_any_phase_only_with_a_grant(repo, home):
    wt = ready(repo, "implement")
    assert run_script("discard", ["t-1"], cwd=str(repo)).returncode != 0
    assert os.path.isdir(wt)
    grant.mint("discard", "t-1", "s")
    r = run_script("discard", ["t-1"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["discarded"] == "t-1"
    assert not os.path.exists(wt) and "rehorse/t-1" not in git(repo, "branch", "--list", "rehorse/*")
    assert task_state(repo)["phase"] == "discarded" and "sub" not in (repo / "app.py").read_text()
    assert not grant.present("t-1")


def test_merge_succeeds_when_report_and_progress_are_still_untracked_in_the_main_checkout(repo, home):
    """report.py leaves rehorse-reports/ untracked in the main checkout while committing copies on the branch; git refuses to
    overwrite untracked files during a merge, so merge.py must clear those copies first (PROGRESS.md is regenerated after)."""
    wt = ready(repo, "verify")
    assert run_script("report", cwd=str(repo)).returncode == 0
    assert git(repo, "status", "--porcelain", "rehorse-reports").startswith("??")
    grant.mint("merge", "t-1", "s")
    r = run_script("merge", ["t-1"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    assert git(repo, "ls-files", "rehorse-reports").split() == sorted(["rehorse-reports/PROGRESS.md", task_state(repo)["report_path"]])
    assert "merged" in (repo / "rehorse-reports" / "PROGRESS.md").read_text()
    assert "sub" in (repo / "app.py").read_text()


def test_id_defaults_to_the_active_task(repo, home):
    ready(repo)
    grant.mint("merge", "t-1", "s")
    assert run_script("merge", cwd=str(repo)).returncode == 0
