"""guard_bash.py (PreToolUse Bash): no branch mutation, no commit outside the worktree, no rm -rf on repo/.rehorse, no --no-verify."""
import os

import pytest
from conftest import hook_input, hook_out, run_script, task_in


def bash(repo, command, cwd=None):
    payload = dict(hook_input("pretooluse_bash_git_merge"), cwd=cwd or str(repo))
    payload["tool_input"] = dict(payload["tool_input"], command=command)
    return hook_out(run_script("guard_bash", stdin=payload, cwd=cwd or str(repo)))


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


def test_user_grant_file_lifts_git_denials_but_not_rm(repo, home):
    import grant
    task_in(repo, "report")
    denied(bash(repo, "git merge rehorse/t-1"))
    grant.mint("merge", "t-1", "s")
    assert bash(repo, "git merge rehorse/t-1") is None
    assert bash(repo, "git branch -D rehorse/t-1") is None
    denied(bash(repo, "rm -rf .rehorse"))
    grant.clear(["t-1"])
    denied(bash(repo, "git merge rehorse/t-1"))
    grant.mint("discard", "t-1", "s")
    assert bash(repo, "git worktree remove .rehorse/worktrees/t-1") is None


def test_env_var_tokens_from_the_old_design_are_ignored(repo, home):
    import state
    task_in(repo, "report")
    s = state.load(str(repo))
    s["merge_token"] = "tok-123"
    state.save(str(repo), s)
    denied(bash(repo, "REHORSE_MERGE_TOKEN=tok-123 git merge rehorse/t-1"))


@pytest.mark.parametrize("command", [
    "cat ~/.rehorse/merge-t-1",
    "touch $HOME/.rehorse/merge-t-1",
    "ls ${HOME}/.rehorse",
    "echo '{}' > {home}/.rehorse/discard-t-1",
    "python3 -c \"open('{home}/.rehorse/merge-t-1','w')\"",
])
def test_the_grant_directory_is_unreachable_from_bash(repo, home, command):
    task_in(repo, "implement")
    reason = denied(bash(repo, command.replace("{home}", str(home))))
    assert "/rehorse:merge" in reason and ".rehorse" in reason


# ---- milestone 4 live run: step agents wrote files with `printf >> app.py`, bypassing guard_edit ---------------

@pytest.mark.parametrize("command", [
    "printf 'def sub(a, b):\\n    return a - b\\n' >> app.py",
    "echo x > tests/test_app.py",
    "cat <<'EOF' > app.py\nx\nEOF",
    "cd {wt} && printf 'x' >> app.py && pytest -q",
    "sed -i '' 's/add/sub/' app.py",
    "perl -pi -e 's/a/b/' app.py",
    "tee app.py < other.py",
    "cp other.py app.py",
    "mv other.py app.py",
    "python3 - > app.py",
])
def test_file_writes_from_bash_are_denied_inside_the_repo_or_worktree(repo, command):
    wt = task_in(repo, "implement")
    reason = denied(bash(repo, command.format(wt=wt), cwd=wt))
    assert "Edit" in reason and "Write" in reason


@pytest.mark.parametrize("command", [
    "pytest -q 2>&1 | tail -5",
    "pytest -q > /dev/null 2>&1",
    "pytest -q 2>/dev/null",
    "git log --oneline > /tmp/rehorse-log.txt",
    "echo hi",
    "cat app.py",
    "git add -A && git commit -m 'step 1: x'",
    "mkdir -p build && touch build/.keep",
])
def test_redirects_to_dev_null_or_outside_the_repo_and_non_writes_are_allowed(repo, command):
    wt = task_in(repo, "implement")
    assert bash(repo, command, cwd=wt) is None
