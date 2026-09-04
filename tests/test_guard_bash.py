"""guard_bash.py (PreToolUse Bash): no branch mutation, no commit outside the worktree, no rm -rf on repo/.rehorse, no --no-verify."""
import os

import pytest
from conftest import hook_input, hook_out, run_script, task_in


def bash(repo, command, cwd=None, env=None):
    payload = dict(hook_input("pretooluse_bash_git_merge"), cwd=cwd or str(repo))
    payload["tool_input"] = dict(payload["tool_input"], command=command)
    full_env = dict(os.environ, **(env or {}))
    full_env.pop("REHORSE_MERGE_TOKEN", None) if not env else None
    import subprocess, sys, json
    from conftest import SCRIPTS
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "guard_bash.py")], input=json.dumps(payload),
                       capture_output=True, text=True, cwd=cwd or str(repo), env=full_env)
    return hook_out(r)


def denied(out):
    h = (out or {}).get("hookSpecificOutput") or {}
    assert h.get("hookEventName") == "PreToolUse" and h.get("permissionDecision") == "deny", out
    assert h["permissionDecisionReason"].startswith("REHORSE: ")
    return h["permissionDecisionReason"]


def test_dormant_without_an_active_task(repo):
    assert bash(repo, "git merge some-branch") is None
    assert bash(repo, "rm -rf " + str(repo)) is None


def test_real_fixture_git_merge_is_denied_with_the_way_out(repo):
    task_in(repo, "implement")
    payload = dict(hook_input("pretooluse_bash_git_merge"), cwd=str(repo))
    reason = denied(hook_out(run_script("guard_bash", stdin=payload, cwd=str(repo))))
    assert "git merge" in reason and "/rehorse:merge" in reason


@pytest.mark.parametrize("command", [
    "git merge main",
    "git rebase main",
    "git pull",
    "git push origin main",
    "git push --force",
    "git checkout main",
    "git checkout -b other",
    "git switch main",
    "git reset --hard HEAD~1",
    "git branch -D rehorse/t-1",
    "git branch --delete rehorse/t-1",
    "git branch -m main old",
    "git worktree remove .rehorse/worktrees/t-1",
    "git worktree prune",
    "git --no-pager -C {repo} merge x",
    "git status && git merge x",
    "git status; git merge x",
    "echo $(git merge x)",
    "bash -c 'git merge x'",
    "sh -c \"cd {wt} && git push\"",
    "git status\ngit push",
])
def test_branch_mutations_are_denied_wherever_they_run(repo, command):
    wt = task_in(repo, "implement")
    reason = denied(bash(repo, command.format(repo=repo, wt=wt), cwd=wt))
    assert wt in reason


@pytest.mark.parametrize("command", [
    "git status",
    "git diff base..HEAD --stat",
    "git log --oneline -5",
    "git add -A",
    "git commit -m 'step 1'",
    "git commit -m 'note: git merge is for later'",  # commit message mentions merge
    "git restore app.py",
    "git reset HEAD~1",  # soft reset inside the worktree keeps the work
    "git stash && git stash pop",
    "git worktree list",
    "git branch --show-current",
    "python3 -m pytest -q",
    "rm -rf build/ dist/",
    "rm app.pyc",
    "rm -rf .pytest_cache",
    "echo 'git merge is denied'",
    "python3 -c 'print(1)'",
])
def test_ordinary_work_inside_the_worktree_is_allowed(repo, command):
    wt = task_in(repo, "implement")
    assert bash(repo, command, cwd=wt) is None


@pytest.mark.parametrize("command", [
    "git commit --no-verify -m x",
    "git commit -n -m x",
    "git -c core.hooksPath=/dev/null commit -m x",
])
def test_git_hook_bypasses_are_denied(repo, command):
    wt = task_in(repo, "implement")
    assert "without it" in denied(bash(repo, command, cwd=wt))


def test_commit_is_only_allowed_inside_the_worktree(repo):
    wt = task_in(repo, "implement")
    reason = denied(bash(repo, "git commit -am x", cwd=str(repo)))
    assert "cd %s && git commit" % wt in reason
    assert bash(repo, "cd %s && git commit -am x" % wt, cwd=str(repo)) is None
    assert bash(repo, "git -C %s commit -am x" % wt, cwd=str(repo)) is None


@pytest.mark.parametrize("command,cwd", [
    ("rm -rf {repo}", "{wt}"),
    ("rm -rf {repo}/", "{wt}"),
    ("rm -fr .", "{repo}"),
    ("rm -r *", "{repo}"),
    ("rm -rf ./*", "{repo}"),
    ("rm -rf .rehorse", "{repo}"),
    ("rm -rf .rehorse/worktrees/t-1", "{repo}"),
    ("rm -rf {wt}", "{repo}"),
    ("rm -Rf ../../..", "{wt}"),
    ("rm --recursive --force {repo}", "{wt}"),
    ("cd {repo} && rm -rf .", "{wt}"),
    ("rm -rf {parent}", "{wt}"),
])
def test_rm_rf_on_repo_root_or_rehorse_is_denied(repo, command, cwd):
    wt = task_in(repo, "implement")
    fmt = dict(repo=str(repo), wt=wt, parent=os.path.dirname(str(repo)))
    reason = denied(bash(repo, command.format(**fmt), cwd=cwd.format(**fmt)))
    assert "/rehorse:discard t-1" in reason


def test_merge_token_lifts_git_denials_but_not_rm(repo):
    import state
    wt = task_in(repo, "report")
    s = state.load(str(repo))
    s["merge_token"] = "tok-123"
    state.save(str(repo), s)
    denied(bash(repo, "git merge rehorse/t-1"))
    denied(bash(repo, "git merge rehorse/t-1", env={"REHORSE_MERGE_TOKEN": "wrong"}))
    assert bash(repo, "git merge rehorse/t-1", env={"REHORSE_MERGE_TOKEN": "tok-123"}) is None
    assert bash(repo, "REHORSE_MERGE_TOKEN=tok-123 git merge rehorse/t-1") is None
    denied(bash(repo, "rm -rf .rehorse", env={"REHORSE_MERGE_TOKEN": "tok-123"}))
