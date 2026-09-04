"""on_bash_done.py (PostToolUse + PostToolUseFailure Bash): record real test runs against the current edit_seq."""
from conftest import hook_input, hook_out, run_script, task_in, task_state


def done(repo, fixture="posttooluse_bash_pytest_pass", cwd=None, command=None, stdout=None, error=None):
    payload = dict(hook_input(fixture), cwd=cwd or str(repo))
    if command is not None:
        payload["tool_input"] = dict(payload["tool_input"], command=command)
    if stdout is not None:
        payload["tool_response"] = dict(payload.get("tool_response") or {}, stdout=stdout, stderr="")
    if error is not None:
        payload["error"] = error
    return hook_out(run_script("on_bash_done", stdin=payload, cwd=cwd or str(repo)))


def context(out, event="PostToolUse"):
    h = (out or {}).get("hookSpecificOutput") or {}
    assert h.get("hookEventName") == event, out
    assert h["additionalContext"].startswith("REHORSE: ")
    return h["additionalContext"]


def test_dormant_without_an_active_task(repo):
    assert done(repo) is None


def test_passing_run_from_real_fixture_is_recorded_with_edit_seq(repo):
    wt = task_in(repo, "implement", edit_seq=3)
    out = done(repo, cwd=wt)  # fixture command: <venv>/python -m pytest -q, run inside the worktree
    assert "2 passed, 0 failed" in context(out)
    run = task_state(repo)["last_test_run"]
    assert (run["passed"], run["failed"], run["after_edit_seq"]) == (2, 0, 3)
    assert "pytest" in run["command"] and run["at"]


def test_failing_run_arrives_as_posttoolusefailure_and_is_recorded(repo):
    wt = task_in(repo, "implement", edit_seq=1)
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt)
    assert "2 passed, 1 failed" in context(out, "PostToolUseFailure")
    run = task_state(repo)["last_test_run"]
    assert (run["passed"], run["failed"], run["after_edit_seq"]) == (2, 1, 1)


def test_vitest_failure_with_leading_cd_into_the_worktree(repo):
    wt = task_in(repo, "implement", test_cmd="npx vitest run")
    out = done(repo, "posttoolusefailure_bash_vitest_fail", cwd=str(repo), command="cd %s && npx vitest run" % wt)
    assert "1 passed, 1 failed" in context(out, "PostToolUseFailure")


def test_non_test_commands_are_ignored(repo):
    wt = task_in(repo, "implement")
    assert done(repo, cwd=wt, command="git status", stdout="On branch rehorse/t-1") is None
    assert task_state(repo)["last_test_run"] is None


def test_collect_only_version_and_grep_are_not_test_runs(repo):
    wt = task_in(repo, "implement")
    assert done(repo, cwd=wt, command="python3 -m pytest --collect-only -q", stdout="tests/test_app.py::test_add\n\n1 test collected in 0.01s") is None
    assert done(repo, cwd=wt, command="python3 -m pytest --version", stdout="pytest 9.1.1") is None
    assert done(repo, cwd=wt, command="grep -rn pytest .", stdout="./pyproject.toml:3:[tool.pytest.ini_options]") is None
    assert done(repo, cwd=wt, command="python3 -m pytest -q 2>&1 | grep -c passed", stdout="1") is None
    assert task_state(repo)["last_test_run"] is None


def test_run_outside_the_worktree_is_ignored_with_a_hint(repo):
    wt = task_in(repo, "implement")
    out = done(repo, cwd=str(repo))  # ran against the main checkout, not the rehearsal
    assert "cd %s && python3 -m pytest -q" % wt in context(out)
    assert task_state(repo)["last_test_run"] is None


def test_spec_phase_records_the_baseline(repo):
    wt = task_in(repo, "spec")
    done(repo, cwd=wt)
    t = task_state(repo)
    assert t["baseline"] == {"passed": 2, "failed": 0} and t["phase"] == "spec"


def test_zero_test_baseline_sends_the_task_to_needs_attention(repo):
    wt = task_in(repo, "spec")
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 5\n\nno tests ran in 0.00s")
    assert "needs-attention" in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert t["baseline"] == {"passed": 0, "failed": 0}
    assert t["phase"] == "needs-attention" and t["attention"]["prior_phase"] == "spec"
    assert "0 tests" in t["attention"]["reason"]


def test_tests_phase_records_red_check(repo):
    wt = task_in(repo, "tests", edit_seq=2)
    done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt)
    t = task_state(repo)
    assert t["red_check"] == {"passed": 2, "failed": 1}
    assert t["last_test_run"]["after_edit_seq"] == 2 and t["baseline"] is None


def test_zero_test_run_in_implement_is_recorded_but_changes_no_phase(repo):
    wt = task_in(repo, "implement", edit_seq=1)
    done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 5\n\nno tests ran in 0.00s")
    t = task_state(repo)
    assert t["last_test_run"]["passed"] == 0 and t["phase"] == "implement"
