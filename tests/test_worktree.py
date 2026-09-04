"""worktree.py: the rehearsal sandbox. Every operation is a git subprocess; nothing here touches the main checkout's branch."""
import json
import os

from conftest import git, run_script

import worktree


def test_create_makes_worktree_branch_and_records_base_sha(repo):
    info = worktree.create(str(repo), "t-1")
    assert info == {"worktree": ".rehorse/worktrees/t-1", "branch": "rehorse/t-1", "base_sha": git(repo, "rev-parse", "HEAD").strip()}
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
