"""run_eval.py: the parts that need no network and no Claude Code: prompt shape, reading Rehorse's state into a result,
skipping done tasks, grading against a PR ref, and the results table."""
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval"))
import run_eval  # noqa: E402

TASK = {"id": "rich-2942", "repo": "Textualize/rich", "base_sha": "610fd75", "issue_url": "https://github.com/Textualize/rich/issues/2942",
        "issue_title": "[BUG] Style.clear_meta_and_links should reset hash", "issue_body": "The hash of a `Style` depends on \"_meta\".",
        "pr_url": "https://github.com/Textualize/rich/pull/2943", "pr_test_files": ["tests/test_style.py"],
        "test_cmd": ".venv/bin/python -m pytest -q --tb=short", "setup_cmd": "true"}


def test_prompt_is_the_build_command_with_title_and_body():
    assert run_eval.prompt(TASK) == '/rehorse:build "[BUG] Style.clear_meta_and_links should reset hash\n\nThe hash of a `Style` depends on \\"_meta\\"."'


def state(**over):
    t = {"phase": "report", "last_test_run": {"passed": 40, "failed": 0}, "verifier": {"verdict": "concerns", "findings": [{}]},
         "verify_round": 1, "report_path": "rehorse-reports/2026-09-04-x.md", "worktree": ".rehorse/worktrees/t-1", "attention": None}
    t.update(over)
    return {"active_task": "t-1", "tasks": {"t-1": t}}


def test_rehorse_outcome_is_read_from_state_not_the_report_text():
    assert run_eval.outcome(state()) == {"merged_green": True, "verdict": "concerns", "rounds": 1, "phase": "report",
                                         "report_path": "rehorse-reports/2026-09-04-x.md", "worktree": ".rehorse/worktrees/t-1", "attention": None,
                                         "baseline": None, "last_test_run": {"passed": 40, "failed": 0}}
    assert run_eval.outcome(state(phase="implement"))["merged_green"] is False
    assert run_eval.outcome(state(last_test_run={"passed": 40, "failed": 1}))["merged_green"] is False
    assert run_eval.outcome(state(verifier=None))["verdict"] is None
    att = run_eval.outcome(state(phase="needs-attention", attention={"reason": "gave up", "prior_phase": "implement"}))
    assert att["merged_green"] is False and att["attention"] == "gave up"
    assert run_eval.outcome(None) == {"merged_green": False, "verdict": None, "rounds": 0, "phase": None, "report_path": None, "worktree": None,
                                      "attention": None, "baseline": None, "last_test_run": None}


def test_tasks_with_a_result_file_are_skipped_unless_rerun(tmp_path):
    (tmp_path / "rich-2942.json").write_text("{}")
    other = dict(TASK, id="rich-3881")
    assert [t["id"] for t in run_eval.pending([TASK, other], str(tmp_path), rerun=False)] == ["rich-3881"]
    assert [t["id"] for t in run_eval.pending([TASK, other], str(tmp_path), rerun=True)] == ["rich-2942", "rich-3881"]
    assert [t["id"] for t in run_eval.pending([TASK, other], str(tmp_path), rerun=False, only=["rich-2942"])] == []


def test_results_table_and_one_line_summary():
    rows = [{"id": "rich-2942", "merged_green": True, "upstream_pass": True, "verdict": "pass", "rounds": 1, "wall_s": 601.4, "turns": 23,
             "report": "results/rich-2942.report.md"},
            {"id": "rich-3881", "merged_green": True, "upstream_pass": False, "verdict": "concerns", "rounds": 2, "wall_s": 88, "turns": 9,
             "report": "results/rich-3881.report.md"},
            {"id": "rich-3479", "merged_green": False, "upstream_pass": False, "verdict": None, "rounds": 0, "wall_s": 12, "turns": None,
             "report": None, "error": "setup_cmd failed (exit 1)"}]
    md = run_eval.render(rows)
    assert "| task | merged-green | upstream-tests-pass | verifier | rounds | wall | turns | report |" in md
    assert "| rich-2942 | yes | **yes** | pass | 1 | 10m01s | 23 | [report](results/rich-2942.report.md) |" in md
    assert "| rich-3881 | yes | no | concerns | 2 | 1m28s | 9 | [report](results/rich-3881.report.md) |" in md
    assert "| rich-3479 | no | no | – | 0 | 12s | – | setup_cmd failed (exit 1) |" in md
    assert md.rstrip().endswith("1 of 3 tasks pass the upstream PR's tests; 2 self-reported green; 1 errored.")


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def origin_and_clone(tmp_path):
    """A bare 'origin' with refs/pull/7/head carrying a test that needs sub(); a clone at base with a worktree holding the fix."""
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-q", "-b", "main")
    git(src, "config", "user.email", "t@example.com")
    git(src, "config", "user.name", "t")
    (src / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (src / "tests").mkdir()
    (src / "tests" / "test_app.py").write_text("from app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "base")
    base = git(src, "rev-parse", "HEAD")
    git(src, "checkout", "-q", "-b", "pr")
    (src / "app.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    (src / "tests" / "test_app.py").write_text("from app import add, sub\n\n\ndef test_add():\n    assert add(1, 2) == 3\n\n\ndef test_sub():\n    assert sub(3, 1) == 2\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "fix")
    git(src, "update-ref", "refs/pull/7/head", "HEAD")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(src), str(clone)], check=True)
    git(clone, "checkout", "-q", "-b", "eval", base)
    wt = clone / ".rehorse" / "worktrees" / "t-1"
    git(clone, "worktree", "add", "-q", str(wt), "-b", "rehorse/t-1", base)
    return clone, wt


def test_grade_checks_out_the_prs_test_files_into_the_worktree_and_runs_them(origin_and_clone):
    clone, wt = origin_and_clone
    task = dict(TASK, pr_url="https://example.invalid/o/r/pull/7", pr_test_files=["tests/test_app.py"],
                test_cmd="%s -m pytest -q --tb=short" % sys.executable)
    before = run_eval.grade(task, str(clone), str(wt))  # the worktree still has the base: the PR's test must fail
    assert before["upstream_pass"] is False and before["counts"] == {"passed": 0, "failed": 1}  # import of sub() fails: a collection error
    assert "def test_sub" in (wt / "tests" / "test_app.py").read_text()
    (wt / "app.py").write_text("def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n")
    after = run_eval.grade(task, str(clone), str(wt))
    assert after["upstream_pass"] is True and after["counts"] == {"passed": 2, "failed": 0}
    assert after["command"].endswith("tests/test_app.py") and after["where"] == str(wt)


def test_grade_without_a_worktree_runs_in_the_clone_and_says_so(origin_and_clone):
    clone, _ = origin_and_clone
    task = dict(TASK, pr_url="https://example.invalid/o/r/pull/7", pr_test_files=["tests/test_app.py"],
                test_cmd="%s -m pytest -q --tb=short" % sys.executable)
    r = run_eval.grade(task, str(clone), None)
    assert r["upstream_pass"] is False and r["where"] == str(clone)


def test_grade_records_an_unparseable_run_as_not_passing(origin_and_clone):
    clone, wt = origin_and_clone
    task = dict(TASK, pr_url="https://example.invalid/o/r/pull/7", pr_test_files=["tests/test_app.py"], test_cmd="false")
    r = run_eval.grade(task, str(clone), str(wt))
    assert r["upstream_pass"] is False and r["counts"] is None
