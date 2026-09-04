"""Shared fixtures: real hook inputs from the Day-1 spikes, and a throwaway git repo."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "hook_inputs")
sys.path.insert(0, SCRIPTS)


def hook_input(name):
    """Load a captured hook input by fixture filename stem."""
    with open(os.path.join(FIXTURES, name + ".json")) as f:
        return json.load(f)


def run_script(name, args=(), stdin=None, cwd=None):
    """Invoke scripts/<name>.py exactly as Claude Code does: python3 script, JSON on stdin."""
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, name + ".py"), *args],
        input=json.dumps(stdin) if stdin is not None else "",
        capture_output=True, text=True, cwd=cwd,
    )


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    """A git repo with one commit, a tiny pytest suite, and identity configured for commits."""
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "t")
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def task_in(repo, phase, **fields):
    """Active task 't-1' with a real worktree, advanced to `phase`, extra state fields applied. Returns the worktree path."""
    import state
    import worktree
    s = state.empty()
    t = state.new_task(s, "t-1")
    t.update(worktree.create(str(repo), "t-1"))
    t.update({"test_cmd": "python3 -m pytest -q", "test_paths": ["tests/"]}, **fields)
    for p in state.PHASES[1:state.PHASES.index(phase) + 1]:
        state.advance(s, "t-1", p)
    state.save(str(repo), s)
    return os.path.realpath(os.path.join(str(repo), t["worktree"]))


def task_state(repo):
    import state
    return state.load(str(repo))["tasks"]["t-1"]


def hook_out(result):
    """Parsed stdout of a hook run (None when the hook printed nothing, i.e. normal permission flow)."""
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None
