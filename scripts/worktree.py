#!/usr/bin/env python3
"""Rehorse worktrees: create / list / diff / dirty / remove under <repo>/.rehorse/worktrees/<task-id>/.

Every operation is a git subprocess run from the main checkout or the worktree; none of them
checks out, merges, or resets the user's branch. CLI (JSON out):
  worktree.py create <id> | list | diff <id> --base SHA [--stat] [--paths p ...] | dirty <id> | remove <id>
"""
import json
import os
import subprocess
import sys


def git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check).stdout


def path_for(root, tid):
    return os.path.join(root, ".rehorse", "worktrees", tid)


def ensure_ignored(root):
    """Append '.rehorse/' to .gitignore once, so state and worktrees never show up in the user's diff."""
    gi = os.path.join(root, ".gitignore")
    lines = open(gi).read().splitlines() if os.path.exists(gi) else []
    if ".rehorse/" not in lines and ".rehorse" not in lines:
        with open(gi, "a") as f:
            f.write(("" if not lines or lines[-1] == "" else "\n") + ".rehorse/\n")


EXCLUDE = ["REHORSE_SPEC.md", "__pycache__/", ".pytest_cache/"]
DEP_DIRS = [".venv", "venv", "node_modules", "target", ".tox"]


def ensure_excluded(root, names=EXCLUDE):
    """Local-only ignores in .git/info/exclude (shared by every worktree, never committed): the spec file and test
    caches must not be swept into a step commit or trip the dirty-tree refusal."""
    path = os.path.join(root, git(root, "rev-parse", "--git-common-dir").strip(), "info", "exclude")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = open(path).read().splitlines() if os.path.exists(path) else []
    missing = [e for e in names if e not in lines]
    if missing:
        with open(path, "a") as f:
            f.write(("" if not lines or lines[-1] == "" else "\n") + "\n".join(missing) + "\n")


def link_deps(root, wt):
    """Symlink (never copy) the main checkout's gitignored dependency dirs into a fresh worktree, so the test command
    finds the same interpreter, packages and build cache there. Returns the names linked."""
    linked = []
    for name in DEP_DIRS:
        src = os.path.join(root, name)
        if os.path.isdir(src) and not os.path.lexists(os.path.join(wt, name)):
            os.symlink(src, os.path.join(wt, name))
            linked.append(name)
    ensure_excluded(root, linked)  # bare names: the user's `.venv/` pattern matches directories, and a symlink is a file
    return linked


def create(root, tid):
    """New branch rehorse/<id> at HEAD, checked out in its own directory. Returns the fields state.json needs."""
    ensure_ignored(root)
    ensure_excluded(root)
    base_sha = git(root, "rev-parse", "HEAD").strip()
    os.makedirs(os.path.dirname(path_for(root, tid)), exist_ok=True)
    git(root, "worktree", "add", "-q", "-b", "rehorse/" + tid, path_for(root, tid), "HEAD")
    return {"worktree": ".rehorse/worktrees/" + tid, "branch": "rehorse/" + tid, "base_sha": base_sha,
            "linked_deps": link_deps(root, path_for(root, tid))}


def list_(root):
    """Rehorse-owned worktrees only, parsed from `git worktree list --porcelain` (path/HEAD/branch stanzas)."""
    base = os.path.realpath(os.path.join(root, ".rehorse", "worktrees"))
    out, cur = [], {}
    for line in git(root, "worktree", "list", "--porcelain").splitlines() + [""]:
        if not line:
            if cur.get("path", "").startswith(base + os.sep):
                out.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = os.path.realpath(line[9:])
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:].replace("refs/heads/", "", 1)
    return out


def diff(root, tid, base_sha, stat=False, paths=()):
    """Committed work only: base_sha..HEAD. That is what the verifier and the report see."""
    args = ["diff", "--no-color"] + (["--stat"] if stat else []) + [base_sha + "..HEAD"]
    return git(path_for(root, tid), *args, "--", *paths)


def dirty(root, tid):
    """Uncommitted paths in the worktree (so the report can flag work that is not in the diff)."""
    return [line[3:] for line in git(path_for(root, tid), "status", "--porcelain", "--untracked-files=all").splitlines()]


def remove(root, tid):
    """Drop the directory and the branch. Idempotent; used by both merge.py and discard.py."""
    if os.path.exists(path_for(root, tid)):
        git(root, "worktree", "remove", "--force", path_for(root, tid))
    git(root, "worktree", "prune")
    git(root, "branch", "-D", "rehorse/" + tid, check=False)


def contains(worktree_path, file_path):
    """True if file_path is inside worktree_path after resolving symlinks (macOS: /tmp -> /private/tmp)."""
    wt, fp = os.path.realpath(worktree_path), os.path.realpath(file_path)
    return fp == wt or fp.startswith(wt + os.sep)


def main(argv):
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    if not root:
        sys.exit("worktree.py: not inside a git repository")
    root = os.path.realpath(root)
    cmd, args = (argv or ["help"])[0], argv[1:]
    if cmd == "create":
        result = create(root, args[0])
    elif cmd == "list":
        result = list_(root)
    elif cmd == "diff":
        base = args[args.index("--base") + 1]
        paths = args[args.index("--paths") + 1:] if "--paths" in args else ()
        sys.stdout.write(diff(root, args[0], base, stat="--stat" in args, paths=paths))
        return 0
    elif cmd == "dirty":
        result = dirty(root, args[0])
    elif cmd == "remove":
        remove(root, args[0])
        result = {"removed": args[0]}
    else:
        sys.exit(__doc__)
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
