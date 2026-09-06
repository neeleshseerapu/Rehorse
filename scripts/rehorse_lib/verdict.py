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
CONTRADICTS = "CONTRADICTS SPEC:"
TEST_ID = re.compile(r"[\w./\\-]+\.\w+(?:::[\w\[\]./-]*[\w\]])+")  # <path>.<ext>::[<Class>::]<test>, as the runners print it
TITLE_CAP = 180  # a finding's description as a step title; the full text stays in state
SHAPE = ('{"verdict": "pass|concerns|fail", "findings": [{"severity": "high|medium|low", "file": "<path>", "line": 0, '
         '"criterion": "<the acceptance criterion this violates; required for a fail>", '
         '"test": "<file>::<test>", "pins_bug": false, "description": "..."}], '
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
                 "criterion": str(f.get("criterion") or ""), "test": str(f.get("test") or ""),
                 "pins_bug": bool(f.get("pins_bug")) and bool(f.get("test")),  # a claim about a test nobody named cannot be routed
                 "description": str(f.get("description") or "")} for f in v.get("findings") or [] if isinstance(f, dict)]
    coverage = [{"criterion": str(c.get("criterion") or ""), "evidence": c.get("evidence") if c.get("evidence") in EVIDENCE else "none",
                 "ref": str(c.get("ref") or "")} for c in v.get("coverage") or [] if isinstance(c, dict)]
    down = v["verdict"].lower() == "fail" and not any(f["criterion"] for f in findings)  # a fail names the criterion it violates
    return {"verdict": "concerns" if down else v["verdict"].lower(), "downgraded": down, "findings": findings, "coverage": coverage,
            "tests_added": [str(t) for t in v.get("tests_added") or []]}


def contradiction(text):
    """A step reply's `CONTRADICTS SPEC:` line and the test id it names, or None: the step's version of a pins_bug
    finding. The id is read out of the line rather than asked for in a json block, because this is the reply a step
    writes when it has decided it cannot finish, and one more required structure is one more thing to get wrong when
    the model is already off its script. Without an id it is a claim about a test nobody named: routable nowhere, so
    step_done.py stops the task with it, exactly as parse() drops a pins_bug flag that names no test."""
    line = next((l.strip() for l in text.splitlines() if l.strip().startswith(CONTRADICTS)), None)
    if not line:
        return None
    m = TEST_ID.search(line)
    return {"line": line, "test": m.group(0) if m else ""}


def contradiction_round(c, n):
    """The round a step's contradiction buys, in the shape a verifier round is recorded in.

    It goes in verify_history beside the verifier's rounds on purpose: they are the same event -- the task sent back a
    phase because an existing test and the spec disagree -- and keeping one list means one cap counts them, one report
    section shows them, and `progress.py plan` already refuses to drop the steps a round trip earned."""
    return {"round": n, "verdict": "contradicts spec", "from": "implement", "tests": None, "tests_added": [], "coverage": [],
            "findings": [{"severity": "high", "file": c["test"].split("::")[0], "line": None, "criterion": "", "test": c["test"],
                          "pins_bug": True, "description": c["line"]}],
            "revision": [{"test": c["test"], "why": c["line"]}]}


def revisions(v):
    """Findings that say an existing test pins the very behaviour the spec calls a bug, each naming that test.

    The implementer cannot answer one of these. Test paths are locked once the tests phase ends, so the only edit that
    would satisfy the finding is an edit the hooks deny, and the round would come back saying the same thing. The
    round trip therefore goes to `tests`, the one phase whose job is deciding what the tests should say and where a
    rewrite is declared, justified against a criterion and recorded. `pins_bug` counts only with a test id: a claim
    about a test nobody named cannot be routed anywhere (parse() drops the flag), so it stays an ordinary finding."""
    return [f for f in v["findings"] if f["pins_bug"]]


def round_trip_steps(v, run, vfile, n):
    """Plan steps for the implementer: one per high finding (every finding when the verdict is fail and none is high), and one
    to make the verifier's failing tests pass. A pins_bug finding is answered by the tests phase, so it buys no step here."""
    found = [f for f in v["findings"] if f["severity"] == "high"] or (v["findings"] if v["verdict"] == "fail" else [])
    steps = ["Fix (verifier round %d): %s (%s:%s)" % (n, f["description"][:TITLE_CAP] + ("..." if len(f["description"]) > TITLE_CAP else ""),
                                                      f["file"], "?" if f["line"] is None else f["line"])
             for f in found if not f["pins_bug"]]
    if run["failed"]:
        steps.append("Make the verifier's tests pass: %s (%d failing)" % (vfile, run["failed"]))
    return steps
