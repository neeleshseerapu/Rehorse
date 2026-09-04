"""on_bash_done.py (PostToolUse + PostToolUseFailure Bash): record real test runs against the current edit_seq."""
import pytest
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


# ---- weak-test flag: new tests that already pass before implementation ----------------------------------------

def test_red_check_with_no_weak_tests_records_zero(repo):
    wt = task_in(repo, "tests", baseline={"passed": 2, "failed": 0})
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt)  # real fixture: 2 passed, 1 failed -> 1 added, 0 weak
    assert "WARNING" not in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert t["red_check"] == {"passed": 2, "failed": 1} and t["weak_tests"] == 0


def test_red_check_with_one_weak_test_records_it_and_warns_but_still_counts_as_red(repo):
    wt = task_in(repo, "tests", baseline={"passed": 2, "failed": 0})
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 1\n\n1 failed, 3 passed in 0.01s")
    assert "1 new test(s) passed before implementation" in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert t["red_check"] == {"passed": 3, "failed": 1} and t["weak_tests"] == 1 and t["phase"] == "tests"


def test_weak_tests_never_goes_negative_or_above_the_number_added(repo):
    wt = task_in(repo, "tests", baseline={"passed": 2, "failed": 0})
    done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 2\n\n1 error in 0.01s")  # collection error
    assert task_state(repo)["weak_tests"] == 0
    done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 1\n\n1 failed, 4 passed in 0.01s")
    assert task_state(repo)["weak_tests"] == 2


# ---- red by compile failure (the Milo run): fewer tests than baseline, or a build error in the output ------------

def fixture_output(name):
    import os
    return open(os.path.join(os.path.dirname(__file__), "fixtures", "runner_output", name)).read()


def test_red_run_with_fewer_tests_than_baseline_is_a_build_failure_and_skips_weak_tests(repo):
    wt = task_in(repo, "tests", baseline={"passed": 2, "failed": 0})
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 2\n\n1 error in 0.01s")
    assert "build failed" in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert t["red_kind"] == "build_failed" and t["red_check"] == {"passed": 0, "failed": 1} and t["weak_tests"] == 0


@pytest.mark.parametrize("name,cmd", [("swift_build_failed.txt", "swift test"), ("cargo_build_failed.txt", "cargo test")])
def test_red_run_whose_output_is_a_compiler_error_is_recorded_as_build_failed(repo, name, cmd):
    wt = task_in(repo, "tests", test_cmd=cmd, baseline={"passed": 2, "failed": 0}, edit_seq=1)
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, command="cd %s && %s" % (wt, cmd),
               error="Exit code 1\n" + fixture_output(name))
    assert "build failed" in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert t["red_kind"] == "build_failed" and t["red_check"] == {"passed": 0, "failed": 0} and t["weak_tests"] == 0
    assert t["last_test_run"]["after_edit_seq"] == 1  # the attempt counts as a run: the Stop guard must not loop on it


def test_ordinary_red_run_has_red_kind_tests(repo):
    wt = task_in(repo, "tests", baseline={"passed": 2, "failed": 0})
    done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt)
    assert task_state(repo)["red_kind"] == "tests"


def test_swift_red_run_with_failing_tests_is_an_ordinary_red_not_a_build_failure(repo):
    wt = task_in(repo, "tests", test_cmd="swift test", baseline={"passed": 2, "failed": 0})
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, command="cd %s && swift test" % wt,
               error="Exit code 1\n" + fixture_output("swift_tests_red.txt"))
    assert "2 passed, 1 failed" in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert t["red_kind"] == "tests" and t["red_check"] == {"passed": 2, "failed": 1} and t["weak_tests"] == 0


def test_verify_phase_records_the_verifiers_run_separately(repo):
    wt = task_in(repo, "verify", edit_seq=3)
    context(done(repo, cwd=wt))
    t = task_state(repo)
    assert t["verify_run"] == {"passed": 2, "failed": 0} and t["last_test_run"]["after_edit_seq"] == 3
    assert t["baseline"] is None and t["red_check"] == {"passed": 1, "failed": 1}
