#!/usr/bin/env python3
"""Acceptance-criteria coverage for the tests phase: before tests -> implement, every criterion under
`## Acceptance criteria` in REHORSE_SPEC.md must map to a test in a test file the tests phase added or changed.

The mapping comes from the tests-phase agent's reply, a ```json block {"coverage": [{"criterion": <number or text>,
"ref": "<file>::<test>"}]} (the verifier's coverage shape), recorded by step_done.py as task["coverage"]. This module
checks the mapping against the files: the ref must name a new or changed test file and a test that exists in it. It
cannot judge whether that test really exercises the criterion; that is the verifier's job. Not a hook (no line cap).
CLI: coverage.py check   -> {"uncovered": [...]} for the active task; exit 1 when anything is uncovered
"""
import json
import os
import re
import sys

import state
import testcmd
import worktree

HEADING_RE = re.compile(r"^#+\s*acceptance criteria\s*$", re.I)
ITEM_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.+?)\s*$")
BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)
NO_SECTION = "REHORSE_SPEC.md has no '## Acceptance criteria' section (numbered, each testable); write it before the tests"


def criteria(text):
    """The items under '## Acceptance criteria' (numbered or bulleted), or None when the section is missing."""
    items, inside, seen = [], False, False
    for line in text.splitlines():
        if line.startswith("#"):
            inside = bool(HEADING_RE.match(line.strip()))
            seen = seen or inside
            continue
        m = inside and ITEM_RE.match(line)
        if m:
            items.append(m.group(1))
    return items if seen else None


def json_block(text):
    """The last ```json block of a reply as a dict, or None."""
    blocks = BLOCK_RE.findall(text or "")
    try:
        v = json.loads(blocks[-1]) if blocks else None
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def entries(block):
    """Normalised [{criterion, ref}] from a reply's block, or None when it has no coverage list."""
    if not block or not isinstance(block.get("coverage"), list):
        return None
    return [{"criterion": str(c.get("criterion", "")).strip(), "ref": str(c.get("ref", "")).strip()}
            for c in block["coverage"] if isinstance(c, dict)]


def normalize(s):
    return re.sub(r"\s+", " ", re.sub(r"^\s*\d+[.)]\s*", "", str(s))).strip().lower()


def matches(n, criterion, entry):
    """Does a mapping entry's criterion name criterion number n: by its number, or by (normalised) text."""
    e = str(entry or "").strip()
    m = re.match(r"^(\d+)[.)]?(?:\s|$)", e)
    if m:
        return int(m.group(1)) == n
    ne, nc = normalize(e), normalize(criterion)
    return bool(ne) and (ne == nc or (len(ne) >= 12 and (ne in nc or nc in ne)))


def uncovered(root, task):
    """Criteria with no verified test, as '<n>. <criterion>: <why>' lines. Empty means the gate is satisfied."""
    wt = os.path.realpath(os.path.join(root, task["worktree"]))
    try:
        crits = criteria(open(os.path.join(wt, "REHORSE_SPEC.md")).read())
    except OSError:
        crits = None
    if crits is None:
        return [NO_SECTION]
    changed = set(worktree.git(wt, "diff", "--name-only", task["base_sha"] + "..HEAD").split()) if task.get("base_sha") else set()
    tests = {f for f in changed | set(worktree.dirty(root, task["id"])) if testcmd.is_test_path(f, task.get("test_paths") or [])}
    out = []
    for n, c in enumerate(crits, 1):
        why = "no test mapped"
        for e in [e for e in task.get("coverage") or [] if matches(n, c, e.get("criterion"))]:
            f, _, name = e.get("ref", "").partition("::")
            if f not in tests:
                why = "%s is not a new or changed test file" % (f or "(empty ref)")
            elif not name:
                why = "ref %s names a file but no test" % f
            elif not re.search(r"\b%s\b" % re.escape(name), open(os.path.join(wt, f), errors="ignore").read()):
                why = "%s not found in %s" % (name, f)
            else:
                why = None
                break
        if why:
            out.append("%d. %s: %s" % (n, c, why))
    return out


def main(argv):
    root, _, task = state.active(os.getcwd())
    if not task or argv[:1] != ["check"]:
        sys.exit("coverage.py: no active task" if not task else __doc__)
    un = uncovered(root, task)
    json.dump({"uncovered": un}, sys.stdout)
    return 1 if un else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
