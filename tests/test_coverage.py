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


# ---- guards: tests the tests-phase agent marks as expected to pass before the implementation ---------------------

def test_guards_are_the_marked_tests_in_the_given_files_across_runners(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(
        "def test_new():\n    assert 0\n\n\n# rehorse: guard\ndef test_add_unchanged():\n    assert 1\n\n\n"
        "class TestK:\n    # rehorse: guard\n    async def test_k(self):\n        pass\n\n\ndef test_other():  # rehorse: guard\n    pass\n")
    (tmp_path / "tests" / "a.test.ts").write_text(
        "import { it, test } from 'vitest'\n// rehorse: guard\nit('keeps adding', () => {})\ntest(\"breaks\", () => {})\n"
        "// rehorse: guard\ntest(`template name`, () => {})\n")
    (tmp_path / "tests" / "a_test.go").write_text("// rehorse: guard\nfunc TestOld(t *testing.T) {}\nfunc TestNew(t *testing.T) {}\n")
    (tmp_path / "tests" / "a.rs").write_text("// rehorse: guard\n#[test]\nfn old_still_works() {}\n#[test]\nfn new_one() {}\n")
    (tmp_path / "tests" / "A.swift").write_text("    // rehorse: guard\n    func testOld() {}\n    func testNew() {}\n")
    got = coverage.guards(str(tmp_path), ["tests/test_a.py", "tests/a.test.ts", "tests/a_test.go", "tests/a.rs", "tests/A.swift", "tests/missing.py"])
    assert got == ["tests/A.swift::testOld", "tests/a.rs::old_still_works", "tests/a.test.ts::keeps adding", "tests/a.test.ts::template name",
                   "tests/a_test.go::TestOld", "tests/test_a.py::TestK::test_k", "tests/test_a.py::test_add_unchanged", "tests/test_a.py::test_other"]


def test_changed_tests_are_the_new_or_changed_test_files_committed_or_dirty(repo):
    wt = spec_task(repo, [])
    open(os.path.join(wt, "tests", "test_dirty.py"), "w").write("def test_x():\n    pass\n")
    open(os.path.join(wt, "app.py"), "w").write("changed but not a test\n")
    assert coverage.changed_tests(str(repo), task_state(repo)) == {"tests/test_dirty.py", "tests/test_new.py"}


# ---- existing tests the tests phase changed --------------------------------------------------------------------------

BASE_TESTS = ("from app import truncate\n\n\ndef test_short():\n    assert truncate('abc', 5) == 'abc'\n\n\n"
              "def test_long():\n    assert truncate('abcdefgh', 5) == 'abcde…'\n")


def changed_task(repo, new_tests):
    """A tests-phase task whose base commit holds BASE_TESTS and whose worktree now holds `new_tests`."""
    wt = task_in(repo, "tests")
    base = state.load(str(repo))["tasks"]["t-1"]["base_sha"]
    commit_in(wt, "tests/test_app.py", BASE_TESTS, "base tests")
    s = state.load(str(repo))
    s["tasks"]["t-1"]["base_sha"] = git(wt, "rev-parse", "HEAD").strip()
    state.save(str(repo), s)
    assert base
    commit_in(wt, "tests/test_app.py", new_tests, "tests: red for t-1")
    return wt


def test_changed_existing_tests_lists_only_tests_that_existed_and_changed(repo):
    """A new test is not a change; an edited assertion and a deleted test both are."""
    edited = BASE_TESTS.replace("'abcde…'", "'abcd…'") + "\n\ndef test_new():\n    assert truncate('ab', 1) == 'a…'\n"
    changed_task(repo, edited)
    task = task_state(repo)
    assert coverage.changed_existing_tests(str(repo), task) == ["tests/test_app.py::test_long"]


def test_an_untouched_test_file_and_a_brand_new_file_report_no_changes(repo):
    changed_task(repo, BASE_TESTS + "\n\ndef test_new():\n    assert truncate('ab', 1) == 'a…'\n")
    assert coverage.changed_existing_tests(str(repo), task_state(repo)) == []


def test_a_deleted_test_counts_as_changed(repo):
    changed_task(repo, "from app import truncate\n\n\ndef test_short():\n    assert truncate('abc', 5) == 'abc'\n")
    assert coverage.changed_existing_tests(str(repo), task_state(repo)) == ["tests/test_app.py::test_long"]


def test_declared_changes_are_the_reply_blocks_entries_with_a_reason():
    block = {"expected_test_changes": [{"test": "tests/test_app.py::test_long", "why": "the spec says the pinned width is wrong"},
                                       {"test": "tests/test_app.py::test_x"}, {"why": "no test named"}, "junk"]}
    assert coverage.declared_changes(block) == [{"test": "tests/test_app.py::test_long", "why": "the spec says the pinned width is wrong"}]
    assert coverage.declared_changes({}) == [] and coverage.declared_changes(None) == []
