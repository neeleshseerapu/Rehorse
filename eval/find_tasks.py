#!/usr/bin/env python3
"""List eval candidates for a repo: closed issues whose linked PR is merged, touches 1-5 files, and adds or changes a
test file next to at least one source file. Prints one line per candidate and writes the full records, in the
eval/tasks.json schema, to a JSON file so the ten can be picked by hand and pasted in.

  python3 eval/find_tasks.py Textualize/rich [--scan 300] [--out eval/candidates-rich.json]

base_sha is the merge commit's first parent (the base branch the moment before the fix landed: right for both true
merges and squashes), falling back to the PR's baseRefOid, which can be months stale. Needs `gh` logged in.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import testcmd  # noqa: E402

MAX_FILES = 5
DEFAULTS = {  # per-repo setup and test commands; the target's own venv, so the plugin's interpreter never leaks in
    "Textualize/rich": {"setup_cmd": "python3 -m venv .venv && .venv/bin/pip install -q -e . pytest",
                        "test_cmd": ".venv/bin/python -m pytest -q --tb=short"},
    "fastapi/fastapi": {"setup_cmd": "python3 -m venv .venv && .venv/bin/pip install -q -e '.[all]' -r requirements-tests.txt",
                        "test_cmd": ".venv/bin/python -m pytest -q --tb=short"},
    "colinhacks/zod": {"setup_cmd": "npm ci", "test_cmd": "npx vitest run --reporter=dot"},
}
QUERY = """query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(first: 50, states: CLOSED, orderBy: {field: CREATED_AT, direction: DESC}, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { number title url body
        closedByPullRequestsReferences(first: 5) { nodes { number url merged changedFiles baseRefOid
          mergeCommit { oid parents(first: 1) { nodes { oid } } } files(first: 10) { nodes { path } } } } } } } }"""


def fetch_issues(repo, scan):
    """Closed issues, newest first, up to `scan` of them, via gh's GraphQL endpoint."""
    owner, name = repo.split("/")
    after, issues = None, []
    while len(issues) < scan:
        args = ["gh", "api", "graphql", "-f", "query=" + QUERY, "-F", "owner=" + owner, "-F", "name=" + name]
        if after:
            args += ["-F", "after=" + after]
        page = json.loads(subprocess.run(args, capture_output=True, text=True, check=True).stdout)["data"]["repository"]["issues"]
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    return issues[:scan]


def candidates(repo, issues):
    """[{issue, task, src_files}] for issues whose first merged PR fits the filter."""
    out, short = [], repo.split("/")[1]
    for i in issues:
        for p in i["closedByPullRequestsReferences"]["nodes"]:
            if not p["merged"] or not 1 <= p["changedFiles"] <= MAX_FILES:
                continue
            files = [f["path"] for f in p["files"]["nodes"]]
            tests = [f for f in files if testcmd.is_test_path(f, ["tests/", "test/"])]
            src = [f for f in files if f not in tests]
            if not tests or not src:
                continue
            parents = ((p.get("mergeCommit") or {}).get("parents") or {}).get("nodes") or []
            task = {"id": "%s-%d" % (short, i["number"]), "repo": repo, "base_sha": parents[0]["oid"] if parents else p["baseRefOid"],
                    "issue_url": i["url"], "issue_title": i["title"], "issue_body": i.get("body") or "", "pr_url": p["url"],
                    "pr_test_files": tests, **DEFAULTS.get(repo, {"setup_cmd": "", "test_cmd": ""})}
            out.append({"issue": i["number"], "task": task, "src_files": src})
            break
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo", help="owner/name")
    ap.add_argument("--scan", type=int, default=300, help="closed issues to look through, newest first")
    ap.add_argument("--out", help="where to write the candidate records (default eval/candidates-<name>.json)")
    a = ap.parse_args(argv)
    found = candidates(a.repo, fetch_issues(a.repo, a.scan))
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "candidates-%s.json" % a.repo.split("/")[1])
    with open(out, "w") as f:
        json.dump([c["task"] for c in found], f, indent=2)
    print("%-6s %-6s %-10s %-3s %-3s %s" % ("issue", "pr", "base_sha", "src", "tst", "title"))
    for c in found:
        t = c["task"]
        print("%-6d %-6s %-10s %-3d %-3d %s" % (c["issue"], t["pr_url"].rsplit("/", 1)[1], t["base_sha"][:10], len(c["src_files"]), len(t["pr_test_files"]), t["issue_title"][:70]))
    print("%d candidate(s) from %d issue(s) scanned; records in %s" % (len(found), a.scan, out), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
