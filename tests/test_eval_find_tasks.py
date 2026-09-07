"""find_tasks.py: which closed issues with a merged PR are eval candidates, and what record they become."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval"))
import find_tasks  # noqa: E402


def pr(number, files, merged=True, parent="aaa111", base="bbb222", repo="o/r"):
    return {"number": number, "url": "https://github.com/%s/pull/%d" % (repo, number), "merged": merged, "changedFiles": len(files),
            "repository": {"nameWithOwner": repo},
            "mergeCommit": {"oid": "mmm", "parents": {"nodes": [{"oid": parent}]}} if merged else None, "baseRefOid": base,
            "files": {"nodes": [{"path": f} for f in files]}}


def issue(number, prs, body="body"):
    return {"number": number, "title": "Issue %d" % number, "url": "https://github.com/o/r/issues/%d" % number, "body": body,
            "closedByPullRequestsReferences": {"nodes": prs}}


def test_candidate_needs_a_merged_pr_touching_one_to_five_files_with_a_test_and_a_source_file():
    good = issue(1, [pr(10, ["rich/segment.py", "tests/test_segment.py"])])
    unmerged = issue(2, [pr(11, ["rich/a.py", "tests/test_a.py"], merged=False)])
    too_big = issue(3, [pr(12, ["a.py", "b.py", "c.py", "d.py", "e.py", "tests/test_a.py"])])
    no_test = issue(4, [pr(13, ["rich/a.py", "CHANGELOG.md"])])
    only_tests = issue(5, [pr(14, ["tests/test_a.py"])])
    no_pr = issue(6, [])
    got = [c["issue"] for c in find_tasks.candidates("o/r", [good, unmerged, too_big, no_test, only_tests, no_pr])]
    assert got == [1]


def test_candidate_record_matches_the_tasks_json_schema_and_uses_the_merge_commits_parent_as_base():
    [c] = find_tasks.candidates("Textualize/rich", [issue(3299, [pr(4155, ["CHANGELOG.md", "rich/segment.py", "tests/test_segment.py"],
                                                                  repo="Textualize/rich")])])
    task = c["task"]
    assert set(task) == {"id", "repo", "base_sha", "issue_url", "issue_title", "issue_body", "pr_url", "pr_test_files", "test_cmd", "setup_cmd"}
    assert task["id"] == "rich-3299" and task["repo"] == "Textualize/rich" and task["base_sha"] == "aaa111"
    assert task["pr_test_files"] == ["tests/test_segment.py"] and task["pr_url"].endswith("/pull/4155")
    assert "pytest" in task["test_cmd"] and "venv" in task["setup_cmd"]
    assert c["src_files"] == ["CHANGELOG.md", "rich/segment.py"]


def test_base_sha_falls_back_to_the_prs_base_ref_when_the_merge_commit_is_unknown():
    p = pr(10, ["a.py", "tests/test_a.py"])
    p["mergeCommit"] = None
    [c] = find_tasks.candidates("o/r", [issue(1, [p])])
    assert c["task"]["base_sha"] == "bbb222"


def test_first_merged_pr_wins_when_an_issue_was_closed_by_several():
    i = issue(1, [pr(10, ["a.py", "tests/test_a.py"], merged=False), pr(11, ["b.py", "tests/test_b.py"])])
    [c] = find_tasks.candidates("o/r", [i])
    assert c["task"]["pr_url"].endswith("/pull/11")


def test_a_closing_pr_in_another_repository_is_not_a_candidate():
    """zod#5760 is closed by elastic/kibana#266343: its base_sha is not in zod's history and its files are kibana's."""
    foreign = issue(5760, [pr(266343, ["src/a.ts", "src/a.test.ts"], repo="elastic/kibana")])
    own = issue(5761, [pr(12, ["src/b.ts", "src/b.test.ts"], repo="colinhacks/zod")])
    assert [c["issue"] for c in find_tasks.candidates("colinhacks/zod", [foreign, own])] == [5761]


# ---- eval/tasks.json: thirty tasks pasted by hand, so what is pasted is checked --------------------------------

def tasks_json():
    return json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval", "tasks.json")))


def test_every_task_carries_the_candidate_schema_a_tier_and_its_repos_own_commands():
    """The records are copied out of eval/candidates-<repo>.json by hand. A retyped setup or test command is the kind
    of drift nothing else would catch: the eval would run, and it would be measuring a different environment."""
    tasks = tasks_json()
    assert len(tasks) == len({t["id"] for t in tasks}) == 30
    for t in tasks:
        assert set(t) == {"id", "repo", "base_sha", "issue_url", "issue_title", "issue_body", "pr_url",
                          "pr_test_files", "test_cmd", "setup_cmd", "tier"}, t["id"]
        assert t["tier"] in (1, 2, 3) and len(t["base_sha"]) == 40 and t["pr_test_files"]
        assert t["id"].startswith(t["repo"].split("/")[1] + "-") and t["id"].split("-")[1] in t["issue_url"]
        assert (t["setup_cmd"], t["test_cmd"]) == (find_tasks.DEFAULTS[t["repo"]]["setup_cmd"],
                                                   find_tasks.DEFAULTS[t["repo"]]["test_cmd"]), t["id"]


def test_the_three_repos_carry_ten_tasks_each():
    """Ten per repo is the eval's own methodology; a repo short of ten is a table that cannot be compared across them."""
    from collections import Counter
    assert Counter(t["repo"] for t in tasks_json()) == {"Textualize/rich": 10, "fastapi/fastapi": 10, "colinhacks/zod": 10}
