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
collect_ignore = ["fixtures"]  # fixture repos carry their own tests; they are data, not this suite


def hook_input(name):
    """Load a captured hook input by fixture filename stem."""
    with open(os.path.join(FIXTURES, name + ".json")) as f:
        return json.load(f)


def run_script(name, args=(), stdin=None, cwd=None, env=None):
    """Invoke scripts/<name>.py exactly as Claude Code does: python3 script, JSON on stdin. `env` overrides (e.g. HOME)."""
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, name + ".py"), *args],
        input=json.dumps(stdin) if stdin is not None else "",
        capture_output=True, text=True, cwd=cwd, env=dict(os.environ, **(env or {})),
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


VERDICT = {"round": 1, "verdict": "pass", "findings": [], "tests_added": [], "coverage": [], "tests": {"passed": 2, "failed": 0}}


def task_in(repo, phase, **fields):
    """Active task 't-1' with a real worktree, advanced to `phase`, extra state fields applied. Returns the worktree path."""
    import state
    import worktree
    s = state.empty()
    t = state.new_task(s, "t-1")
    t.update(worktree.create(str(repo), "t-1"))
    t.update({"test_cmd": "python3 -m pytest -q", "test_paths": ["tests/"]}, **fields)
    if state.PHASES.index(phase) > state.PHASES.index("tests") and t["red_check"] is None:
        t["red_check"] = {"passed": 1, "failed": 1, "new_failed": 1}  # the red gate must let the walk past tests
    if state.PHASES.index(phase) > state.PHASES.index("verify") and t["verifier"] is None:
        t["verifier"] = VERDICT  # and the verifier gate past verify
    t["phase"] = "setup"  # walk the whole machine so every transition is a legal one
    for p in state.PHASES[1:state.PHASES.index(phase) + 1]:
        state.advance(s, "t-1", p)
    state.save(str(repo), s)
    return os.path.realpath(os.path.join(str(repo), t["worktree"]))


def commit_in(wt, rel_path, content, message):
    """Write a file in the worktree and commit it; returns the new HEAD sha."""
    path = os.path.join(wt, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    git(wt, "add", "-A")
    git(wt, "commit", "-q", "-m", message)
    return git(wt, "rev-parse", "HEAD").strip()


PINNED_FIXTURE = os.path.join(ROOT, "tests", "fixtures", "repo_with_pinned_wrong_behaviour")


@pytest.fixture
def pinned_repo(tmp_path):
    """The fixture repo whose existing assertion is the bug: fixing truncate() correctly means changing that test.

    The rich-3577 shape. Used from both ends: the tests phase declaring the rewrite up front (test_step_done.py) and
    the verifier discovering it after the fact (test_verify.py)."""
    import shutil
    repo = tmp_path / "repo"
    shutil.copytree(PINNED_FIXTURE, repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture
def venv_repo(tmp_path):
    """Copy of tests/fixtures/repo_with_venv with a real (pip-less) virtualenv of its own."""
    import shutil
    dst = tmp_path / "target"
    shutil.copytree(os.path.join(ROOT, "tests", "fixtures", "repo_with_venv"), dst)
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(dst / ".venv")], check=True, capture_output=True)
    return dst


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME so grant tokens (~/.rehorse/) never touch the developer's real home."""
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def task_state(repo):
    import state
    return state.load(str(repo))["tasks"]["t-1"]


def hook_out(result):
    """Parsed stdout of a hook run (None when the hook printed nothing, i.e. normal permission flow)."""
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None
