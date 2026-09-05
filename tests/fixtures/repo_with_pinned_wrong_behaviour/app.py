def truncate(text, width):
    """Cut text to width, marking the cut with an ellipsis.

    The ellipsis is currently written outside the budget, so the result is
    width + 1 cells wide: the bug the spec says to fix.
    """
    if len(text) <= width:
        return text
    return text[:width] + "…"
