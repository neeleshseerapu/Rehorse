"""guard_edit.py (PreToolUse Edit|Write|MultiEdit): worktree isolation, phase path lock, orchestrator rule, edit_seq."""
import pytest
from conftest import hook_input, hook_out, run_script, task_in, task_state


def edit(repo, path, subagent=False, tool="Edit", cwd=None):
    payload = dict(hook_input("pretooluse_edit_subagent" if subagent else "pretooluse_edit_lock"), cwd=cwd or str(repo))
    payload["tool_name"] = tool
    payload["tool_input"] = dict(payload["tool_input"], file_path=path)
    return hook_out(run_script("guard_edit", stdin=payload, cwd=cwd or str(repo)))


def denied(out):
    h = (out or {}).get("hookSpecificOutput") or {}
    assert h.get("hookEventName") == "PreToolUse" and h.get("permissionDecision") == "deny", out
    assert h["permissionDecisionReason"].startswith("REHORSE: ")
    return h["permissionDecisionReason"]


def test_dormant_without_an_active_task_prints_nothing(repo, tmp_path):
    assert edit(repo, str(repo / "app.py")) is None
    assert edit(repo, str(tmp_path / "x.py"), cwd=str(tmp_path)) is None  # not even a repo


def test_real_fixture_path_is_outside_the_worktree_and_denied(repo):
    wt = task_in(repo, "spec")
    payload = dict(hook_input("pretooluse_edit_lock"), cwd=str(repo))  # file_path: /tmp/rehorse-spike/toy/app.lock
    reason = denied(hook_out(run_script("guard_edit", stdin=payload, cwd=str(repo))))
    assert "outside the active worktree" in reason and wt in reason


def test_edit_in_main_checkout_is_denied_with_the_worktree_path_to_use_instead(repo):
    wt = task_in(repo, "spec")
    reason = denied(edit(repo, str(repo / "app.py")))
    assert wt + "/app.py" in reason
    assert task_state(repo)["edit_seq"] == 0


@pytest.mark.parametrize("tool", ["Edit", "Write", "MultiEdit"])
def test_all_three_edit_tools_are_guarded(repo, tool):
    task_in(repo, "spec")
    denied(edit(repo, str(repo / "app.py"), tool=tool))


def test_edit_inside_worktree_is_allowed_and_bumps_edit_seq(repo):
    wt = task_in(repo, "spec")
    assert edit(repo, wt + "/app.py") is None
    assert edit(repo, wt + "/REHORSE_SPEC.md") is None
    assert task_state(repo)["edit_seq"] == 2


def test_state_file_is_never_edited_directly(repo):
    task_in(repo, "spec")
    reason = denied(edit(repo, str(repo / ".rehorse" / "state.json")))
    assert "state.py" in reason


def test_reports_dir_is_writable_from_either_checkout_without_bumping_edit_seq(repo):
    wt = task_in(repo, "implement")
    assert edit(repo, str(repo / "rehorse-reports" / "PROGRESS.md")) is None
    assert edit(repo, wt + "/rehorse-reports/2026-09-03-x.md") is None
    assert task_state(repo)["edit_seq"] == 0


def test_tests_phase_locks_non_test_paths(repo):
    wt = task_in(repo, "tests")
    reason = denied(edit(repo, wt + "/app.py"))
    assert "phase tests" in reason and "test" in reason
    assert edit(repo, wt + "/tests/test_new.py") is None
    assert edit(repo, wt + "/src/pkg/util_test.py") is None  # filename pattern, outside tests/
    assert task_state(repo)["edit_seq"] == 2


def test_implement_phase_locks_test_paths_even_for_subagents(repo):
    wt = task_in(repo, "implement")
    reason = denied(edit(repo, wt + "/tests/test_app.py", subagent=True))
    assert "phase implement" in reason and "locked" in reason
    denied(edit(repo, wt + "/conftest.py", subagent=True))
    assert edit(repo, wt + "/app.py", subagent=True) is None
    assert task_state(repo)["edit_seq"] == 1


def test_implement_phase_denies_the_orchestrator_but_not_its_reports(repo):
    wt = task_in(repo, "implement")
    reason = denied(edit(repo, wt + "/app.py"))  # no agent_id: main thread
    assert "Agent tool" in reason or "subagent" in reason
    assert edit(repo, wt + "/rehorse-reports/PROGRESS.md") is None
    assert task_state(repo)["edit_seq"] == 0


@pytest.mark.parametrize("phase", ["setup", "spec", "report"])
def test_other_phases_enforce_isolation_only(repo, phase):
    wt = task_in(repo, phase)
    assert edit(repo, wt + "/app.py") is None
    assert edit(repo, wt + "/tests/test_app.py") is None
    denied(edit(repo, str(repo / "app.py")))


def test_needs_attention_still_isolates(repo):
    import state
    wt = task_in(repo, "implement")
    s = state.load(str(repo))
    state.advance(s, "t-1", "needs-attention", reason="x")
    state.save(str(repo), s)
    denied(edit(repo, str(repo / "app.py")))
    assert edit(repo, wt + "/app.py") is None


def test_verify_phase_allows_only_the_verifiers_own_test_file(repo):
    wt = task_in(repo, "verify")
    assert edit(repo, wt + "/tests/test_rehorse_verify_t-1.py", subagent=True) is None
    assert edit(repo, wt + "/tests/rehorse_verify_t-1.test.ts", subagent=True) is None  # any runner's naming, same stem
    for path in ["/app.py", "/tests/test_app.py", "/rehorse_verify_t-1.py", "/tests/test_rehorse_verify_t-2.py"]:
        reason = denied(edit(repo, wt + path, subagent=True))
        assert "phase verify" in reason and "tests/test_rehorse_verify_t-1.py" in reason and "fixes nothing" in reason
    assert edit(repo, wt + "/rehorse-reports/PROGRESS.md") is None
    assert task_state(repo)["edit_seq"] == 2


def test_after_a_round_trip_the_verifiers_file_is_locked_like_every_test(repo):
    wt = task_in(repo, "implement")
    reason = denied(edit(repo, wt + "/tests/test_rehorse_verify_t-1.py", subagent=True))
    assert "locked" in reason and "step summary" in reason
