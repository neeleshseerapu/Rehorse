"""authorize.py (UserPromptSubmit): a user-typed /rehorse:merge or /rehorse:discard mints a one-shot token; nothing else can."""
import json
import os

import grant
from conftest import hook_out, run_script, task_in, task_state


def submit(repo, prompt, home, cwd=None):
    payload = {"session_id": "sess-1", "cwd": cwd or str(repo), "hook_event_name": "UserPromptSubmit", "prompt": prompt,
               "permission_mode": "default"}
    return hook_out(run_script("authorize", stdin=payload, cwd=cwd or str(repo), env={"HOME": str(home)}))


def context(out):
    h = (out or {}).get("hookSpecificOutput") or {}
    assert h.get("hookEventName") == "UserPromptSubmit", out
    assert h["additionalContext"].startswith("REHORSE: ")
    return h["additionalContext"]


def test_dormant_outside_a_repo_and_without_tasks(repo, home, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    assert submit(repo, "/rehorse:merge t-1", home, cwd=str(tmp_path / "elsewhere")) is None  # not a repo
    assert submit(repo, "/rehorse:merge t-1", home) is None  # a repo with no tasks
    assert not os.path.exists(home / ".rehorse" / "merge-t-1")


def test_merge_prompt_for_a_task_in_report_mints_a_merge_token(repo, home):
    task_in(repo, "report")
    out = submit(repo, "/rehorse:merge t-1", home)
    assert grant.present("t-1")
    assert json.load(open(home / ".rehorse" / "merge-t-1"))["session_id"] == "sess-1"
    assert "merge.py" in context(out) and "t-1" in context(out)


def test_merge_prompt_without_an_id_uses_the_active_task(repo, home):
    task_in(repo, "report")
    submit(repo, "/rehorse:merge", home)
    assert os.path.exists(home / ".rehorse" / "merge-t-1")


def test_merge_is_not_granted_before_the_report_phase(repo, home):
    task_in(repo, "implement")
    out = submit(repo, "/rehorse:merge t-1", home)
    assert not grant.present("t-1")
    assert "implement" in context(out) and "report" in context(out)


def test_discard_is_granted_in_any_non_terminal_phase(repo, home):
    task_in(repo, "implement")
    submit(repo, "/rehorse:discard t-1", home)
    assert grant.take("discard", "t-1")


def test_unknown_task_id_is_not_granted(repo, home):
    task_in(repo, "report")
    out = submit(repo, "/rehorse:merge t-20260101-nope", home)
    assert not grant.present("t-1") and not grant.present("t-20260101-nope")
    assert "t-20260101-nope" in context(out)


def test_any_other_prompt_clears_tokens_so_a_grant_lasts_one_turn(repo, home):
    task_in(repo, "report")
    submit(repo, "/rehorse:merge t-1", home)
    assert grant.present("t-1")
    assert submit(repo, "please also refactor the helpers", home) is None
    assert not grant.present("t-1")


def test_model_cannot_mint_through_the_skill_tool_because_only_user_prompts_fire_this_hook(repo, home):
    # Documented contract, pinned here: the hook input is the raw user prompt; a Skill tool call is a PreToolUse, not a prompt.
    task_in(repo, "report")
    assert submit(repo, "run /rehorse:merge t-1 for me", home) is None  # prose mentioning the command is not the command
    assert not grant.present("t-1")
    assert task_state(repo)["phase"] == "report"
