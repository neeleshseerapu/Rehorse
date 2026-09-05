"""report.py: renders rehorse-reports/<date>-<slug>.md from state and git, advances verify -> report, and commits the
evidence (report + PROGRESS.md snapshot) on the rehearsal branch so /rehorse:merge carries it into the real branch."""
import os

from conftest import VERDICT, commit_in, git, run_script, task_in, task_state

import state


def verified_task(repo, **fields):
    wt = task_in(repo, "tests", baseline={"passed": 1, "failed": 0})
    tests_sha = commit_in(wt, "tests/test_sub.py", "from app import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2\n", "tests: sub")
    s = state.load(str(repo))
    t = s["tasks"]["t-1"]
    t.update(red_check={"passed": 1, "failed": 1, "new_failed": 1}, tests_sha=tests_sha, edit_seq=1,
             last_test_run={"passed": 2, "failed": 0, "after_edit_seq": 1, "output": "2 passed in 0.01s"},
             plan=[{"title": "Add sub()", "done": True, "summary": "Added sub() to app.py.\nTests: 2 passed.", "commit": "abc"}], step=1,
             verifier=dict(VERDICT), verify_round=1)
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
    order = ["GREEN", "verifier PASS", "baseline", "1 | 0", "red", "1 | 1", "green", "2 | 0", "app.py", "Verifier: PASS", "round 1 of 3",
             "drift", "none: test files unchanged", "/rehorse:merge t-1", "/rehorse:discard t-1"]
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


def test_report_renders_a_build_failed_red_instead_of_counts(repo):
    verified_task(repo, red_check={"passed": 0, "failed": 0}, red_kind="build_failed")
    text = render(repo)
    assert "| red (tests written, no implementation) | build failed (new tests reference symbols that don't exist yet) | |" in text
    assert "| red (tests written, no implementation) | 0 | 0 |" not in text


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


def test_report_guard_line_warns_only_on_unexpected_passes(repo):
    verified_task(repo, weak_tests=1, guards=["tests/test_sub.py::test_add_unchanged"])
    assert "**Warning:** 1 guard(s) expected to pass; 1 unexpected pass(es)" in render(repo)
    import state
    s = state.load(str(repo))
    s["tasks"]["t-1"]["weak_tests"] = 0
    state.save(str(repo), s)
    assert "1 guard(s) expected to pass; 0 unexpected pass(es)" in render(repo) and "Warning:** 1 guard" not in render(repo)
    s["tasks"]["t-1"]["guards"] = []
    state.save(str(repo), s)
    assert "guard(s)" not in render(repo)


def test_report_has_a_try_it_yourself_section_between_changes_and_next(repo):
    wt = verified_task(repo)
    (repo / ".rehorse" / "worktrees" / "t-1" / "Makefile").write_text("run:\n\tpython3 app.py\n")
    text = render(repo)
    i = text.index("## Try it yourself")
    assert text.index("## Changes") < i < text.index("## Next")
    section = text[i:text.index("## Next")]
    assert "cd %s" % wt in section and "python3 -m pytest -q" in section and "make run" in section


def test_try_it_yourself_says_so_when_no_run_command_is_detectable(repo):
    wt = verified_task(repo)
    section = render(repo).split("## Try it yourself")[1].split("## Next")[0]
    assert "cd %s" % wt in section and "no run command detected" in section


def test_summary_is_optional_and_labelled_as_written_by_the_model(repo):
    verified_task(repo)
    assert "## Summary" not in render(repo)
    r = run_script("report", ["--summary", "On merge you get sub(). Verified: tests. Not verified: edge cases."], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    text = open(r.stdout.strip()).read()
    i = text.index("## Summary")
    assert "written by the model" in text[i:i + 200].lower() and "On merge you get sub()." in text
    assert text.index("## Summary") < text.index("## Tests")
    assert task_state(repo)["summary"].startswith("On merge")


# ---- verifier verdict, findings, coverage -----------------------------------------------------------------------------

FINDING = {"severity": "high", "file": "app.py", "line": 5, "description": "strings are concatenated, not rejected"}
COVERAGE = [{"criterion": "1. sub(3, 1) == 2", "evidence": "test", "ref": "tests/test_sub.py::test_sub"},
            {"criterion": "2. sub raises TypeError on strings", "evidence": "none", "ref": ""},
            {"criterion": "3. sub is exported", "evidence": "build_only", "ref": "app.py"}]


def test_concerns_verdict_replaces_unverified_in_the_banner_and_renders_findings_and_coverage_after_changes(repo):
    verified_task(repo, verifier=dict(VERDICT, verdict="concerns", findings=[dict(FINDING, severity="medium")], coverage=COVERAGE,
                                      tests_added=["tests/test_rehorse_verify_t-1.py::test_strings"], tests={"passed": 3, "failed": 0}))
    text = render(repo)
    assert "unverified" not in text and "GREEN: 2 passed, 0 failed · verifier CONCERNS (1 finding)" in text
    i = text.index("## Verifier: CONCERNS (round 1 of 3)")
    assert text.index("## Changes") < i < text.index("## Test-file drift")
    section = text[i:text.index("## Test-file drift")]
    assert "[medium] app.py:5 strings are concatenated, not rejected" in section
    assert "tests/test_rehorse_verify_t-1.py::test_strings" in section and "3 passed, 0 failed" in section
    assert "| 2. sub raises TypeError on strings | none |" in section and "| 1. sub(3, 1) == 2 | test | tests/test_sub.py::test_sub |" in section


def test_fail_verdict_leads_the_banner_but_the_merge_command_is_still_offered(repo):
    verified_task(repo, verifier=dict(VERDICT, verdict="fail", findings=[FINDING, dict(FINDING, line=9)], tests={"passed": 3, "failed": 1}))
    text = render(repo)
    first = [l for l in text.splitlines() if l.startswith("## ")][0]
    assert first.startswith("## FAIL: verifier found 2 issue") and "2 passed, 0 failed" in first
    assert "/rehorse:merge t-1" in text and task_state(repo)["phase"] == "report"


def test_try_it_yourself_points_at_criteria_with_no_test_evidence(repo):
    verified_task(repo, verifier=dict(VERDICT, coverage=COVERAGE))
    section = render(repo).split("## Try it yourself")[1].split("## Next")[0]
    assert "2. sub raises TypeError on strings (no test)" in section and "3. sub is exported (only built" in section
    assert "1. sub(3, 1)" not in section
    import state
    s = state.load(str(repo))
    s["tasks"]["t-1"]["verifier"]["coverage"] = COVERAGE[:1]
    state.save(str(repo), s)
    assert "eyeball" not in render(repo).split("## Try it yourself")[1].split("## Next")[0].lower()


def test_many_findings_go_to_the_verifier_folder_and_the_report_links_it(repo):
    findings = [dict(FINDING, line=n, description="finding %d" % n) for n in range(1, 9)]
    wt = verified_task(repo, verifier=dict(VERDICT, verdict="concerns", findings=findings, coverage=COVERAGE))
    text = render(repo)
    name = os.path.basename(task_state(repo)["report_path"])
    assert "finding 5" in text and "finding 6" not in text and "3 more in rehorse-reports/verifier/%s" % name in text
    full = open(os.path.join(str(repo), "rehorse-reports", "verifier", name)).read()
    assert all("finding %d" % n in full for n in range(1, 9)) and "| 2. sub raises TypeError on strings | none |" in full
    names = git(wt, "show", "--name-only", "--format=", "HEAD").split()
    assert "rehorse-reports/verifier/" + name in names


def test_verifier_test_file_is_not_test_drift(repo):
    wt = verified_task(repo)
    commit_in(wt, "tests/test_rehorse_verify_t-1.py", "def test_strings():\n    assert 1\n", "verify: round 1 tests for t-1")
    text = render(repo)
    assert "DRIFT" not in text and "drift" in text.lower()


def test_later_round_shows_the_count_and_what_earlier_rounds_found(repo):
    verified_task(repo, verify_round=2, verifier=dict(VERDICT, round=2),
                  verify_history=[dict(VERDICT, verdict="fail", findings=[FINDING], tests={"passed": 3, "failed": 1})])
    text = render(repo)
    assert "## Verifier: PASS (round 2 of 3)" in text
    assert "Round 1: FAIL" in text and "strings are concatenated, not rejected" in text


def test_report_without_a_verdict_in_needs_attention_still_says_unverified(repo):
    verified_task(repo, verifier=None)
    s = state.load(str(repo))
    state.advance(s, "t-1", "needs-attention", reason="8 consecutive Stop blocks")
    state.save(str(repo), s)
    text = render(repo)
    assert "NEEDS ATTENTION" in text[:300] and "## Verifier: not run" in text


def test_many_tests_added_are_counted_not_listed(repo):
    ids = ["tests/test_rehorse_verify_t-1.py::test_%d" % n for n in range(12)]
    verified_task(repo, verifier=dict(VERDICT, tests_added=ids))
    text = render(repo)
    assert "Tests added: 12 in tests/test_rehorse_verify_t-1.py" in text and text.count("::test_") == 0
    import state
    s = state.load(str(repo))
    s["tasks"]["t-1"]["verifier"]["tests_added"] = ids[:2]
    state.save(str(repo), s)
    assert "Tests added: tests/test_rehorse_verify_t-1.py::test_0, tests/test_rehorse_verify_t-1.py::test_1" in render(repo)


def test_a_step_with_no_edits_renders_as_already_satisfied_not_as_work(repo):
    verified_task(repo, plan=[{"title": "Add sub()", "done": True, "summary": "Added sub().\nGreen.", "commit": "abc"},
                              {"title": "Make the verifier's tests pass", "done": True, "summary": "No edits: nothing to do.\nGreen.",
                               "commit": "abc", "satisfied_by": 1}], step=2)
    text = render(repo)
    assert "- [x] 2. Make the verifier's tests pass — already satisfied by step 1 (no edits)" in text
    assert "No edits: nothing to do." not in text


def test_report_lists_preexisting_failures_separately_and_ignores_them(repo):
    verified_task(repo, baseline={"passed": 1, "failed": 2, "failing": ["tests/test_a.py::test_x", "tests/test_a.py::test_y"]},
                  red_check={"passed": 1, "failed": 3, "new_failed": 1, "new_failing": ["tests/test_new.py::test_z"], "preexisting": 2})
    text = render(repo)
    assert "2 failing at baseline (ignored): tests/test_a.py::test_x, tests/test_a.py::test_y" in text
    assert "1 new failing test(s) at red: tests/test_new.py::test_z" in text


def test_report_warns_when_red_was_judged_by_counts(repo):
    verified_task(repo, red_check={"passed": 1, "failed": 1, "new_failed": 1, "ids_unavailable": True})
    assert "no test ids in the runner output; red was judged by counts" in render(repo)


CHANGE = [{"test": "tests/test_sub.py::test_sub", "why": "criterion 2 says the old result was wrong"}]


def test_declared_existing_test_changes_are_rendered_with_their_reasons(repo):
    verified_task(repo, expected_test_changes=CHANGE)
    text = render(repo)
    assert "Existing tests changed: 1" in text
    assert "tests/test_sub.py::test_sub" in text and "criterion 2 says the old result was wrong" in text


def test_no_declared_changes_says_none(repo):
    verified_task(repo)
    assert "Existing tests changed: none" in render(repo)


def test_a_declared_change_is_not_drift_but_an_undeclared_one_still_is(repo):
    """Drift is the implementer weakening the tests; a change the tests phase declared and justified is expected."""
    wt = verified_task(repo, expected_test_changes=CHANGE)
    commit_in(wt, "tests/test_sub.py", "from app import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2  # tweaked\n", "declared change")
    text = render(repo)
    assert "DRIFT" not in text and "expected" in text.lower()
    commit_in(wt, "tests/test_sub.py", "from app import sub\n\ndef test_sub():\n    assert sub(3, 1) == 2  # tweaked\n\n\n"
              "def test_other():\n    assert 0\n", "undeclared change")
    commit_in(wt, "tests/test_sub.py", "from app import sub\n\ndef test_other():\n    assert 0\n", "drop test_sub too")
    assert "DRIFT" in render(repo)
