"""testcmd.py: detect the test command, recognise test runs and test paths, parse counts from real hook output."""
import json
import os
import subprocess
import sys

import pytest
from conftest import hook_input, run_script

import testcmd


# ---- detection -------------------------------------------------------------

def test_detect_pytest_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
    (tmp_path / "tests").mkdir()
    assert testcmd.detect(str(tmp_path)) == {"test_cmd": "python3 -m pytest -q --tb=short", "runner": "pytest", "test_paths": ["tests/"]}


def test_detect_pytest_from_tests_dir_alone(tmp_path):
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "test_x.py").write_text("")
    assert testcmd.detect(str(tmp_path))["runner"] == "pytest"
    assert testcmd.detect(str(tmp_path))["test_paths"] == ["test/"]


@pytest.mark.parametrize("script,cmd,runner", [
    ("vitest run", "npx vitest run --reporter=dot", "vitest"),
    ("jest --ci", "npx jest", "jest"),
    ("node --test", "npm test", "npm"),
])
def test_detect_from_package_json_test_script(tmp_path, script, cmd, runner):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": script}}))
    (tmp_path / "__tests__").mkdir()
    got = testcmd.detect(str(tmp_path))
    assert (got["test_cmd"], got["runner"]) == (cmd, runner)
    assert got["test_paths"] == ["__tests__/"]


def test_detect_ignores_npm_placeholder_test_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": 'echo "Error: no test specified" && exit 1'}}))
    assert testcmd.detect(str(tmp_path)) is None


def test_detect_makefile_cargo_go(tmp_path):
    (tmp_path / "Makefile").write_text("build:\n\tcc x.c\n\ntest:\n\t./run\n")
    assert testcmd.detect(str(tmp_path))["test_cmd"] == "make test"
    (tmp_path / "Makefile").unlink()
    (tmp_path / "Cargo.toml").write_text("[package]\n")
    assert testcmd.detect(str(tmp_path))["test_cmd"] == "cargo test"
    (tmp_path / "Cargo.toml").unlink()
    (tmp_path / "go.mod").write_text("module x\n")
    assert testcmd.detect(str(tmp_path))["test_cmd"] == "go test ./..."


def test_detect_nothing_returns_none(tmp_path):
    assert testcmd.detect(str(tmp_path)) is None


# ---- is this Bash command a test run? --------------------------------------

def test_is_test_command_matches_real_spike_commands():
    py = hook_input("posttooluse_bash_pytest_pass")["tool_input"]["command"]
    js = hook_input("posttoolusefailure_bash_vitest_fail")["tool_input"]["command"]
    assert testcmd.is_test_command(py, "python3 -m pytest -q")  # venv python, same runner
    assert testcmd.is_test_command(js, "npx vitest run")  # cd && npx prefix
    assert not testcmd.is_test_command(py, "npx vitest run")
    assert not testcmd.is_test_command("git status", "python3 -m pytest -q")
    assert testcmd.is_test_command("npm test -- --watch=false", "npm test")
    assert not testcmd.is_test_command("npm install", "npm test")


# ---- test paths ------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("tests/test_app.py", True),
    ("tests/rehorse_verify_edge.py", True),  # the verifier's file lives under a test dir
    ("src/pkg/test_util.py", True),
    ("src/pkg/util_test.py", True),
    ("conftest.py", True),
    ("src/Button.test.tsx", True),
    ("src/Button.spec.js", True),
    ("pkg/thing_test.go", True),
    ("src/__tests__/x.js", True),
    ("app.py", False),
    ("src/testing_utils.py", False),  # 'testing' prefix is not a test file
    ("tests_data/fixture.json", False),  # not the tests/ dir
    ("docs/latest.md", False),
])
def test_is_test_path(path, expected):
    assert testcmd.is_test_path(path, ["tests/"]) is expected


def test_is_test_path_uses_configured_dirs():
    assert testcmd.is_test_path("spec/thing.rb", ["spec/"])
    assert not testcmd.is_test_path("spec/thing.rb", ["tests/"])


# ---- parse counts from real hook output ------------------------------------

def test_parse_counts_pytest_pass_from_posttooluse():
    out = hook_input("posttooluse_bash_pytest_pass")["tool_response"]["stdout"]
    assert testcmd.parse_counts(out) == {"passed": 2, "failed": 0}


def test_parse_counts_pytest_fail_from_posttoolusefailure_error():
    err = hook_input("posttoolusefailure_bash_pytest_fail")["error"]
    assert testcmd.parse_counts(err) == {"passed": 2, "failed": 1}


def test_parse_counts_vitest_fail_from_posttoolusefailure_error():
    err = hook_input("posttoolusefailure_bash_vitest_fail")["error"]
    assert testcmd.parse_counts(err) == {"passed": 1, "failed": 1}


@pytest.mark.parametrize("text,expected", [
    ("=== 3 passed, 1 error in 0.20s ===", {"passed": 3, "failed": 1}),  # errors count as failures
    ("== 5 passed, 2 skipped, 1 xfailed in 1.00s ==", {"passed": 5, "failed": 0}),
    ("\x1b[32m      Tests  4 passed (4)\x1b[0m", {"passed": 4, "failed": 0}),  # ANSI stripped
    ("Tests:       1 failed, 2 passed, 3 total", {"passed": 2, "failed": 1}),  # jest
    ("test result: ok. 7 passed; 0 failed; 0 ignored", {"passed": 7, "failed": 0}),  # cargo
    ("no tests ran in 0.01s", {"passed": 0, "failed": 0}),  # empty suite: a run of 0 tests
    ("Test Files  1 failed (1)\n", None),  # vitest file line alone is not a test count
    ("", None),
])
def test_parse_counts_other_formats(text, expected):
    assert testcmd.parse_counts(text) == expected


# ---- affected tests --------------------------------------------------------

def test_affected_tests_maps_source_files_to_existing_test_files(tmp_path):
    for p in ["tests/test_app.py", "tests/unit/test_util.py", "src/Button.test.tsx", "tests/test_other.py"]:
        (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / p).write_text("")
    got = testcmd.affected_tests(str(tmp_path), ["app.py", "src/util.py", "src/Button.tsx", "src/nothing.py"], ["tests/"])
    assert got == ["src/Button.test.tsx", "tests/test_app.py", "tests/unit/test_util.py"]


# ---- CLI -------------------------------------------------------------------

def test_cli_detect_and_parse(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    r = run_script("testcmd", ["detect"], cwd=str(tmp_path))
    assert r.returncode == 0 and json.loads(r.stdout)["runner"] == "pytest"
    r = run_script("testcmd", ["parse"], stdin=hook_input("posttoolusefailure_bash_pytest_fail"))
    assert json.loads(r.stdout) == {"passed": 2, "failed": 1}
    r = run_script("testcmd", ["parse"], stdin=hook_input("posttooluse_bash_pytest_pass"))
    assert json.loads(r.stdout) == {"passed": 2, "failed": 0}


# ---- milestone 3 additions: zero-test runs, non-runs, effective cwd -------

@pytest.mark.parametrize("text,expected", [
    ("no tests ran in 0.00s", {"passed": 0, "failed": 0}),  # pytest, empty suite (exit 5): a real run of 0 tests
    ("21 deselected in 0.00s", {"passed": 0, "failed": 0}),  # pytest -k matched nothing: ran 0 tests
    ("No test files found, exiting with code 1", {"passed": 0, "failed": 0}),  # vitest, empty
    ("No tests found, exiting with code 1", {"passed": 0, "failed": 0}),  # jest, empty
    ("test result: ok. 0 passed; 0 failed; 0 ignored", {"passed": 0, "failed": 0}),  # cargo, empty
    ("no tests collected in 0.00s", None),  # pytest --collect-only: not a run
    ("3 tests collected in 0.01s", None),  # pytest --collect-only: not a run
    ("pytest 9.1.1", None),  # pytest --version
    ("pyproject.toml:[tool.pytest.ini_options]", None),  # grep hit on the runner name
    ("Compiled in 2.1s", None),  # a build tool's timing line is not a pytest summary
    ("===== 2 passed in 65.23s (0:01:05) =====", {"passed": 2, "failed": 0}),  # pytest long-run clock suffix
])
def test_parse_counts_zero_test_runs_versus_non_runs(text, expected):
    assert testcmd.parse_counts(text) == expected


@pytest.mark.parametrize("command", [
    "python3 -m pytest --collect-only -q",
    "pytest --co",
    "pytest --version",
    "npx vitest --version",
    "python3 -m pytest --help",
])
def test_is_test_command_rejects_collect_only_version_help(command):
    assert not testcmd.is_test_command(command, "python3 -m pytest -q")
    assert not testcmd.is_test_command(command, "npx vitest run")


@pytest.mark.parametrize("command,cwd,expected", [
    ("pytest -q", "/repo", "/repo"),
    ("cd /wt && pytest -q", "/repo", "/wt"),
    ("cd sub; pytest -q", "/repo", "/repo/sub"),
    ("cd '/a b' && pytest", "/repo", "/a b"),
    ("  cd /wt\npytest", "/repo", "/wt"),
    ("echo cd /x && pytest", "/repo", "/repo"),  # only a leading cd counts
])
def test_effective_cwd_follows_a_leading_cd(command, cwd, expected):
    assert testcmd.effective_cwd(command, cwd) == expected


# ---- fix 2: the test command comes from the target repo, never from Rehorse's environment ----

def test_detect_uses_the_target_repos_own_venv_by_absolute_path(venv_repo):
    got = testcmd.detect(str(venv_repo))
    python = os.path.join(str(venv_repo), ".venv", "bin", "python")
    assert got["test_cmd"] == python + " -m pytest -q --tb=short"
    assert got["runner"] == "pytest" and got["test_paths"] == ["tests/"]
    # the interpreter named in the command really is the fixture's, not the one running this test suite
    prefix = subprocess.run([python, "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True).stdout.strip()
    assert os.path.realpath(prefix) == os.path.realpath(str(venv_repo / ".venv"))
    assert sys.executable not in got["test_cmd"]


def test_detect_never_falls_back_to_sys_executable(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    assert sys.executable not in testcmd.detect(str(tmp_path))["test_cmd"]
    assert sys.prefix not in testcmd.detect(str(tmp_path))["test_cmd"]


def test_detect_accepts_venv_dir_and_windows_layout(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "venv" / "Scripts").mkdir(parents=True)
    (tmp_path / "venv" / "Scripts" / "python.exe").write_text("")
    assert testcmd.detect(str(tmp_path))["test_cmd"].startswith(os.path.join(str(tmp_path), "venv", "Scripts", "python.exe"))


def test_set_records_a_user_supplied_command_in_the_active_task(repo):
    from conftest import task_in, task_state
    task_in(repo, "spec")
    r = run_script("testcmd", ["set", "make check"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    assert task_state(repo)["test_cmd"] == "make check"
    assert task_state(repo)["test_paths"] == ["tests/"]
