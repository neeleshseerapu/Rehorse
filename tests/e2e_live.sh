#!/bin/bash
# Live end-to-end check of Rehorse with real Claude Code sessions (milestone 4 and 5 acceptance).
#
#   bash tests/e2e_live.sh [output-dir] [runs]      (defaults: /tmp/rehorse-e2e, "1 2 3")
#
# Needs `claude` on PATH. Creates toy repos with their own venv + pytest and runs:
#   run1   full /rehorse:build in a fresh toy repo, then /rehorse:merge typed as the user (new session)
#   run2   a build cut mid-implement by --max-turns, a forced /compact on that session, a resume of the
#          compacted session, and a resume from a fresh session
#   run3   verifier round-trip: a task driven to `verify` with a deliberately weak implementation (the spec's
#          error branch is neither tested nor implemented), then one session that must run the verifier, go back to
#          implement on its findings, verify again, and report
# Everything lands in the output dir: live*/ (toy repos), run*.log (Claude Code debug logs with every
# hook decision), run*.json (result envelopes). Sessions run with permissions bypassed, as the eval will.
set -u
OUT=${1:-/tmp/rehorse-e2e}
RUNS=${2:-"1 2 3"}
P=$(cd "$(dirname "$0")/.." && pwd)
R=$P/scripts
CLAUDE="claude --plugin-dir $P --dangerously-skip-permissions --output-format json"
mkdir -p "$OUT"

mk_toy() {  # fresh toy repo with its own venv + pytest (fix 2: the test command must come from here)
  rm -rf "$1" && mkdir -p "$1/tests" && cd "$1" && git init -q -b main && git config user.email t@example.com && git config user.name toy
  printf 'def add(a, b):\n    return a + b\n' > app.py
  printf 'from app import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n\n\ndef test_add_negative():\n    assert add(-1, 1) == 0\n' > tests/test_app.py
  printf '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n' > pyproject.toml
  printf '.venv/\n__pycache__/\n' > .gitignore
  git add -A && git commit -q -m init && python3 -m venv .venv && .venv/bin/pip install -q pytest 2>/dev/null
}
sid() { python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('session_id',''))" "$1"; }
result() { python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print('turns', d.get('num_turns'), 'ms', d.get('duration_ms')); print(d.get('result','')[:1500])" "$1"; }
phase() { python3 "$R/state.py" show | python3 -c "import json,sys; t=json.load(sys.stdin); print('phase', t.get('phase'), 'step', t.get('step'), 'plan', [p['done'] for p in t.get('plan',[])]) if 'phase' in t else print('no active task')"; }
hooks() { grep -E "Hook (PreToolUse|Stop|SubagentStop|UserPromptSubmit|PreCompact|SessionStart|PostToolUse)" "$1" | sed -E 's/^.*Hook /Hook /' | cut -c1-260; }

hook() { python3 - "$@" <<'PY'
import json, sys
event, cwd = sys.argv[1], sys.argv[2]
d = {"session_id": "drive", "transcript_path": "/dev/null", "cwd": cwd, "hook_event_name": event, "permission_mode": "default"}
for kv in sys.argv[3:]:
    k, v = kv.split("=", 1)
    d[k] = open(v[1:]).read() if v[:1] == "@" else json.loads(v) if v[:1] in "{[\"" else v
print(json.dumps(d))
PY
}
run_tests() { local out; out=$(cd "$WT" && $CMD 2>&1); local ev=PostToolUse; local field=tool_response; local val
  if echo "$out" | tail -1 | grep -q failed; then ev=PostToolUseFailure; fi
  val=$(python3 -c 'import json,sys; print(json.dumps({"stdout": sys.argv[1], "stderr": ""}))' "$out")
  if [ $ev = PostToolUseFailure ]; then field=error; val=$(python3 -c 'import json,sys; print(json.dumps("Exit code 1\n"+sys.argv[1]))' "$out"); fi
  hook $ev "$WT" tool_name=Bash "tool_input={\"command\": \"cd $WT && $CMD\"}" "$field=$val" | python3 "$R/on_bash_done.py"; echo; }
new_task() {  # state.py new "<title>" in the current toy repo; sets ID, CMD, WT
  local task; task=$(python3 "$R/state.py" new "$1")
  ID=$(echo "$task" | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
  CMD=$(echo "$task" | python3 -c "import json,sys; print(json.load(sys.stdin)['test_cmd'])")
  WT=$PWD/.rehorse/worktrees/$ID
}

run1() {
echo "=== RUN 1: full /rehorse:build in a fresh toy repo ==="
mk_toy "$OUT/live1"; cd "$OUT/live1"
$CLAUDE --debug-file "$OUT/run1.log" -p '/rehorse:build "add a subtract function sub(a, b) to app.py, returning a - b"' > "$OUT/run1.json" 2> "$OUT/run1.err"
echo "exit $?"; result "$OUT/run1.json"; phase
echo "--- hook lines (run1):"; hooks "$OUT/run1.log" | grep -v SessionStart | head -40
echo "--- report:"; cat rehorse-reports/2026-*.md 2>/dev/null | head -60
echo "--- rehearsal branch log:"; git -C .rehorse/worktrees/t-* log --oneline 2>/dev/null

echo; echo "=== RUN 1b: /rehorse:merge typed by the user (new session) ==="
$CLAUDE --debug-file "$OUT/run1b.log" -p '/rehorse:merge' > "$OUT/run1b.json" 2> "$OUT/run1b.err"
echo "exit $?"; result "$OUT/run1b.json"; git log --oneline | head -5; git status --short; hooks "$OUT/run1b.log" | grep UserPromptSubmit | head -3

}

run2() {
echo; echo "=== RUN 2: compaction mid-implement, then resume in the same and in a fresh session ==="
# Drive the task to implement with a two-step plan without a model (real hook JSON piped through the scripts), so the
# --max-turns cut below lands deterministically after step 1: show state, render progress, spawn step 1, and stop.
mk_toy "$OUT/live2"; cd "$OUT/live2"
new_task "add sub and mul"
printf 'Add sub(a, b) returning a - b and mul(a, b) returning a * b to app.py.\n\n## Acceptance criteria\n1. sub(5, 3) == 2\n2. mul(2, 3) == 6\n' > "$WT/REHORSE_SPEC.md"
run_tests                                             # baseline
python3 "$R/state.py" advance tests
printf 'import app\n\n\ndef test_sub():\n    assert app.sub(5, 3) == 2\n\n\ndef test_mul():\n    assert app.mul(2, 3) == 6\n' > "$WT/tests/test_new.py"
run_tests                                             # red_check
(cd "$WT" && git add -A && git commit -q -m "tests: red for $ID")
printf 'Added tests/test_new.py.\nBoth fail.\n```json\n{"coverage": [{"criterion": 1, "ref": "tests/test_new.py::test_sub"}, {"criterion": 2, "ref": "tests/test_new.py::test_mul"}]}\n```\n' > "$OUT/live2-reply.txt"
hook SubagentStop "$WT" agent_type=rehorse:rehorse-step agent_id=drive "last_assistant_message=@$OUT/live2-reply.txt" | python3 "$R/step_done.py"; echo
python3 "$R/state.py" advance implement
python3 "$R/progress.py" plan "add sub(a, b) to app.py" "add mul(a, b) to app.py"
echo "--- driven to:"; phase
$CLAUDE --debug-file "$OUT/run2a.log" --max-turns 3 -p '/rehorse:build' > "$OUT/run2a.json" 2> "$OUT/run2a.err"
echo "exit $? (a max-turns cut after step 1 is the goal)"; result "$OUT/run2a.json"; phase
SID=$(sid "$OUT/run2a.json"); echo "session $SID"
echo "--- forcing /compact on that session:"
$CLAUDE --debug-file "$OUT/run2b.log" --resume "$SID" -p '/compact' > "$OUT/run2b.json" 2> "$OUT/run2b.err"; echo "exit $?"
hooks "$OUT/run2b.log" | grep -E "PreCompact|SessionStart" | head -5; echo "--- handoff.json:"; head -30 .rehorse/handoff.json 2>/dev/null
echo "--- resuming the compacted session:"
$CLAUDE --debug-file "$OUT/run2c.log" --resume "$SID" -p 'What is the active Rehorse task, its phase and next action? Then continue it with /rehorse:build' > "$OUT/run2c.json" 2> "$OUT/run2c.err"
echo "exit $?"; result "$OUT/run2c.json"; phase
echo "--- fresh session resume:"
$CLAUDE --debug-file "$OUT/run2d.log" -p '/rehorse:build' > "$OUT/run2d.json" 2> "$OUT/run2d.err"
echo "exit $?"; result "$OUT/run2d.json"; phase
echo "--- PROGRESS.md:"; cat rehorse-reports/PROGRESS.md
echo "--- report:"; cat rehorse-reports/2026-*.md 2>/dev/null | head -60
}

run3() {
echo; echo "=== RUN 3: verifier round-trip on a deliberately weak implementation ==="
# Driven to `verify` without a model: the spec has an error branch (divide by zero -> ValueError), the tests-phase
# tests cover only the happy path, and the implementation has no such branch. The verifier must catch it.
mk_toy "$OUT/live3"; cd "$OUT/live3"
new_task "add divide"
printf 'Add divide(a, b) to app.py, returning a / b.\n\n## Acceptance criteria\n1. divide(6, 3) == 2\n2. divide(1, 0) raises ValueError with the message "division by zero"\n\n## Files likely involved\n- app.py\n' > "$WT/REHORSE_SPEC.md"
run_tests                                             # baseline
python3 "$R/state.py" advance tests
printf 'import app\n\n\ndef test_divide():\n    assert app.divide(6, 3) == 2\n' > "$WT/tests/test_divide.py"   # happy path only, on purpose
run_tests                                             # red
(cd "$WT" && git add -A && git commit -q -m "tests: red for $ID")
# The coverage gate checks that each mapped ref is a real test in a new test file, not what the test asserts; an
# implementer that maps criterion 2 to the happy-path test passes it. Catching that is the verifier's job (below).
printf 'Added tests/test_divide.py.\nIt fails: no divide.\n```json\n{"coverage": [{"criterion": 1, "ref": "tests/test_divide.py::test_divide"}, {"criterion": 2, "ref": "tests/test_divide.py::test_divide"}]}\n```\n' > "$OUT/live3-reply.txt"
hook SubagentStop "$WT" agent_type=rehorse:rehorse-step agent_id=drive "last_assistant_message=@$OUT/live3-reply.txt" | python3 "$R/step_done.py"; echo
python3 "$R/state.py" advance implement
python3 "$R/progress.py" plan "add divide(a, b) to app.py"
printf 'def add(a, b):\n    return a + b\n\n\ndef divide(a, b):\n    return a / b\n' > "$WT/app.py"   # weak: no ValueError branch
hook PreToolUse "$WT" tool_name=Edit "tool_input={\"file_path\": \"$WT/app.py\"}" agent_id=drive | python3 "$R/guard_edit.py"
run_tests                                             # green against the weak tests
(cd "$WT" && git add -A && git commit -q -m "step 1: add divide(a, b) to app.py")
hook SubagentStop "$WT" agent_type=rehorse:rehorse-step agent_id=drive "last_assistant_message=\"Added divide(a, b) to app.py.\\nTests: 3 passed, 0 failed; nothing left.\"" | python3 "$R/step_done.py"; echo
python3 "$R/state.py" advance verify
echo "--- driven to:"; phase
$CLAUDE --debug-file "$OUT/run3.log" --max-turns 80 -p '/rehorse:build' > "$OUT/run3.json" 2> "$OUT/run3.err"
echo "exit $?"; result "$OUT/run3.json"; phase
echo "--- hook lines (run3):"; hooks "$OUT/run3.log" | grep -v SessionStart | head -60
echo "--- verifier state:"; python3 "$R/state.py" show | python3 -c "import json,sys; t=json.load(sys.stdin); print(json.dumps({k: t.get(k) for k in ('phase','verify_round','verifier','verify_history','plan')}, indent=1))"
echo "--- PROGRESS.md:"; cat rehorse-reports/PROGRESS.md
echo "--- report:"; cat rehorse-reports/2026-*.md 2>/dev/null
echo "--- rehearsal branch log:"; git -C "$WT" log --oneline
}

for r in $RUNS; do "run$r"; done
echo "DONE. Logs: $OUT/run*.log  results: $OUT/run*.json"
