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
             "report": "results/rich-2942.report.md", "phase": "report", "rehorse_commit": "abc1234"},
            {"id": "rich-3881", "merged_green": True, "upstream_pass": False, "verdict": "concerns", "rounds": 2, "wall_s": 88, "turns": 9,
             "report": "results/rich-3881.report.md", "phase": "report", "rehorse_commit": "def5678",
             "rehorse_commit_backfilled": True},
            {"id": "rich-3479", "merged_green": False, "upstream_pass": False, "verdict": None, "rounds": 0, "wall_s": 12, "turns": None,
             "report": None, "phase": None, "error": "setup_cmd failed (exit 1)"}]
    md = run_eval.render(rows, {"rich-2942": 1, "rich-3881": 2})
    assert "| task | rehorse | tier | self-green | rehorse-outcome | upstream-tests-pass | verifier | rounds | wall | turns | report |" in md
    assert "| rich-2942 | abc1234 | 1 | yes | green | **yes** | pass | 1 | 10m01s | 23 | [report](results/rich-2942.report.md) |" in md
    assert "| rich-3881 | ~def5678 | 2 | yes | green | no | concerns | 2 | 1m28s | 9 | [report](results/rich-3881.report.md) |" in md
    assert "| rich-3479 | – | – | no | error | no | – | 0 | 12s | – | setup_cmd failed (exit 1) |" in md
    method = md[md.index("## Methodology"):md.index("## Results")]
    for phrase in ("merge commit's first parent", "*merge commit*", "never from\n  the PR head", "replacing\n  Rehorse's edits",
                   "never count toward the grade", "`poetry.lock`", "`attrs`", "Python 3.13"):
        assert phrase in method, phrase
    assert "different Rehorse versions" in method and "`~`" in method, "the table says which version each row measured"
    summary = "1 of 3 tasks pass the upstream PR's tests; 2 self-reported green; 1 errored."
    assert summary in md and md.index(summary) < md.index("| task | rehorse |"), "the headline reads before the table, not after it"
    assert "verify round-trips" in md[md.index(summary):md.index("| task | rehorse |")]


def test_rehorse_outcome_names_the_phase_the_task_stopped_in():
    """green / needs-attention / error, from state's phase. A run stopped anywhere else shows that phase, so a stalled
    task cannot read as a clean stop."""
    assert run_eval.outcome_label({"phase": "report", "merged_green": True}) == "green"
    assert run_eval.outcome_label({"phase": "needs-attention", "merged_green": False}) == "needs-attention"
    assert run_eval.outcome_label({"phase": "report", "merged_green": False, "error": "claude exit 1"}) == "error"
    assert run_eval.outcome_label({"phase": "implement", "merged_green": False}) == "implement"
    assert run_eval.outcome_label({"phase": "report", "merged_green": False}) == "report (not green)"
    assert run_eval.outcome_label({}) == "error"


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


@pytest.fixture(autouse=True)
def pr_head_is_the_fix(monkeypatch):
    """The local origin has no gh-resolvable merge commit; grade from the PR head ref, the documented fallback."""
    monkeypatch.setattr(run_eval, "fix_ref", lambda task: "refs/pull/%s/head" % task["pr_url"].rsplit("/", 1)[1])


def test_fix_ref_is_the_merge_commit_from_gh_and_falls_back_to_the_pr_head(monkeypatch):
    monkeypatch.undo()
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="a" * 40 + "\n", stderr="")
    monkeypatch.setattr(run_eval.subprocess, "run", fake_run)
    assert run_eval.fix_ref(TASK) == "a" * 40
    assert calls[0][:3] == ["gh", "api", "repos/Textualize/rich/pulls/2943"]
    monkeypatch.setattr(run_eval.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "gh")))
    assert run_eval.fix_ref(TASK) == "refs/pull/2943/head"


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
    assert after["command"].endswith("tests/test_app.py") and after["where"] == str(wt) and after["tests_from"] == "refs/pull/7/head"


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


def test_only_top_level_id_json_files_are_rows(tmp_path):
    """An archived copy (rich-1.pre-fix1.json) or a file under archive/ is not a result: it would double a task's row."""
    row = json.dumps({"id": "rich-1", "merged_green": True, "upstream_pass": True, "verdict": "pass", "rounds": 1, "wall_s": 1, "turns": 1,
                      "report": None})
    (tmp_path / "rich-1.json").write_text(row)
    (tmp_path / "rich-1.pre-fix1.json").write_text(row)
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "rich-2.json").write_text(row)
    (tmp_path / "notes.md").write_text("not a result")
    assert [os.path.basename(p) for p in run_eval.result_files(str(tmp_path))] == ["rich-1.json"]


def test_the_rehorse_commit_is_read_from_git_in_the_plugin_directory():
    """Which Rehorse a row measured. The eval loads the plugin from ROOT with --plugin-dir, so the version is that
    directory's HEAD — marked `-dirty` when the working tree it loads is not that commit."""
    head = git(run_eval.ROOT, "rev-parse", "--short", "HEAD")
    dirty = bool(git(run_eval.ROOT, "status", "--porcelain"))
    assert run_eval.rehorse_commit() == (head + "-dirty" if dirty else head)


def test_a_plugin_directory_that_is_not_a_git_repo_records_no_commit(tmp_path):
    assert run_eval.rehorse_commit(str(tmp_path)) is None


def test_a_dirty_plugin_directory_is_marked(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "f").write_text("one\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "one")
    clean = run_eval.rehorse_commit(str(tmp_path))
    assert clean == git(tmp_path, "rev-parse", "--short", "HEAD")
    (tmp_path / "f").write_text("two\n")
    assert run_eval.rehorse_commit(str(tmp_path)) == clean + "-dirty"


def test_tasks_with_no_result_yet_are_counted_under_the_table(tmp_path):
    """The table is the tasks that ran, and it says how many have not: a reader must not read 13 rows as the whole eval."""
    rows = [{"id": "rich-2942", "merged_green": True, "upstream_pass": True, "verdict": "pass", "rounds": 1, "wall_s": 1, "turns": 1,
             "report": None, "phase": "report"}]
    assert "17 of the 30 tasks in `eval/tasks.json` have not run yet" in run_eval.render(rows, remaining=17, total=30)
    assert "have not run yet" not in run_eval.render(rows, remaining=0, total=1)
