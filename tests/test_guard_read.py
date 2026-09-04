"""guard_read.py (PreToolUse Read|Grep|Glob): the verifier's inputs are the brief and the worktree, nothing else."""
import os

import pytest
from conftest import hook_input, hook_out, run_script, task_in, task_state

VERIFIER = "rehorse:rehorse-verifier"


def read(repo, path=None, tool="Read", agent_type=VERIFIER, agent=True, cwd=None):
    payload = dict(hook_input("pretooluse_edit_subagent"), cwd=cwd or str(repo), tool_name=tool)
    if agent:
        payload["agent_type"] = agent_type
    else:
        payload.pop("agent_id"), payload.pop("agent_type")
    key = "file_path" if tool == "Read" else "path"
    payload["tool_input"] = {key: path} if path is not None else {"pattern": "x"}
    return hook_out(run_script("guard_read", stdin=payload, cwd=cwd or str(repo)))


def denied(out):
    h = (out or {}).get("hookSpecificOutput") or {}
    assert h.get("hookEventName") == "PreToolUse" and h.get("permissionDecision") == "deny", out
    assert h["permissionDecisionReason"].startswith("REHORSE: ")
    return h["permissionDecisionReason"]


def test_dormant_without_an_active_task_or_for_other_agents(repo, tmp_path):
    assert read(repo, str(repo / "rehorse-reports" / "PROGRESS.md")) is None
    task_in(repo, "verify")
    assert read(repo, str(repo / "rehorse-reports" / "PROGRESS.md"), agent_type="rehorse:rehorse-step") is None
    assert read(repo, str(repo / "rehorse-reports" / "PROGRESS.md"), agent=False) is None  # the orchestrator
    outside = tmp_path.parent / "nowhere"
    outside.mkdir(exist_ok=True)
    assert read(repo, str(outside / "x"), cwd=str(outside)) is None  # not a repo


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
def test_verifier_may_read_the_worktree_and_its_brief_only(repo, tool):
    wt = task_in(repo, "verify")
    os.makedirs(os.path.join(str(repo), ".rehorse", "verify"))
    brief = os.path.join(str(repo), ".rehorse", "verify", "t-1-round1.md")
    open(brief, "w").write("brief")
    assert read(repo, wt + "/app.py", tool) is None
    assert read(repo, wt + "/tests", tool) is None
    assert read(repo, brief, tool) is None
    for path in [str(repo / "rehorse-reports" / "PROGRESS.md"), wt + "/rehorse-reports/2026-x.md", str(repo / ".rehorse" / "state.json"),
                 str(repo / ".rehorse" / "handoff.json"), str(repo / "app.py"), str(repo)]:
        reason = denied(read(repo, path, tool))
        assert "verifier" in reason and wt in reason and "brief" in reason, path


def test_grep_and_glob_without_a_path_search_the_main_checkout_and_are_denied(repo):
    wt = task_in(repo, "verify")
    reason = denied(read(repo, None, "Grep"))
    assert "path" in reason and wt in reason
    assert read(repo, None, "Grep", cwd=wt) is None  # cwd inside the worktree: the default path is fine
    denied(read(repo, None, "Glob"))


def test_read_guard_bumps_nothing(repo):
    wt = task_in(repo, "verify")
    read(repo, wt + "/app.py")
    assert task_state(repo)["edit_seq"] == 0


def test_hooks_json_wires_read_grep_glob_to_guard_read():
    import json
    hooks = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks", "hooks.json")))["hooks"]
    entry = [h for h in hooks["PreToolUse"] if "guard_read.py" in h["hooks"][0]["args"][0]]
    assert len(entry) == 1 and entry[0]["matcher"] == "Read|Grep|Glob"
