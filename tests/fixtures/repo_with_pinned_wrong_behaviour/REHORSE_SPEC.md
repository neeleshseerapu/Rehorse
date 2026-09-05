truncate() must never return more cells than the width it was given.

## Acceptance criteria
1. `truncate("abcdefgh", 5)` returns `"abcd…"`: five cells, the ellipsis inside the budget.
2. `truncate("abc", 5)` still returns `"abc"` unchanged.

## Assumptions
- `tests/test_app.py::test_long_text_is_cut_with_an_ellipsis` pins the old, wrong width
  (`"abcde…"`, six cells). The spec says that expectation is the bug, so the tests phase
  updates that assertion rather than leaving it to contradict criterion 1.
