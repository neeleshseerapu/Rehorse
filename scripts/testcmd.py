#!/usr/bin/env python3
"""Rehorse test-command heuristics, shared by the spec phase, guard_edit.py and on_bash_done.py.

  detect(root)                      -> {"test_cmd", "runner", "test_paths"} or None, from the target repo only
                                       (its .venv/venv, pyproject/pytest.ini, package.json, Makefile; never sys.executable)
  is_test_command(cmd, test_cmd)    -> does this Bash command run the project's test runner?
  is_test_path(rel_path, dirs)      -> is this file a test file (locked/unlocked by phase)?
  parse_counts(text)                -> {"passed", "failed"} from pytest / vitest / jest / cargo output, or None
                                       (0-test runs like `no tests ran` are {0, 0}; --collect-only, --version, grep hits are None)
  effective_cwd(cmd, cwd)           -> where a Bash command really runs after a leading `cd <dir> &&`
  build_failed(text)                -> did the runner output show a compiler/build error (swift, cargo, go, tsc, xcodebuild)?
  run_cmd(root)                     -> how to run the project (package.json dev/start, make run, build.sh, cargo/go/swift, README) or None
  affected_tests(root, changed, dirs) -> existing test files that look like they cover the changed files
CLI: testcmd.py detect | testcmd.py set "<cmd>" (record a user-supplied command in the active task) | testcmd.py parse
"""
import json
import os
import re
import sys

TEST_DIRS = ["tests", "test", "Tests", "__tests__", "spec"]
TEST_FILE_RE = re.compile(r"^(test_.*\.py|.*_test\.py|conftest\.py|.*\.(test|spec)\.[cm]?[jt]sx?|.*_test\.go)$")
RUNNER_TOKENS = {"pytest": ["pytest"], "vitest": ["vitest"], "jest": ["jest"], "npm": ["npm test", "npm t "],
                 "make": ["make test"], "cargo": ["cargo test"], "go": ["go test"], "swift": ["swift test"]}
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
NOT_A_RUN_RE = re.compile(r"(?:^|\s)(?:--collect-only|--co|--version|--help|-h)(?:\s|$)")
PYTEST_SUMMARY_RE = re.compile(r"^=*\s*(?:no tests ran|\d+ [a-z]+(?:, \d+ [a-z]+)*) in \d+(?:\.\d+)?s(?: \(.*\))?\s*=*$")
NO_TESTS_RE = re.compile(r"^No tests? (?:files )?found")
XCTEST_RE = re.compile(r"Executed (\d+) tests?, with (\d+) failures?")
BUILD_ERROR_RE = re.compile(r"(?m)^(?:\S+:\d+:\d+: )?(?:fatal )?error(?:\[E\d+\])?: |error TS\d+: |\[build failed\]|\*\* BUILD FAILED \*\*|could not compile")


def _test_dirs(root):
    names = set(os.listdir(root)) if os.path.isdir(root) else set()  # exact names: macOS says isdir("Tests") when tests/ exists
    return [d + "/" for d in TEST_DIRS if d in names and os.path.isdir(os.path.join(root, d))]


def _has_pytest_config(root):
    for name in ("pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml", "conftest.py"):
        p = os.path.join(root, name)
        if os.path.exists(p) and (name in ("pytest.ini", "conftest.py") or "pytest" in open(p, errors="ignore").read()):
            return True
    return any(TEST_FILE_RE.match(f) and f.endswith(".py") for d in _test_dirs(root) for f in os.listdir(os.path.join(root, d)))


def _python(root):
    """The target repo's own interpreter when it has a venv; otherwise whatever `python3` is on the Bash tool's PATH.
    Never sys.executable: that is the interpreter running Rehorse, not the project's."""
    for d in (".venv", "venv"):
        for rel in ("bin/python", "Scripts/python.exe"):
            p = os.path.join(root, d, rel)
            if os.path.exists(p):
                return p
    return "python3"


def detect(root):
    dirs = _test_dirs(root)
    if _has_pytest_config(root):
        return {"test_cmd": _python(root) + " -m pytest -q --tb=short", "runner": "pytest", "test_paths": dirs}
    pkg = os.path.join(root, "package.json")
    if os.path.exists(pkg):
        script = (json.load(open(pkg)).get("scripts") or {}).get("test", "")
        if script and "no test specified" not in script:
            runner = "vitest" if "vitest" in script else "jest" if "jest" in script else "npm"
            cmd = {"vitest": "npx vitest run --reporter=dot", "jest": "npx jest", "npm": "npm test"}[runner]
            return {"test_cmd": cmd, "runner": runner, "test_paths": dirs}
    mk = os.path.join(root, "Makefile")
    if os.path.exists(mk) and re.search(r"^test\s*:", open(mk, errors="ignore").read(), re.M):
        return {"test_cmd": "make test", "runner": "make", "test_paths": dirs}
    if os.path.exists(os.path.join(root, "Cargo.toml")):
        return {"test_cmd": "cargo test", "runner": "cargo", "test_paths": dirs}
    if os.path.exists(os.path.join(root, "go.mod")):
        return {"test_cmd": "go test ./...", "runner": "go", "test_paths": dirs}
    if os.path.exists(os.path.join(root, "Package.swift")):
        return {"test_cmd": "swift test", "runner": "swift", "test_paths": dirs}
    return None


def build_failed(text):
    """Compiler/build errors in runner output: the tests never ran, so no summary line exists (or fewer tests ran)."""
    return bool(BUILD_ERROR_RE.search(ANSI_RE.sub("", text or "")))


def runner_of(test_cmd):
    return next((r for r, toks in RUNNER_TOKENS.items() if any(t.strip() in test_cmd for t in toks)), None)


def is_test_command(command, test_cmd):
    """Match on the runner, not the exact string: venv python, `cd x &&`, and extra flags all still count."""
    runner = runner_of(test_cmd)
    if not runner or NOT_A_RUN_RE.search(command):
        return False
    return any(t in command + " " for t in RUNNER_TOKENS[runner])


def effective_cwd(command, cwd):
    """Directory a Bash command runs in: `cd <dir> &&` / `;` / newline at the start moves it, nothing else does."""
    m = re.match(r"\s*cd\s+(\"[^\"]+\"|'[^']+'|\S+)\s*(?:&&|;|\n)", command or "")
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(m.group(1).strip("\"'")))) if m else cwd


def is_test_path(rel_path, test_dirs):
    rel = rel_path.replace(os.sep, "/")
    if any(rel.startswith(d if d.endswith("/") else d + "/") for d in test_dirs):
        return True
    parts = rel.split("/")
    return "__tests__" in parts[:-1] or bool(TEST_FILE_RE.match(parts[-1]))


def parse_counts(text):
    """Find the runner's own summary line and read its numbers; errors count as failures.
    A summary with no passed/failed counts (`no tests ran`, `3 deselected`, `No test files found`) is a run of 0 tests."""
    for line in reversed(ANSI_RE.sub("", text or "").splitlines()):
        line = line.strip()
        if NO_TESTS_RE.match(line):
            return {"passed": 0, "failed": 0}
        m = XCTEST_RE.search(line)  # swift test / XCTest
        if m:
            return {"passed": int(m.group(1)) - int(m.group(2)), "failed": int(m.group(2))}
        pytest_line = bool(PYTEST_SUMMARY_RE.match(line)) and "collected" not in line
        if pytest_line or re.match(r"Tests:?\s", line) or line.startswith("test result:"):
            found = {k: int(n) for n, k in re.findall(r"(\d+) (passed|failed|errors?)", line)}
            if pytest_line or "passed" in found or "failed" in found:
                return {"passed": found.get("passed", 0),
                        "failed": found.get("failed", 0) + found.get("error", 0) + found.get("errors", 0)}
    return None


def affected_tests(root, changed_files, test_dirs):
    """Cheap name-based guess so an implement step can run the relevant subset before the whole suite."""
    wanted = set()
    for f in changed_files:
        stem, ext = os.path.splitext(os.path.basename(f))
        wanted.update({"test_%s.py" % stem, "%s_test.py" % stem, "%s_test.go" % stem} |
                      {"%s.%s%s" % (stem, kind, e) for kind in ("test", "spec") for e in (ext, ".js", ".ts", ".jsx", ".tsx")})
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        hits += [os.path.normpath(os.path.join(rel_dir, n)).replace(os.sep, "/") for n in filenames
                 if n in wanted and is_test_path(os.path.join(rel_dir, n), test_dirs)]
    return sorted(hits)


def main(argv):
    if argv[:1] == ["detect"]:
        json.dump(detect(os.getcwd()), sys.stdout)
    elif argv[:1] == ["set"] and len(argv) == 2:
        import state
        root, s, task = state.active(os.getcwd())
        if not task:
            sys.exit("testcmd.py set: no active task")
        task.update(test_cmd=argv[1], test_paths=_test_dirs(root))
        state.save(root, s)
    elif argv[:1] == ["parse"]:
        hook = json.load(sys.stdin)
        text = hook.get("error") or (hook.get("tool_response") or {}).get("stdout") or ""
        json.dump(parse_counts(text), sys.stdout)
    else:
        sys.exit(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
