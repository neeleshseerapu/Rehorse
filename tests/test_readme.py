"""README limits, checked rather than asserted: it is the one file in the repo that grows back.

Under 100 lines and 700 words; no section over 12 lines except Guarantees and the one holding the report excerpt,
which has its own 20-line limit; and Results is one paragraph of at most three sentences pointing at eval/results.md.
That last rule is the one most likely to slip: when fastapi and zod run, the paragraph's numbers change and nothing
else does. A table would grow a column per idea and stop being read."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINES = open(os.path.join(ROOT, "README.md")).read().rstrip("\n").split("\n")
GUARANTEES, EXCERPT_FENCE = "## Guarantees", "```markdown"


def sections():
    """[(heading, body lines)] per `## ` section; headings inside fenced blocks are report content, not sections."""
    starts, fence = [], False
    for i, line in enumerate(LINES):
        if line.startswith("```"):
            fence = not fence
        elif not fence and line.startswith("## "):
            starts.append(i)
    return [(LINES[a], LINES[a:b]) for a, b in zip(starts, starts[1:] + [len(LINES)])]


def trimmed(body):
    while body and not body[-1].strip():
        body = body[:-1]
    return body


def test_the_whole_readme_stays_under_100_lines_and_700_words():
    assert len(LINES) < 100, "%d lines" % len(LINES)
    assert len(" ".join(LINES).split()) < 700, "%d words" % len(" ".join(LINES).split())


def test_no_section_runs_longer_than_twelve_lines():
    """Two exceptions, both deliberate: the guarantees are the reason to trust the thing, and the report excerpt is
    governed by its own limit below."""
    for heading, body in sections():
        if heading == GUARANTEES or any(l.startswith(EXCERPT_FENCE) for l in body):
            continue
        assert len(trimmed(body)) <= 12, "%s is %d lines" % (heading, len(trimmed(body)))


def test_the_report_excerpt_stays_under_twenty_lines():
    start = next(i for i, l in enumerate(LINES) if l.startswith(EXCERPT_FENCE))
    end = next(i for i in range(start + 1, len(LINES)) if LINES[i].startswith("```"))
    assert end - start - 1 < 20, "%d lines of report" % (end - start - 1)


def test_results_is_one_paragraph_of_at_most_three_sentences_linking_the_table():
    body = trimmed(next(b for h, b in sections() if h == "## Results")[1:])
    assert body[0] == "", "a blank line follows the heading"
    paragraphs = "\n".join(body).strip().split("\n\n")
    assert len(paragraphs) == 1, "%d paragraphs" % len(paragraphs)
    text = " ".join(paragraphs[0].split())
    assert len(re.findall(r"[.!?](?:\s|$)", text)) <= 3, text
    assert "](eval/results.md)" in text, "the numbers live in eval/results.md; the README points at them"
    assert "|" not in text and "tier" not in text.lower(), "no table, no methodology, no tiers"
