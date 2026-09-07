#!/usr/bin/env python3
"""Rehorse test-command heuristics, shared by the spec phase, guard_edit.py and on_bash_done.py.

  detect(root)                      -> {"test_cmd", "runner", "test_paths"} or None, from the target repo only
                                       (its .venv/venv, pyproject/pytest.ini, package.json, Makefile; never sys.executable)
  is_test_command(cmd, test_cmd)    -> does this Bash command run the project's test runner?
  scope(cmd, test_cmd)              -> "full" (the whole suite the task is judged by) or "partial" (narrowed to some of it)
  with_exit_status(counts, ids, nonzero) -> counts, with a non-zero exit the summary never explained recorded as failed
  is_test_path(rel_path, dirs)      -> is this file a test file (locked/unlocked by phase)?
  parse_counts(text)                -> {"passed", "failed"} from pytest / vitest / jest / cargo output, or None
                                       (0-test runs like `no tests ran` are {0, 0}; --collect-only, --version, grep hits are None)
  failing_ids(text)                 -> sorted ids of the failing tests (pytest FAILED/ERROR lines, jest ●, go --- FAIL, cargo,
                                       XCTest, vitest FAIL/× lines); [] when nothing failed; None when the runner gave counts but no ids
  effective_cwd(cmd, cwd)           -> where a Bash command really runs after a leading `cd <dir> &&`
  build_failed(text)                -> did the runner output show a compiler/build error (swift, cargo, go, tsc, xcodebuild)?
  verify_file(task, wt, changed)    -> the one file the verifier may write, placed where this runner will collect it
  file_run(test_cmd, path, dirs)    -> the recorded command narrowed to one file (the collection check), or None
  diff_paths(diff_text)             -> the files a unified diff touches
  run_cmd(root)                     -> how to run the project (package.json dev/start, make run, build.sh, cargo/go/swift, README) or None
  affected_tests(root, changed, dirs) -> existing test files that look like they cover the changed files
CLI: testcmd.py detect | testcmd.py set "<cmd>" (record a user-supplied command in the active task) | testcmd.py parse
"""
import fnmatch
import glob
import json
import os
import re
import shlex
import sys

TEST_DIRS = ["tests", "test", "Tests", "__tests__", "spec"]
TEST_FILE_RE = re.compile(r"^(test_.*\.py|.*_test\.py|conftest\.py|.*\.(test|spec)\.[cm]?[jt]sx?|.*_test\.go)$")
RUNNER_TOKENS = {"pytest": ["pytest"], "vitest": ["vitest"], "jest": ["jest"], "npm": ["npm test", "npm t "],
                 "make": ["make test"], "cargo": ["cargo test"], "go": ["go test"], "swift": ["swift test"]}
SELECTORS = ("-k", "-m", "-t", "--testNamePattern")  # narrow a suite to some of its tests: pytest -k/-m, vitest/jest -t
PROJECTS_RE = re.compile(r"projects\s*:\s*\[([^\]]*)\]", re.S)  # vitest config / workspace file: the globs it collects in
PNPM_PACKAGES_RE = re.compile(r"^packages:\s*\n((?:[ \t]*-[ \t]*\S.*\n?)+)", re.M)
LIST_ITEM_RE = re.compile(r"""^\s*-\s*['"]?([^'"\s]+)""", re.M)
QUOTED_RE = re.compile(r"""['"]([^'"]+)['"]""")
DIFF_PATH_RE = re.compile(r"^\+\+\+ b/(.+)$", re.M)
FILE_ERROR = "suite exited non-zero (file-level errors)"
FILE_RUNNERS = ("pytest", "vitest", "jest")  # runners a single file can be handed on the command line
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
        return {"test_cmd": _python(root) + " -m pytest -q --tb=short -rfE", "runner": "pytest", "test_paths": dirs}  # -rfE: failing ids
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


def _tokens(s):
    try:
        return shlex.split(s or "", comments=False)
    except ValueError:  # an unbalanced quote is not worth a traceback inside a hook
        return (s or "").split()


def _run_of(tokens, want):
    """Start index of `want` as a contiguous run in `tokens`, or None."""
    return next((i for i in range(len(tokens) - len(want) + 1) if tokens[i:i + len(want)] == want), None) if want else None


def _beyond(command, test_cmd):
    """The arguments this command adds past the recorded test command: what follows it where it appears verbatim, else
    what follows the runner token. Cut at the first shell separator or redirect, so `| sed ...` is not read as args."""
    cmd, want = _tokens(command), _tokens(test_cmd)
    i = _run_of(cmd, want)
    if i is not None:
        i += len(want)
    else:
        runner = runner_of(test_cmd) or ""
        i = next((n + 1 for n, t in enumerate(cmd) if t == runner or t.endswith("/" + runner)), None) if runner else None
        if i is None:
            return []
    out = []
    for t in cmd[i:]:
        if t in (";", "|", "||", "&&", "&") or ">" in t or "<" in t:
            break
        out.append(t)
    return out


def scope(command, test_cmd):
    """"full" when the run exercises the whole suite the task is judged by, "partial" when it narrows to part of it.

    Partial on positive evidence only: an argument beyond the recorded test command that names a file path, a node id
    (`::`), or one of SELECTORS -- pytest's `-k` / `-m`, vitest's and jest's `-t` / `--testNamePattern`, which narrow by
    test name and leave the summary reading like a whole run (`vitest run -t "passing validations"` ran 28 of zod's
    4359 tests and printed "28 passed"). A token the recorded command already carries is not evidence -- a suite whose
    own command says `tests/`, or `go test ./...`, is still the whole suite -- and a command nothing matches is `full`,
    because a run wrongly called partial leaves the task unable to satisfy any gate, while one wrongly called full only
    costs a warning."""
    want = _tokens(test_cmd)
    args = _beyond(command, test_cmd)
    for i, a in enumerate(args):
        head, eq, tail = a.partition("=")
        flag, val = (head, tail) if eq and head in SELECTORS else (a, args[i + 1] if i + 1 < len(args) else "")
        if flag in SELECTORS:  # `python -m pytest`'s -m is not pytest's: only the ones past the runner reach here
            if _run_of(want, [flag, val]) is None and _run_of(want, [flag + "=" + val]) is None:
                return "partial"  # the same selector the recorded command carries is that suite, not a slice of it
        elif not a.startswith("-") and a not in want and ("::" in a or "/" in a or TEST_FILE_RE.match(a)):
            return "partial"
    return "full"


def with_exit_status(counts, ids, nonzero):
    """A run whose runner exited non-zero while its summary counted no failure failed at file level: a file that throws
    on import or in a `beforeAll` never reaches a per-test result, so vitest reports `Test Files 2 failed` and
    `Tests 4351 passed` on a run that exited 1 -- which the green gate (0 failed, >0 passed) would accept.

    Positive evidence only, like scope(): the runner must have named failures (`ids`) its own summary did not count, so
    a test command with a linter or a coverage gate chained after it is not read as a failing suite. The named failures
    are the count, because they are what the runner said failed; FILE_ERROR is how every message explains the number."""
    if nonzero and counts and counts["passed"] and not counts["failed"] and ids:
        return dict(counts, failed=len(ids), file_errors=True)
    return counts


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


ID_FAMILIES = [  # one family per runner, tried in order; the first that matches anything wins
    re.compile(r"^(?:FAILED|ERROR) (\S+)", re.M),                       # pytest -rfE (an ERROR is a collection failure)
    re.compile(r"^\s*● (\S.*?)\s*$", re.M),                             # jest
    re.compile(r"^--- FAIL: (\S+)", re.M),                               # go test
    re.compile(r"^test (\S+) \.\.\. FAILED", re.M),                      # cargo test
    re.compile(r"Test Case '-\[(.+?)\]' failed", re.M),                  # XCTest
    re.compile(r"^\s*FAIL\s+(\S.*?)\s*$", re.M),                         # vitest: FAIL  file > name
    re.compile(r"^\s*[×✗✕]\s+(\S.*?)(?:\s+\d+ms)?\s*$", re.M),           # vitest per-test lines (name only)
]


def failing_ids(text):
    """Ids of the failing tests, so red can mean 'fails now and did not at baseline' rather than a count. None when the
    output has failures but no ids the families above recognise (the caller falls back to counts and says so)."""
    clean = ANSI_RE.sub("", text or "")
    for fam in ID_FAMILIES:
        found = sorted(set(fam.findall(clean)))
        if found:
            return found
    counts = parse_counts(clean)
    return [] if counts and not counts["failed"] else None


def _read(path):
    return open(path, errors="ignore").read() if os.path.exists(path) else ""


def _project_globs(wt):
    """Directory globs this project treats as packages: vitest's `projects:` (or a vitest.workspace file), package.json
    `workspaces`, pnpm-workspace.yaml. Config files listed among the projects (`./vitest.compile.config.ts`) are not
    directories and are dropped."""
    out = []
    for name in ("vitest.config.ts", "vitest.config.js", "vitest.config.mts", "vitest.workspace.ts", "vitest.workspace.js"):
        m = PROJECTS_RE.search(_read(os.path.join(wt, name)))
        out += QUOTED_RE.findall(m.group(1)) if m else []
    try:
        ws = json.loads(_read(os.path.join(wt, "package.json")) or "{}").get("workspaces") or []
    except ValueError:
        ws = []
    out += (ws.get("packages") or []) if isinstance(ws, dict) else list(ws)
    m = PNPM_PACKAGES_RE.search(_read(os.path.join(wt, "pnpm-workspace.yaml")))
    out += LIST_ITEM_RE.findall(m.group(1)) if m else []
    return [g.rstrip("/") for g in out if not g.startswith(("!", ".")) and not g.endswith((".ts", ".js", ".json", ".mts"))]


def _pkg_of(rel, globs):
    """The configured package directory holding `rel`, or None: `packages/*` owns `packages/zod/src/v4/schemas.ts`."""
    parts = rel.split("/")
    for g in globs:
        depth = len(g.split("/"))
        if len(parts) > depth and fnmatch.fnmatch("/".join(parts[:depth]), g):
            return "/".join(parts[:depth])
    return None


def _test_dir_near(wt, rel, stop=None):
    """Nearest existing test directory at or above `rel`'s own directory, going no higher than `stop`. The file's own
    neighbourhood first: a change in packages/zod/src/v4/classic belongs in that directory's tests/, not the repo's."""
    d = os.path.dirname(rel)
    while True:
        for name in TEST_DIRS:
            cand = "/".join(filter(None, [d, name]))
            if os.path.isdir(os.path.join(wt, cand)):
                return cand + "/"
        if d == (stop or "") or not d:
            return None
        d = os.path.dirname(d)


def _pkg_test_dir(wt, pkg):
    """The directory inside `pkg` that already holds test files (one named tests/, test/, __tests__/ wins), or None."""
    best = None
    for dirpath, dirnames, filenames in os.walk(os.path.join(wt, pkg)):
        dirnames[:] = sorted(d for d in dirnames if d != "node_modules" and not d.startswith("."))
        if any(TEST_FILE_RE.match(f) for f in filenames):
            rel = os.path.relpath(dirpath, wt).replace(os.sep, "/")
            if os.path.basename(rel) in TEST_DIRS:
                return rel + "/"
            best = best or rel + "/"
    return best


def _js_dir(wt, changed):
    """Where a vitest/jest file has to live to be collected. A workspace runner looks only inside its configured
    projects, so the package the diff touches decides; with no diff yet, the first configured project that has tests
    does. None when neither answers and the caller's test_paths default stands."""
    globs = _project_globs(wt)
    for rel in changed:
        pkg = _pkg_of(rel, globs)
        if pkg:
            return _test_dir_near(wt, rel, stop=pkg) or _pkg_test_dir(wt, pkg) or pkg + "/"
    for rel in changed:  # no workspace: the test dir next to the change still beats the repo's first one
        d = _test_dir_near(wt, rel)
        if d:
            return d
    projects = [os.path.relpath(p, wt).replace(os.sep, "/") for g in globs
                for p in sorted(glob.glob(os.path.join(wt, g))) if os.path.isdir(p)]
    return next((d for p in projects for d in [_pkg_test_dir(wt, p)] if d), projects[0] + "/" if projects else None)


def verify_file(task, wt, changed=()):
    """The verifier's one writable file, relative to the worktree: pytest only collects test_*.py, vitest/jest *.test.*,
    go *_test.go next to the package, cargo tests/*.rs, XCTest any .swift in the test target's directory.

    Recorded in state the first time it is derived (`task["verify_file"]`), so the brief, the edit guard's message and a
    round-trip step all name one path, and round 2 does not move the file round 1 committed. For vitest and jest the
    path comes from the diff: those runners collect only inside their configured projects, so a file in the repo's root
    tests/ is run by nothing at all (zod: `projects: ["packages/*"]`) and the verifier's verdict would rest on tests
    that never executed."""
    if task.get("verify_file"):
        return task["verify_file"]
    tid, runner, d = task["id"], runner_of(task.get("test_cmd") or ""), (task.get("test_paths") or ["tests/"])[0]
    if runner == "go":
        return "rehorse_verify_%s_test.go" % tid
    if runner == "cargo":
        return "%srehorse_verify_%s.rs" % (d, tid)
    if runner == "swift":
        subs = sorted(x for x in (os.listdir(os.path.join(wt, d)) if os.path.isdir(os.path.join(wt, d)) else []) if os.path.isdir(os.path.join(wt, d, x)))
        return "%s%s/rehorse_verify_%s.swift" % (d, subs[0], tid) if subs else "%srehorse_verify_%s.swift" % (d, tid)
    if runner in ("vitest", "jest", "npm"):
        d = _js_dir(wt, changed) or d
        return "%srehorse_verify_%s.test.%s" % (d, tid, "ts" if os.path.exists(os.path.join(wt, "tsconfig.json")) else "js")
    return "%stest_rehorse_verify_%s.py" % (d, tid)


def file_run(test_cmd, rel_path, test_paths=()):
    """The recorded test command narrowed to one file: its test-path arguments replaced by that file, everything else
    kept (zod's `pnpm build &&` is how its suite runs at all). None for a runner that cannot be handed a file, where
    "this file alone" is not a question it can be asked."""
    if runner_of(test_cmd) not in FILE_RUNNERS:
        return None
    kept = [t for i, t in enumerate(_tokens(test_cmd)) if i == 0 or t.startswith("-") or not is_test_path(t, test_paths)]
    return " ".join(kept + [shlex.quote(rel_path)])


def diff_paths(diff_text):
    """The files a unified diff touches, in the order it lists them (a deleted file's /dev/null is not one)."""
    return [p for p in DIFF_PATH_RE.findall(diff_text or "") if p != "/dev/null"]


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


RUN_LINE_RE = re.compile(r"^\$?\s*((?:npm|yarn|pnpm|npx|bun|node|python3?|uv|make|cargo|go|swift|dotnet|java|\./)\S*\b.*)$")


def run_cmd(root):
    """How a person runs the project, for the report's 'Try it yourself' section. None when nothing is detectable."""
    pkg = os.path.join(root, "package.json")
    if os.path.exists(pkg):
        scripts = json.load(open(pkg)).get("scripts") or {}
        if "dev" in scripts:
            return "npm run dev"
        if "start" in scripts:
            return "npm start"
    mk = os.path.join(root, "Makefile")
    if os.path.exists(mk) and re.search(r"^run\s*:", open(mk, errors="ignore").read(), re.M):
        return "make run"
    for name, cmd in (("build.sh", "./build.sh"), ("Cargo.toml", "cargo run"), ("go.mod", "go run ."), ("Package.swift", "swift run")):
        if os.path.exists(os.path.join(root, name)):
            return cmd
    for readme in ("README.md", "README.rst", "README"):
        if os.path.exists(os.path.join(root, readme)):
            fenced = False
            for line in open(os.path.join(root, readme), errors="ignore"):
                fenced = not fenced if line.startswith("```") else fenced
                m = fenced and RUN_LINE_RE.match(line.strip())
                if m and not re.search(r"\b(install|test|lint|build|add|upgrade)\b", line):
                    return m.group(1)
    return None


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
