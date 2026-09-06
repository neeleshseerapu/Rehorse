Make `Text.from_ansi()` preserve trailing line breaks, so the plain text of the result keeps every line break present
in the input (`Text.from_ansi("text\n").plain == "text\n"`) instead of silently dropping the final one.

<!-- rich-3577's own REHORSE_SPEC.md, criteria 1 and 10 verbatim, with the source tag this fixture exists to exercise.
     Criterion 1 is the issue's Expected Output, restated. Criterion 10 is the model's: the issue says nothing about
     tests/test_ansi.py, and the decision that those two existing tests must be rewritten was the spec's own. -->

## Acceptance criteria

1. [issue] A single trailing newline is preserved: `Text.from_ansi("text\n").plain == "text\n"`.
10. [inferred] Two existing tests assert the behaviour this spec calls a bug, and their expectations must be updated
    to include the trailing line break -- nothing else about them changes:
    - `tests/test_ansi.py::test_decode_issue_2688`, case 0: input
      `b"\x1b[31mFound 4 errors in 2 files (checked 18 source files)\x1b(B\x1b[m\n"` ends with `"\n"`, and the
      expected `str(text)` currently omits it. Criterion 1 says it must be `"...source files)\n"`.
    - `tests/test_ansi.py::test_decode_example`: its input ends with `"\n"` and its `expected` captured render
      is one line break short. Criterion 1 says the render now carries that break.
    Both are updates to an *expectation*, not a weakening: the assertion still pins the full decoded string.

## Files likely involved

- `rich/text.py` -- `Text.from_ansi()`: the `decode()` call site where the fix belongs.
