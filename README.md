<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg"><img src="assets/logo.svg" alt="Rehorse" width="160" height="160"></picture></p>
<h1 align="center">Rehorse</h1>
<p align="center">Auto mode for Claude Code that you can walk away from.</p>

Type one command, leave, come back to a report. Every task rehearses on its own git worktree, must go red-then-green
on your tests, and is checked by an independent verifier. Nothing touches your branch until you type `/rehorse:merge`.

The rules are **hooks** — Python scripts Claude Code runs on every tool call — not prose, so they hold
with permissions bypassed.

## Install

Claude Code, git, Python 3, and a suite Rehorse can run (pytest, vitest, jest, cargo, go, swift, make);
red-then-green needs something to go red.

```bash
claude plugin marketplace add neeleshseerapu/Rehorse
claude plugin install rehorse
```

`/rehorse:status` in your project says there is no active task. From a clone: `claude --plugin-dir ~/Rehorse`.

## Use it

```
/rehorse:build "add a --json flag to the export command"
```

Walk away. You come back to `rehorse-reports/<date>-<slug>.md`, then run `/rehorse:merge` or `/rehorse:discard` —
only you can: the grant is minted when *you* type it.

## The report

```markdown
# Rehearsal report: Add divide(a, b) to app.py, returning a / b.
## GREEN: 28 passed, 0 failed · verifier PASS
| stage    | passed | failed |
| baseline | 2      | 0      |
| red      | 2      | 1      |
| green    | 28     | 0      |

## Verifier: PASS (round 2 of 3)
Round 1: FAIL — [high] app.py:6 divide(1, 0) raises ZeroDivisionError, not a ValueError: criterion 2 unmet.

## Test-file drift
none: test files unchanged since the tests phase (`e51ad94`).
```

## What happens

**spec** — a worktree from your HEAD on its own branch, the test command detected, a spec, a baseline run.
**tests** — a fresh subagent writes failing tests, test files only. **implement** — 1 to 6 steps, each a fresh subagent
that edits implementation files only, runs the tests and commits; the orchestrator reads two-line summaries, never
source. **verify** — a subagent that never saw how the code was built, given only the spec, the diff and the last
test output. **report** — written, committed, session ends. A stuck task stops at `needs-attention`; the hook
that stopped it writes the report.

## Guarantees

While a task is active, in any permission mode:

- **Isolation.** Edits outside the worktree are denied, shell writes (`>>`, `tee`, `sed -i`) included.
- **Tests are locked while it implements.** Only the tests phase may touch them, and it may rewrite an existing test
  only where the spec calls the behaviour it pins wrong, citing the criterion; other drift is flagged.
- **Red before green, by test id.** A run counts only inside the worktree, over the whole suite, with the runner's own
  summary line; a narrowed run is a diagnostic, and failures the baseline had are not red.
- **Verified by someone else.** The verifier's stop is held until it ran the tests, committed and
  returned a verdict; no report renders without one. The turn cannot end with untested edits, and only
  `/rehorse:merge` or `/rehorse:discard`, typed by you, touches your branch.

Every denial says what is allowed instead. Hooks stop shortcuts, not an adversarial model: an accident cannot merge, only intent can.

## Results

Nine of ten `rich` issues pass, graded by each upstream PR's own tests, never Rehorse's, and the first three
`fastapi` issues pass too; 17 of 30 tasks are still to run. `rich-3871`, the run that stopped itself, refused to
rewrite a snapshot test pinning the bug; its diff passes upstream anyway. Every row, with the version it
measured: [eval/results.md](eval/results.md).

## Status

`v0.2.0-alpha`. Milestones 1–6 and the listing are done and live-checked. Next: the rest of the `fastapi` and `zod`
eval, on the version you install. `main` is kept green.

## Contributing

`SPEC.md` is the spec; `DECISIONS.md` every decision with its evidence.

```bash
.venv/bin/python -m pytest tests/ -q       # real hook payloads
bash tests/e2e_live.sh /tmp/rehorse-e2e    # real sessions
```

Hook scripts are test-first, stdlib only, and each one Claude Code invokes stays under 150 lines, so you can read
what enforces a guarantee before trusting it. Run it on a real repo and open an issue with the report.

## License

MIT. See [LICENSE](LICENSE).
