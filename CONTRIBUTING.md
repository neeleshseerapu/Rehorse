# Contributing to Rehorse

Rehorse is small on purpose: git, Python 3's standard library, and Claude Code. There is no build step, no package to
install, and no service to sign up for. If you can run `git` and `python3`, you can work on it.

Read [SPEC.md](SPEC.md) first — it is the source of truth for what Rehorse is and is not — and
[DECISIONS.md](DECISIONS.md) for why the code looks the way it does.

## Development setup

```bash
git clone https://github.com/neeleshseerapu/Rehorse.git && cd Rehorse
python3 -m venv .venv && .venv/bin/pip install pytest      # pytest is the only dependency, and only for the tests
.venv/bin/python -m pytest tests/ -q                       # ~550 tests, about 90 seconds
claude plugin validate .                                   # the plugin and marketplace manifests
claude --plugin-dir .                                      # load your working copy in another project
```

`claude --plugin-dir` takes precedence over an installed `rehorse`, so you do not have to uninstall to test a change.

Two more checks, both slower and both worth running before a pull request that touches hooks or skills:

```bash
bash tests/e2e_live.sh /tmp/rehorse-e2e     # real Claude Code sessions: a full build, a compaction, a verifier round trip
python3 eval/run_eval.py --only rich-4041   # one eval task end to end (needs `gh` logged in; ~5 minutes)
```

`pytest` must be green on every commit. The suite runs hooks against real captured payloads in
`tests/fixtures/hook_inputs/`, so a passing suite means the hook would have behaved that way in a real session.

## Hook rules

Every safety guarantee lives in a hook script, never in a skill's prose. Prose guides; hooks enforce. That gives three
rules. The last two are checked by `tests/test_line_cap.py`; the first is on you:

1. **Test first.** Write the failing pytest for a hook script before the script. We dogfood red-then-green.
2. **Standard library only.** No third-party imports anywhere in `scripts/`. A hook that needs a dependency is a hook a
   user cannot trust to run on their machine.
3. **Under 150 lines**, for every script named in `hooks/hooks.json`. The cap exists so a hook can be read whole before
   it is trusted. Shared logic moves to `scripts/rehorse_lib/` (a plain package, no install) — that is the intended way
   to fit. **Deleting a guarantee to fit the cap is not.**

Phases advance only through `scripts/state.py`. Only `merge.py` and `discard.py` may touch the user's real branch.

## DECISIONS.md

Every non-obvious choice gets a line in `DECISIONS.md`, newest at the bottom, in the form **what was decided** followed
by *why* and the evidence that settled it — the command that was run, the output it printed, the probe that failed.
"It seemed cleaner" is not a reason; "the runner printed `No test files found`" is. If your pull request changes
behaviour anyone could reasonably have expected to work the other way, it needs one of these lines.

`README.md` has hard limits (under 100 lines and 700 words, enforced by `tests/test_readme.py`). Detail belongs in
`SPEC.md`, `DECISIONS.md` or here.

## Running the eval

The eval grades Rehorse by the upstream PR's own tests, never by the tests Rehorse writes. It needs `gh` logged in and
takes roughly 10-25 minutes per task.

```bash
python3 eval/run_eval.py                       # every task in eval/tasks.json without a result yet
python3 eval/run_eval.py --only fastapi-5623   # one task
python3 eval/find_tasks.py Textualize/rich     # find new candidate tasks
```

Results land in `eval/results/<id>.json` and `eval/results.md` is re-rendered from them; each row records the Rehorse
commit it measured. Numbers from a run of your own are welcome in a pull request — say which commit produced them.

## Using AI to contribute

**AI tools are welcome here.** Rehorse is built with them, and pretending otherwise would be strange.

One rule, and it is not negotiable: **every pull request needs a human who can explain every line of it.** If a
reviewer asks why a branch exists, "the model wrote it" is not an answer. Code you cannot defend is code we cannot
maintain, whoever or whatever typed it.

In practice:

- Read what you submit, all of it, before you open the pull request.
- Delete what you did not need. Generated code is generous with helpers nothing calls.
- Test-first still means test-first: a test written after the code, by anything, is a test that was shaped to pass.
- **Rehearsal reports are welcome as verification evidence.** If you built the change with Rehorse, attach the report
  from `rehorse-reports/` — the red-then-green counts, the verifier's verdict and its findings say more about a change
  than a description does. It is evidence, not a substitute for review, and a `concerns` verdict you disagree with is
  worth arguing in the pull request rather than deleting.
- You do not have to disclose which tool you used, and no one will ask. You do have to stand behind the result.
