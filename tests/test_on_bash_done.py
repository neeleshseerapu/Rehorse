"""on_bash_done.py (PostToolUse + PostToolUseFailure Bash): record real test runs against the current edit_seq."""
import os
import pathlib
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


def pf(d):
    """passed/failed only: the id fields are asserted by their own tests."""
    return {k: d[k] for k in ("passed", "failed")}


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
    assert pf(t["baseline"]) == {"passed": 2, "failed": 0} and t["phase"] == "spec"


def test_zero_test_baseline_sends_the_task_to_needs_attention(repo):
    wt = task_in(repo, "spec")
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 5\n\nno tests ran in 0.00s")
    assert "needs-attention" in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert pf(t["baseline"]) == {"passed": 0, "failed": 0}
    assert t["phase"] == "needs-attention" and t["attention"]["prior_phase"] == "spec"
    assert "0 tests" in t["attention"]["reason"]


def test_tests_phase_records_red_check(repo):
    wt = task_in(repo, "tests", edit_seq=2)
    done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt)
    t = task_state(repo)
    assert pf(t["red_check"]) == {"passed": 2, "failed": 1}
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
    assert pf(t["red_check"]) == {"passed": 2, "failed": 1} and t["weak_tests"] == 0


def test_red_check_with_one_weak_test_records_it_and_warns_but_still_counts_as_red(repo):
    wt = task_in(repo, "tests", baseline={"passed": 2, "failed": 0})
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 1\n\n1 failed, 3 passed in 0.01s")
    assert "WARNING: 0 guard(s) expected to pass; 1 unexpected pass(es)" in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert pf(t["red_check"]) == {"passed": 3, "failed": 1} and t["weak_tests"] == 1 and t["phase"] == "tests"


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
    assert t["red_kind"] == "build_failed" and pf(t["red_check"]) == {"passed": 0, "failed": 1} and t["weak_tests"] == 0


@pytest.mark.parametrize("name,cmd", [("swift_build_failed.txt", "swift test"), ("cargo_build_failed.txt", "cargo test")])
def test_red_run_whose_output_is_a_compiler_error_is_recorded_as_build_failed(repo, name, cmd):
    wt = task_in(repo, "tests", test_cmd=cmd, baseline={"passed": 2, "failed": 0}, edit_seq=1)
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, command="cd %s && %s" % (wt, cmd),
               error="Exit code 1\n" + fixture_output(name))
    assert "build failed" in context(out, "PostToolUseFailure")
    t = task_state(repo)
    assert t["red_kind"] == "build_failed" and pf(t["red_check"]) == {"passed": 0, "failed": 0} and t["weak_tests"] == 0
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
    assert t["red_kind"] == "tests" and pf(t["red_check"]) == {"passed": 2, "failed": 1} and t["weak_tests"] == 0


def test_verify_phase_records_the_verifiers_run_separately(repo):
    wt = task_in(repo, "verify", edit_seq=3)
    context(done(repo, cwd=wt))
    t = task_state(repo)
    assert t["verify_run"] == {"passed": 2, "failed": 0} and t["last_test_run"]["after_edit_seq"] == 3
    assert t["baseline"] is None and pf(t["red_check"]) == {"passed": 1, "failed": 1}


# ---- red by test ids: a failure that also fails at baseline is not red ---------------------------------------------

RED_TWO = ("Exit code 1\n..FF\n=========================== short test summary info ============================\n"
           "FAILED tests/test_app.py::test_broken_before_rehorse - assert 2 == 3\n"
           "FAILED tests/test_new.py::test_sub - ImportError\n2 failed, 2 passed in 0.01s\n")
RED_OLD_ONLY = ("Exit code 1\n..F.\n=========================== short test summary info ============================\n"
                "FAILED tests/test_app.py::test_broken_before_rehorse - assert 2 == 3\n1 failed, 3 passed in 0.01s\n")
BASE = ("Exit code 1\n.F\n=========================== short test summary info ============================\n"
        "FAILED tests/test_app.py::test_broken_before_rehorse - assert 2 == 3\n1 failed, 1 passed in 0.01s\n")


def test_baseline_records_the_failing_ids(repo):
    wt = task_in(repo, "spec")
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error=BASE)
    t = task_state(repo)
    assert t["baseline"] == {"passed": 1, "failed": 1, "failing": ["tests/test_app.py::test_broken_before_rehorse"]}
    assert "1 failing at baseline" in context(out, "PostToolUseFailure")


def test_red_counts_only_failures_that_were_not_failing_at_baseline(repo):
    wt = task_in(repo, "tests", baseline={"passed": 1, "failed": 1, "failing": ["tests/test_app.py::test_broken_before_rehorse"]})
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error=RED_TWO)
    r = task_state(repo)["red_check"]
    assert r["failed"] == 2 and r["new_failed"] == 1 and r["new_failing"] == ["tests/test_new.py::test_sub"] and r["preexisting"] == 1
    assert "1 new failing test(s)" in context(out, "PostToolUseFailure") and "1 failing at baseline (ignored)" in context(out, "PostToolUseFailure")


def test_red_run_where_only_the_baseline_failure_fails_is_not_red(repo):
    wt = task_in(repo, "tests", baseline={"passed": 1, "failed": 1, "failing": ["tests/test_app.py::test_broken_before_rehorse"]})
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error=RED_OLD_ONLY)
    r = task_state(repo)["red_check"]
    assert r["failed"] == 1 and r["new_failed"] == 0 and r["new_failing"] == []
    assert "0 new failing test(s)" in context(out, "PostToolUseFailure") and "also fail at baseline" in context(out, "PostToolUseFailure")


def test_red_falls_back_to_counts_with_a_warning_when_ids_are_unavailable(repo):
    wt = task_in(repo, "tests", baseline={"passed": 2, "failed": 1, "failing": None})
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error="Exit code 1\n3 failed, 2 passed in 0.01s\n")
    r = task_state(repo)["red_check"]
    assert r["new_failed"] == 2 and r["ids_unavailable"] is True and r["preexisting"] == 1
    assert "WARNING: no test ids" in context(out, "PostToolUseFailure")


def test_weak_tests_are_unchanged_by_a_preexisting_failure(repo):
    wt = task_in(repo, "tests", baseline={"passed": 1, "failed": 1, "failing": ["tests/test_app.py::test_broken_before_rehorse"]})
    done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, error=RED_TWO)  # 2 added: one fails, one passes
    assert task_state(repo)["weak_tests"] == 1


def test_real_pytest_in_a_repo_with_a_preexisting_failure_goes_red_only_on_a_new_failure(tmp_path):
    """The fixture repo has one test that fails before Rehorse touches it; baseline, a red run that adds a failing test,
    and the gate are driven with real pytest output through the hook."""
    import shutil
    import subprocess
    import sys
    import state
    repo = tmp_path / "pre"
    shutil.copytree(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "repo_with_preexisting_failure"), repo)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    cmd = "%s -m pytest -q --tb=short -rfE -p no:cacheprovider" % sys.executable
    wt = task_in(repo, "spec", test_cmd=cmd)

    def run():
        p = subprocess.run(cmd, shell=True, cwd=wt, capture_output=True, text=True)
        return done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt, command=cmd, error="Exit code %d\n%s" % (p.returncode, p.stdout))
    run()  # baseline
    assert task_state(repo)["baseline"] == {"passed": 1, "failed": 1, "failing": ["tests/test_app.py::test_broken_before_rehorse"]}
    s = state.load(str(repo))
    state.advance(s, "t-1", "tests")
    state.save(str(repo), s)
    run()  # nothing new written: the old failure alone is not red
    assert task_state(repo)["red_check"]["new_failed"] == 0
    with pytest.raises(ValueError, match="also fail at baseline"):
        state.advance(state.load(str(repo)), "t-1", "implement")
    pathlib.Path(wt, "tests", "test_new.py").write_text("def test_sub():\n    from app import sub\n    assert sub(3, 1) == 2\n")
    run()  # now a new failure next to the old one
    r = task_state(repo)["red_check"]
    assert r["new_failed"] == 1 and r["new_failing"] == ["tests/test_new.py::test_sub"] and r["preexisting"] == 1
    state.advance(state.load(str(repo)), "t-1", "implement")  # the gate lets it through now


# ---- guards: marked regression tests are expected to pass at red and are not weak, nor red ------------------------

GUARDED = ("def test_sub():\n    from app import sub\n    assert sub(3, 1) == 2\n\n\n# rehorse: guard\ndef test_add_unchanged():\n"
           "    from app import add\n    assert add(1, 2) == 3\n")


def test_guards_are_recorded_at_red_and_subtracted_from_the_early_passes(repo):
    wt = task_in(repo, "tests", baseline={"passed": 1, "failed": 0})
    pathlib.Path(wt, "tests", "test_new.py").write_text(GUARDED)  # 2 added: the guard passes, test_sub fails
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt,
               error="Exit code 1\n\nFAILED tests/test_new.py::test_sub - ImportError\n1 failed, 2 passed in 0.01s")
    t = task_state(repo)
    assert t["guards"] == ["tests/test_new.py::test_add_unchanged"] and t["weak_tests"] == 0
    assert "1 guard(s) expected to pass; 0 unexpected pass(es)" in context(out, "PostToolUseFailure")
    assert "WARNING" not in context(out, "PostToolUseFailure")


def test_an_unmarked_early_pass_is_still_unexpected_and_warns(repo):
    wt = task_in(repo, "tests", baseline={"passed": 1, "failed": 0})
    pathlib.Path(wt, "tests", "test_new.py").write_text(GUARDED + "\n\ndef test_also_passes():\n    pass\n")  # 3 added, 2 pass, 1 guard
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt,
               error="Exit code 1\n\nFAILED tests/test_new.py::test_sub - ImportError\n1 failed, 3 passed in 0.01s")
    assert task_state(repo)["weak_tests"] == 1
    assert "WARNING: 1 guard(s) expected to pass; 1 unexpected pass(es)" in context(out, "PostToolUseFailure")


def test_a_failing_guard_is_not_red(repo):
    wt = task_in(repo, "tests", baseline={"passed": 1, "failed": 0})
    pathlib.Path(wt, "tests", "test_new.py").write_text(GUARDED)
    out = done(repo, "posttoolusefailure_bash_pytest_fail", cwd=wt,
               error="Exit code 1\n\nFAILED tests/test_new.py::test_add_unchanged - assert\n1 failed, 2 passed in 0.01s")
    r = task_state(repo)["red_check"]
    assert r["new_failed"] == 0 and r["new_failing"] == [] and r["failing_guards"] == ["tests/test_new.py::test_add_unchanged"]
    assert "1 guard(s) failing" in context(out, "PostToolUseFailure")


def test_a_revision_round_re_entering_tests_does_not_overwrite_the_red_it_earned(repo):
    """A round trip back to `tests` runs the suite with the implementation present, so it is green — and recording that
    as the red check would leave `state.py advance implement` refusing the very task it just sent here. Red is evidence
    from the first tests phase; a revision does not re-earn it. `tests_sha` (set when the plan was made) is what tells
    the two apart."""
    wt = task_in(repo, "tests", edit_seq=2, tests_sha="a" * 40,
                 red_check={"passed": 2, "failed": 1, "new_failed": 1, "new_failing": ["tests/test_app.py::test_x"]})
    out = done(repo, cwd=wt)  # the fixture's run is green, as a revision round's run is
    t = task_state(repo)
    assert t["red_check"] == {"passed": 2, "failed": 1, "new_failed": 1, "new_failing": ["tests/test_app.py::test_x"]}
    assert t["last_test_run"]["after_edit_seq"] == 2, "the run itself is still recorded"
    assert "red stands from the first tests phase" in context(out)


# ---- partial runs: recorded, but not as evidence -----------------------------------------------------------------

def test_a_partial_run_is_a_diagnostic_and_nothing_else(repo):
    """rich-3871's own targeted command, verbatim from that run: a node id, extra flags, a pipe and a second command.
    (The failure body is abbreviated: the 4000-character tail the run recorded had scrolled past pytest's summary line,
    so only the command is captured, which is what this classification turns on.) That run's 1 failure was the whole
    suite's story for nine minutes, and it is evidence of neither red nor green."""
    wt = task_in(repo, "implement", edit_seq=8, test_cmd="/private/tmp/rehorse-eval/rich-3871/.venv/bin/python "
                 "-m pytest -q --tb=short -rfE", last_test_run={"passed": 931, "failed": 0, "after_edit_seq": 3})
    out = done(repo, "posttoolusefailure_bash_pytest_partial", cwd=wt)
    t = task_state(repo)
    assert t["last_test_run"] == {"passed": 931, "failed": 0, "after_edit_seq": 3}, "untouched: the Stop guard still holds"
    assert t["baseline"] is None and t["red_check"]["failed"] == 1, "and so is every count the report will print"
    runs = t["diagnostic_runs"]
    assert len(runs) == 1 and pf(runs[0]) == {"passed": 0, "failed": 1} and runs[0]["after_edit_seq"] == 8
    assert "tests/test_columns.py::test_render" in runs[0]["command"] and "output" not in runs[0]
    ctx = context(out, "PostToolUseFailure")
    assert "diagnostic run recorded" in ctx and "part of the suite" in ctx and "--tb=short -rfE" in ctx


def test_a_partial_run_in_the_tests_phase_cannot_stand_in_for_red(repo):
    wt = task_in(repo, "tests", edit_seq=1, test_cmd="python3 -m pytest -q")
    done(repo, cwd=wt, command="cd %s && python3 -m pytest -q tests/test_app.py::test_add" % wt,
         stdout="1 failed, 0 passed in 0.01s")
    t = task_state(repo)
    assert t["red_check"] is None and t["last_test_run"] is None
    assert len(t["diagnostic_runs"]) == 1


def test_diagnostic_runs_are_capped_so_state_does_not_grow_without_saying_more(repo):
    wt = task_in(repo, "implement", edit_seq=1, test_cmd="python3 -m pytest -q")
    import on_bash_done
    for n in range(on_bash_done.MAX_DIAGNOSTIC + 5):
        done(repo, cwd=wt, command="cd %s && python3 -m pytest -q -k case%d" % (wt, n), stdout="1 passed in 0.01s")
    runs = task_state(repo)["diagnostic_runs"]
    assert len(runs) == on_bash_done.MAX_DIAGNOSTIC and runs[-1]["command"].endswith("case%d" % (on_bash_done.MAX_DIAGNOSTIC + 4))
