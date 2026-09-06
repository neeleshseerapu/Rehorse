"""The two constraints on the scripts, checked rather than trusted: a hook entry script stays under 150 lines, and
nothing under scripts/ imports anything outside the standard library.

The line cap is what makes "read the hook before you trust it" possible, so it is the entry scripts named in
hooks/hooks.json that it binds. Shared logic they import lives in scripts/rehorse_lib/, which has no cap and the same
stdlib-only rule. The import check is what "no API keys, no external services" means in practice: a third-party import
would be a dependency the user has to install and a network call nobody asked for."""
import ast
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
CAP = 150


def hook_entry_scripts():
    """Every script hooks.json points Claude Code at, by basename: these are the files the cap binds."""
    hooks = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))["hooks"]
    return sorted({h["args"][0].rsplit("/", 1)[-1] for event in hooks.values() for entry in event for h in entry["hooks"]})


def py_files():
    for dirpath, _, names in os.walk(SCRIPTS):
        if "__pycache__" in dirpath:
            continue
        for n in sorted(names):
            if n.endswith(".py"):
                yield os.path.relpath(os.path.join(dirpath, n), SCRIPTS)


def test_hooks_json_names_the_scripts_the_cap_binds():
    assert hook_entry_scripts() == ["authorize.py", "guard_bash.py", "guard_edit.py", "guard_read.py", "guard_stop.py",
                                    "handoff.py", "on_bash_done.py", "state.py", "step_done.py", "verify.py"]


@pytest.mark.parametrize("name", hook_entry_scripts())
def test_every_hook_entry_script_is_under_the_line_cap(name):
    n = len(open(os.path.join(SCRIPTS, name)).read().splitlines())
    assert n < CAP, "%s is %d lines; move logic into scripts/rehorse_lib/ rather than raising the cap" % (name, n)


@pytest.mark.parametrize("rel", list(py_files()))
def test_no_script_imports_anything_outside_the_standard_library(rel):
    """Local modules resolve because the entry script's directory is on sys.path; everything else must be stdlib."""
    import sys
    local = {f[:-3].replace(os.sep, ".") for f in py_files()} | {"rehorse_lib", "conftest"}
    tree = ast.parse(open(os.path.join(SCRIPTS, rel)).read())
    for node in ast.walk(tree):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                 [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else [])
        for name in names:
            top = name.split(".")[0]
            assert top in sys.stdlib_module_names or top in local or name in local, \
                "%s imports %s, which is neither stdlib nor a sibling script" % (rel, name)


def test_rehorse_lib_is_a_plain_package_with_no_install_step():
    """No setup.py, no pyproject, no path juggling: `from rehorse_lib import x` works because scripts/ is sys.path[0]."""
    assert os.path.isfile(os.path.join(SCRIPTS, "rehorse_lib", "__init__.py"))
    assert not [f for f in os.listdir(SCRIPTS) if f in ("setup.py", "pyproject.toml", "setup.cfg")]
