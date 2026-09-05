from app import truncate


def test_short_text_is_returned_unchanged():
    assert truncate("abc", 5) == "abc"


def test_long_text_is_cut_with_an_ellipsis():
    # Pins the off-by-one: the result is 6 cells for a width of 5. The spec says
    # this expectation is the bug, so the tests phase must change it.
    assert truncate("abcdefgh", 5) == "abcde…"
