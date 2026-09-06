#!/usr/bin/env python3
"""What a verifier verdict is: its shape, how a reply is parsed into one, and the plan steps a failing one buys.

Kept apart from verify.py, which is the SubagentStop hook that records it (and stays under the hook line cap).
Nothing here touches state or git; it is text in, dicts out, so the round-trip rules can be read in one place.
"""
import json
import re

VERDICTS = ("pass", "concerns", "fail")
EVIDENCE = ("test", "build_only", "none")
MAX_ROUNDS = 3
TITLE_CAP = 180  # a finding's description as a step title; the full text stays in state
SHAPE = ('{"verdict": "pass|concerns|fail", "findings": [{"severity": "high|medium|low", "file": "<path>", "line": 0, '
         '"criterion": "<the acceptance criterion this violates; required for a fail>", "description": "..."}], '
         '"tests_added": ["<file>::<test>"], "coverage": [{"criterion": "<acceptance criterion>", '
         '"evidence": "test|build_only|none", "ref": "<test id or file>"}]}')


def parse(text):
    """The last ```json block (else the outermost {...}) as a verdict, fields normalised; None when absent or not pass|concerns|fail."""
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S) or [text[text.find("{"):text.rfind("}") + 1]]
    try:
        v = json.loads(blocks[-1])
    except ValueError:
        return None
    if not isinstance(v, dict) or str(v.get("verdict", "")).lower() not in VERDICTS:
        return None
    findings = [{"severity": str(f.get("severity") or "medium").lower(), "file": str(f.get("file") or ""), "line": f.get("line"),
                 "criterion": str(f.get("criterion") or ""), "description": str(f.get("description") or "")} for f in v.get("findings") or []
                if isinstance(f, dict)]
    coverage = [{"criterion": str(c.get("criterion") or ""), "evidence": c.get("evidence") if c.get("evidence") in EVIDENCE else "none",
                 "ref": str(c.get("ref") or "")} for c in v.get("coverage") or [] if isinstance(c, dict)]
    down = v["verdict"].lower() == "fail" and not any(f["criterion"] for f in findings)  # a fail names the criterion it violates
    return {"verdict": "concerns" if down else v["verdict"].lower(), "downgraded": down, "findings": findings, "coverage": coverage,
            "tests_added": [str(t) for t in v.get("tests_added") or []]}


def round_trip_steps(v, run, vfile, n):
    """Plan steps for the implementer: one per high finding (every finding when the verdict is fail and none is high), and one
    to make the verifier's failing tests pass."""
    found = [f for f in v["findings"] if f["severity"] == "high"] or (v["findings"] if v["verdict"] == "fail" else [])
    steps = ["Fix (verifier round %d): %s (%s:%s)" % (n, f["description"][:TITLE_CAP] + ("..." if len(f["description"]) > TITLE_CAP else ""),
                                                      f["file"], "?" if f["line"] is None else f["line"]) for f in found]
    if run["failed"]:
        steps.append("Make the verifier's tests pass: %s (%d failing)" % (vfile, run["failed"]))
    return steps
