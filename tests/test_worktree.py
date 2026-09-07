"""worktree.py: the rehearsal sandbox. Every operation is a git subprocess; nothing here touches the main checkout's branch."""
import json
import os

from conftest import git, run_script

import worktree


def test_create_makes_worktree_branch_and_records_base_sha(repo):
    info = worktree.create(str(repo), "t-1")
    assert info == {"worktree": ".rehorse/worktrees/t-1", "branch": "rehorse/t-1", "base_sha": git(repo, "rev-parse", "HEAD").strip(),
                    "linked_deps": []}
    wt = repo / ".rehorse" / "worktrees" / "t-1"
    assert (wt / "app.py").exists()
    assert git(wt, "branch", "--show-current").strip() == "rehorse/t-1"
    assert git(repo, "branch", "--show-current").strip() == "main"  # main checkout untouched


def test_create_adds_rehorse_to_gitignore_once(repo):
    worktree.create(str(repo), "t-1")
    worktree.create(str(repo), "t-2")
    assert (repo / ".gitignore").read_text().count(".rehorse/") == 1
    assert git(repo, "status", "--porcelain").strip() == "?? .gitignore"  # worktrees themselves are ignored


def test_create_excludes_the_spec_file_and_test_caches_locally_not_in_gitignore(repo):
    worktree.create(str(repo), "t-1")
    exclude = (repo / ".git" / "info" / "exclude").read_text()
    assert "REHORSE_SPEC.md" in exclude and "__pycache__/" in exclude and ".pytest_cache/" in exclude
    worktree.create(str(repo), "t-2")
    assert (repo / ".git" / "info" / "exclude").read_text().count("REHORSE_SPEC.md") == 1
    wt = repo / ".rehorse" / "worktrees" / "t-1"
    (wt / "REHORSE_SPEC.md").write_text("# spec\n")
    (wt / "__pycache__").mkdir()
    (wt / "__pycache__" / "app.pyc").write_text("")
    assert worktree.dirty(str(repo), "t-1") == []
    assert "REHORSE_SPEC.md" not in (repo / ".gitignore").read_text()


def test_create_symlinks_gitignored_dependency_dirs_from_the_main_checkout(venv_repo):
    """Fresh worktrees have no .venv/node_modules/target/.tox (gitignored), so the baseline would fail on any real repo."""
    import subprocess
    import sys
    root = str(venv_repo)
    (venv_repo / ".gitignore").write_text(".venv/\nnode_modules/\n")
    (venv_repo / "node_modules").mkdir()
    (venv_repo / "node_modules" / "left-pad.js").write_text("")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    info = worktree.create(root, "t-1")
    wt = venv_repo / ".rehorse" / "worktrees" / "t-1"
    assert info["linked_deps"] == [".venv", "node_modules"]  # present in the main checkout; target/ and .tox/ are not
    for name in info["linked_deps"]:
        assert os.path.islink(wt / name) and os.path.realpath(wt / name) == os.path.realpath(venv_repo / name)
    assert not os.path.exists(wt / "target") and not os.path.exists(wt / ".tox")
    prefix = subprocess.run([str(wt / ".venv" / "bin" / "python"), "-c", "import sys; print(sys.prefix)"], capture_output=True, text=True).stdout.strip()
    assert os.path.realpath(prefix) == os.path.realpath(root + "/.venv")  # the worktree now runs the repo's own interpreter
    assert worktree.dirty(root, "t-1") == []  # a symlink never shows up as work to commit


def test_create_links_nothing_when_the_main_checkout_has_no_dependency_dirs(repo):
    assert worktree.create(str(repo), "t-1")["linked_deps"] == []


def test_list_shows_only_rehorse_worktrees(repo):
    worktree.create(str(repo), "t-1")
    listed = worktree.list_(str(repo))
    assert [w["branch"] for w in listed] == ["rehorse/t-1"]
    assert listed[0]["path"] == os.path.realpath(repo / ".rehorse" / "worktrees" / "t-1")


def test_diff_is_base_to_head_and_stat(repo):
    info = worktree.create(str(repo), "t-1")
    wt = repo / ".rehorse" / "worktrees" / "t-1"
    (wt / "app.py").write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    assert worktree.diff(str(repo), "t-1", info["base_sha"]) == ""  # uncommitted work is not in base..HEAD
    git(wt, "commit", "-qam", "add sub")
    full = worktree.diff(str(repo), "t-1", info["base_sha"])
    assert "+def sub(a, b):" in full
    assert "app.py | 3 +++" in worktree.diff(str(repo), "t-1", info["base_sha"], stat=True)
    assert worktree.diff(str(repo), "t-1", info["base_sha"], paths=["tests/"]) == ""


def test_dirty_reports_uncommitted_files(repo):
    worktree.create(str(repo), "t-1")
    assert worktree.dirty(str(repo), "t-1") == []
    (repo / ".rehorse" / "worktrees" / "t-1" / "new.py").write_text("x = 1\n")
    assert worktree.dirty(str(repo), "t-1") == ["new.py"]


def test_remove_deletes_worktree_and_branch(repo):
    worktree.create(str(repo), "t-1")
    worktree.remove(str(repo), "t-1")
    assert not (repo / ".rehorse" / "worktrees" / "t-1").exists()
    assert "rehorse/t-1" not in git(repo, "branch", "--list")
    assert worktree.list_(str(repo)) == []
    worktree.remove(str(repo), "t-1")  # idempotent


def test_contains_resolves_symlinks_like_macos_tmp(tmp_path):
    real = tmp_path / "real"
    (real / "wt").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real)
    assert worktree.contains(str(link / "wt"), str(real / "wt" / "a.py"))
    assert worktree.contains(str(real / "wt"), str(link / "wt" / "sub" / "a.py"))
    assert not worktree.contains(str(real / "wt"), str(real / "wt2" / "a.py"))  # prefix trap: wt vs wt2
    assert not worktree.contains(str(real / "wt"), str(real / "a.py"))


def test_cli_create_list_diff_remove(repo):
    r = run_script("worktree", ["create", "t-1"], cwd=str(repo))
    assert r.returncode == 0, r.stderr
    info = json.loads(r.stdout)
    assert info["branch"] == "rehorse/t-1"
    r = run_script("worktree", ["list"], cwd=str(repo))
    assert json.loads(r.stdout)[0]["branch"] == "rehorse/t-1"
    r = run_script("worktree", ["diff", "t-1", "--base", info["base_sha"], "--stat"], cwd=str(repo))
    assert r.returncode == 0 and r.stdout == ""
    r = run_script("worktree", ["remove", "t-1"], cwd=str(repo))
    assert r.returncode == 0 and json.loads(run_script("worktree", ["list"], cwd=str(repo)).stdout) == []


def test_create_also_links_a_workspaces_per_package_dependency_dirs(workspace_repo):
    """pnpm installs per package as well as at the root: without packages/*/node_modules the worktree resolves a
    workspace package to the main checkout's build, and zod's two treeshaking files fail there and pass with them."""
    root = str(workspace_repo)
    info = worktree.create(root, "t-1")
    wt = workspace_repo / ".rehorse" / "worktrees" / "t-1"
    assert info["linked_deps"] == ["node_modules", "packages/a/node_modules", "packages/b/node_modules"]
    for name in info["linked_deps"]:
        assert os.path.islink(wt / name) and os.path.realpath(wt / name) == os.path.realpath(workspace_repo / name)
        assert (wt / name / "installed.marker").read_text() == name  # the same install, not a copy of it
    assert worktree.dirty(root, "t-1") == []  # each link is excluded, so none of them shows up as work to commit


def test_a_package_that_is_not_in_the_worktree_is_not_linked_into_it(workspace_repo):
    """An untracked package has no directory in the worktree to hang the link off; skipping it beats creating one."""
    (workspace_repo / "packages" / "untracked").mkdir()
    (workspace_repo / "packages" / "untracked" / "node_modules").mkdir()
    info = worktree.create(str(workspace_repo), "t-1")
    assert "packages/untracked/node_modules" not in info["linked_deps"]
