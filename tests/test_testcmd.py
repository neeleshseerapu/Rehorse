"""testcmd.py: detect the test command, recognise test runs and test paths, parse counts from real hook output."""
import json
import os
import subprocess
import sys

import pytest
from conftest import hook_input, run_script

import testcmd

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


# ---- detection -------------------------------------------------------------

def test_detect_pytest_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
    (tmp_path / "tests").mkdir()
    assert testcmd.detect(str(tmp_path)) == {"test_cmd": "python3 -m pytest -q --tb=short -rfE", "runner": "pytest", "test_paths": ["tests/"]}


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


@pytest.mark.parametrize("files,expected", [
    ({"package.json": '{"scripts": {"dev": "vite", "test": "vitest"}}'}, "npm run dev"),
    ({"package.json": '{"scripts": {"start": "node server.js"}}'}, "npm start"),
    ({"Makefile": "test:\n\tpytest\n\nrun:\n\tpython3 app.py\n"}, "make run"),
    ({"build.sh": "#!/bin/sh\n"}, "./build.sh"),
    ({"Cargo.toml": "[package]\n"}, "cargo run"),
    ({"go.mod": "module x\n"}, "go run ."),
    ({"Package.swift": "// swift\n"}, "swift run"),
    ({"README.md": "# App\n\nInstall it, then:\n\n```\npip install -e .\npython3 -m milo --help\n```\n"}, "python3 -m milo --help"),
    ({"README.md": "# App\n\nno instructions\n"}, None),
    ({}, None),
])
def test_run_cmd_detects_how_to_run_the_project(tmp_path, files, expected):
    for name, content in files.items():
        (tmp_path / name).write_text(content)
    assert testcmd.run_cmd(str(tmp_path)) == expected


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
    assert got["test_cmd"] == python + " -m pytest -q --tb=short -rfE"
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


# ---- swift, build failures, run command (from the Milo run) ----------------------------------------------------

def test_detect_swift_package(tmp_path):
    (tmp_path / "Package.swift").write_text("// swift-tools-version:5.9\n")
    (tmp_path / "Tests").mkdir()
    got = testcmd.detect(str(tmp_path))
    assert got["test_cmd"] == "swift test" and got["runner"] == "swift" and got["test_paths"] == ["Tests/"]
    assert testcmd.is_test_command("swift test --filter Parser", "swift test")


def test_parse_counts_swift_xctest_summary():
    out = open(os.path.join(os.path.dirname(__file__), "fixtures", "runner_output", "swift_tests_red.txt")).read()
    assert testcmd.parse_counts(out) == {"passed": 2, "failed": 1}
    assert testcmd.parse_counts("\t Executed 0 tests, with 0 failures (0 unexpected) in 0.000 (0.001) seconds") == {"passed": 0, "failed": 0}


@pytest.mark.parametrize("name,expected", [
    ("swift_build_failed.txt", True),
    ("cargo_build_failed.txt", True),
    ("swift_tests_red.txt", False),
])
def test_build_failed_recognises_compiler_errors_but_not_test_failures(name, expected):
    out = open(os.path.join(os.path.dirname(__file__), "fixtures", "runner_output", name)).read()
    assert testcmd.build_failed(out) is expected
    assert testcmd.parse_counts(out) is None if expected else testcmd.parse_counts(out) is not None


def test_build_failed_also_matches_go_and_pytest_import_errors():
    assert testcmd.build_failed("./app_test.go:5:2: undefined: sub\nFAIL\tmilo [build failed]\n")
    assert not testcmd.build_failed("FAILED tests/test_app.py::test_sub - assert 1 == 2\n1 failed, 2 passed in 0.01s")


# ---- the verifier's one writable file, named so the runner discovers it -------------------------------------------

@pytest.mark.parametrize("test_cmd,test_paths,files,expected", [
    ("python3 -m pytest -q", ["tests/"], [], "tests/test_rehorse_verify_t-1.py"),
    ("python3 -m pytest -q", [], [], "tests/test_rehorse_verify_t-1.py"),
    ("npx vitest run --reporter=dot", ["test/"], ["tsconfig.json"], "test/rehorse_verify_t-1.test.ts"),
    ("npx jest", ["__tests__/"], [], "__tests__/rehorse_verify_t-1.test.js"),
    ("cargo test", ["tests/"], [], "tests/rehorse_verify_t-1.rs"),
    ("go test ./...", [], [], "rehorse_verify_t-1_test.go"),
    ("swift test", ["Tests/"], ["Tests/MiloTests/ParserTests.swift"], "Tests/MiloTests/rehorse_verify_t-1.swift"),
    ("make test", ["tests/"], ["tests/test_a.py"], "tests/test_rehorse_verify_t-1.py"),
])
def test_verify_file_per_runner(tmp_path, test_cmd, test_paths, files, expected):
    for f in files:
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("")
    task = {"id": "t-1", "test_cmd": test_cmd, "test_paths": test_paths}
    assert testcmd.verify_file(task, str(tmp_path)) == expected


# ---- failing test ids: the red gate compares them against the baseline instead of counting -----------------------

def test_failing_ids_pytest_from_the_captured_failure():
    err = hook_input("posttoolusefailure_bash_pytest_fail")["error"]
    assert testcmd.failing_ids(err) == ["tests/test_red.py::test_sub_missing"]


def test_failing_ids_pytest_collection_error_and_parametrized_ids():
    out = ("=========================== short test summary info ============================\n"
           "ERROR tests/test_pretty.py - ModuleNotFoundError: No module named 'attr'\n"
           "FAILED tests/test_x.py::test_p[a-b] - assert 1 == 2\n"
           "FAILED tests/test_x.py::TestK::test_m\n"
           "2 failed, 1 error in 0.10s\n")
    assert testcmd.failing_ids(out) == ["tests/test_pretty.py", "tests/test_x.py::TestK::test_m", "tests/test_x.py::test_p[a-b]"]


def test_failing_ids_vitest_from_the_captured_failure():
    err = hook_input("posttoolusefailure_bash_vitest_fail")["error"]
    assert testcmd.failing_ids(err) == ["sum.test.js > fails on purpose"]


@pytest.mark.parametrize("text,expected", [
    (" FAIL  src/sum.test.js\n  ● sum › adds\n\nTests:       1 failed, 1 passed, 2 total\n", ["sum › adds"]),  # jest
    ("test parse::empty ... FAILED\ntest parse::ok ... ok\ntest result: FAILED. 1 passed; 1 failed; 0 ignored\n", ["parse::empty"]),  # cargo
    ("--- FAIL: TestOpen (0.00s)\nFAIL\nFAIL\tpkg\t0.01s\n", ["TestOpen"]),  # go
    (open(os.path.join(FIXTURES_DIR, "runner_output", "swift_tests_red.txt")).read(), ["MiloTests.ParserTests testOpen"]),  # swift
    ("..\n2 passed in 0.01s\n", []),  # nothing failed: an empty list, not None
])
def test_failing_ids_other_runners(text, expected):
    assert testcmd.failing_ids(text) == expected


def test_failing_ids_is_none_when_the_runner_printed_failures_but_no_ids():
    assert testcmd.failing_ids("1 failed, 2 passed in 0.01s\n") is None
    assert testcmd.failing_ids("Tests  1 failed | 1 passed (2)\n") is None


# ---- scope: is this run the whole suite the task is judged by, or a slice of it? ----------------------------------

RICH = "/private/tmp/rehorse-eval/rich-3871/.venv/bin/python -m pytest -q --tb=short -rfE"


@pytest.mark.parametrize("test_cmd, command, expected", [
    # the recorded command, however it is dressed up, is always the whole suite
    (RICH, "cd /wt && " + RICH, "full"),
    ("python3 -m pytest -q", "python3 -m pytest -q --tb=long", "full"),
    ("cargo test", "cargo test --quiet", "full"),
    ("make test", "cd /wt && make test", "full"),
    ("python3 -m pytest -q", "cd /wt && python3 -m pytest -q > /tmp/out.txt", "full"),
    # rich-3871's own diagnostic: a node id, extra flags, a pipe and a second command after it
    (RICH, "/private/tmp/rehorse-eval/rich-3871/.venv/bin/python -m pytest -q -vv tests/test_columns.py::test_render"
           " 2>&1 | sed -n 1,80p; sed -n 1,70p /wt/tests/test_columns.py", "partial"),
    # paths the recorded command already carries are the suite; a narrower one is not
    ("python3 -m pytest -q tests/", "cd /wt && python3 -m pytest -q tests/", "full"),
    ("python3 -m pytest -q tests/", "cd /wt && python3 -m pytest -q -vv tests/", "full"),
    ("python3 -m pytest -q tests/", "cd /wt && python3 -m pytest -q tests/test_a.py", "partial"),
    ("go test ./...", "cd /wt && go test ./...", "full"),
    ("go test ./...", "cd /wt && go test ./pkg/table", "partial"),
    ("npx vitest run --reporter=dot", "cd /wt && npx vitest run --reporter=dot", "full"),
    ("npx vitest run --reporter=dot", "npx vitest run --reporter=dot src/a.test.ts", "partial"),
    # selectors, and the -m that is python's module flag rather than pytest's marker
    ("python3 -m pytest -q", "python3 -m pytest -q -k 'not slow'", "partial"),
    ("python3 -m pytest -q", "python3 -m pytest -q -k=slow", "partial"),
    ("python3 -m pytest -q", "python3 -m pytest -q -m smoke", "partial"),
    ("python3 -m pytest -q", "cd /wt && python3 -m pytest -q", "full"),
    # a suite the recorded command itself defines by a marker: repeating it is full, changing it is not
    ("python3 -m pytest -m smoke", "cd /wt && python3 -m pytest -m smoke", "full"),
    ("python3 -m pytest -m smoke", "python3 -m pytest -q -m smoke", "full"),
    ("python3 -m pytest -m smoke", "python3 -m pytest -q -m other", "partial"),
])
def test_scope_calls_a_narrowed_run_partial_and_everything_else_full(test_cmd, command, expected):
    assert testcmd.scope(command, test_cmd) == expected


def test_scope_defaults_to_full_when_it_recognises_nothing():
    """A run wrongly called partial leaves the task unable to satisfy any gate; one wrongly called full costs a warning.
    So the classifier only ever answers `partial` on evidence it can point at."""
    assert testcmd.scope("./run-my-tests.sh", "python3 -m pytest -q") == "full"
    assert testcmd.scope("", "python3 -m pytest -q") == "full"
