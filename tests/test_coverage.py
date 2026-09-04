"""coverage.py: acceptance criteria from REHORSE_SPEC.md mapped to new tests; what is missing blocks tests -> implement."""
import os

from conftest import commit_in, git, task_in, task_state

import coverage
import state

SPEC = ("Add sub and mul.\n\n## Acceptance criteria\n\n1. sub(5, 3) == 2\n2. mul(2, 3) == 6\n3) mul(0, 9) == 0\n\n"
        "## Files likely involved\n- app.py\n")


def test_criteria_are_the_numbered_or_bulleted_items_under_the_heading():
    assert coverage.criteria(SPEC) == ["sub(5, 3) == 2", "mul(2, 3) == 6", "mul(0, 9) == 0"]
    assert coverage.criteria("## Acceptance criteria\n- one\n- two\n### Notes\n- not a criterion\n") == ["one", "two"]
    assert coverage.criteria("Goal only.\n") is None


def test_json_block_is_the_last_fenced_block_or_none():
    assert coverage.json_block('x\n```json\n{"a": 1}\n```\ny\n```json\n{"coverage": []}\n```') == {"coverage": []}
    assert coverage.json_block("nothing here") is None
    assert coverage.json_block("```json\nnot json\n```") is None


def test_matches_by_number_or_by_text():
    assert coverage.matches(2, "mul(2, 3) == 6", "2")
    assert coverage.matches(2, "mul(2, 3) == 6", "2. mul(2, 3) == 6")
    assert coverage.matches(2, "mul(2, 3) == 6", "MUL(2, 3) == 6")
    assert not coverage.matches(2, "mul(2, 3) == 6", "3. mul(0, 9) == 0")
    assert not coverage.matches(2, "mul(2, 3) == 6", "sub")


def spec_task(repo, mapping, test_body="import app\n\ndef test_sub():\n    assert app.sub(5, 3) == 2\n\ndef test_mul():\n    assert app.mul(2, 3) == 6\n"):
    wt = task_in(repo, "tests", coverage=mapping)
    open(os.path.join(wt, "REHORSE_SPEC.md"), "w").write(SPEC)
    commit_in(wt, "tests/test_new.py", test_body, "tests: red")
    return wt


def test_uncovered_names_criteria_with_no_mapping_a_stale_ref_or_a_missing_test(repo):
    wt = spec_task(repo, [{"criterion": "1. sub(5, 3) == 2", "ref": "tests/test_new.py::test_sub"},
                          {"criterion": "2", "ref": "tests/test_app.py::test_add"},
                          {"criterion": "3", "ref": "tests/test_new.py::test_zero"}])
    s = state.load(str(repo))
    un = coverage.uncovered(str(repo), s["tasks"]["t-1"])
    assert len(un) == 2
    assert un[0].startswith("2. mul(2, 3) == 6:") and "tests/test_app.py" in un[0] and "not a new or changed test file" in un[0]
    assert un[1].startswith("3. mul(0, 9) == 0:") and "test_zero" in un[1] and "not found" in un[1]


def test_uncovered_is_empty_when_every_criterion_has_a_real_new_test_and_uncommitted_tests_count(repo):
    wt = spec_task(repo, [{"criterion": 1, "ref": "tests/test_new.py::test_sub"}, {"criterion": 2, "ref": "tests/test_new.py::test_mul"},
                          {"criterion": 3, "ref": "tests/test_more.py::test_zero"}])
    open(os.path.join(wt, "tests", "test_more.py"), "w").write("def test_zero():\n    assert 0\n")
    assert coverage.uncovered(str(repo), state.load(str(repo))["tasks"]["t-1"]) == []


def test_a_spec_without_the_section_or_a_task_without_a_mapping_is_uncovered(repo):
    wt = task_in(repo, "tests")
    open(os.path.join(wt, "REHORSE_SPEC.md"), "w").write("Goal only.\n")
    un = coverage.uncovered(str(repo), state.load(str(repo))["tasks"]["t-1"])
    assert len(un) == 1 and "Acceptance criteria" in un[0]
    open(os.path.join(wt, "REHORSE_SPEC.md"), "w").write(SPEC)
    un = coverage.uncovered(str(repo), state.load(str(repo))["tasks"]["t-1"])
    assert len(un) == 3 and all("no test mapped" in u for u in un)
