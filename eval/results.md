# Eval results

## Methodology

- **Tasks** are closed GitHub issues whose merged PR touched 1-5 files, at least one of them a test file and at least
  one not (`eval/find_tasks.py`). `base_sha` is the merge commit's first parent: the base branch the moment before the
  fix landed, for true merges and squashes alike. Rehorse sees only the issue title and body.
- **Grade.** The PR's test files are taken from the PR's *merge commit* (what landed on the base branch), never from
  the PR head, whose branch can predate the base. They are checked out whole into the rehearsal worktree, replacing
  Rehorse's edits to the same files, and run with the task's test command; `upstream-tests-pass` is that run green.
  Rehorse's own tests therefore never count toward the grade; `self-green` is only Rehorse's self-report (phase
  `report` reached with 0 failed), and `rehorse-outcome` is the phase it stopped in. `verifier` is its verdict and how
  many rounds it took.
- **Environment.** Each task gets a fresh clone and its own venv (`setup_cmd`). For `rich`, `pygments` is pinned to the
  version in the repo's `poetry.lock` (the syntax tests are golden ANSI output that drift with pygments) and `attrs`, a
  dev dependency the tests import, is installed. The machine runs Python 3.13, so tasks are chosen from bases that
  support it (`rich` 14.x, 2025 and later): earlier bases fail at baseline on 3.13-only repr changes, and a baseline
  that is not green would make `self-green` unreachable regardless of Rehorse.

## Results

9 of 10 tasks pass the upstream PR's tests; 8 self-reported green; 0 errored.

Wall time is dominated by verify round-trips, not by the size of the fix: every failing verdict sends the task back to
implement and buys another verifier round, so the number of rounds sets the slowest rows.

| task | tier | self-green | rehorse-outcome | upstream-tests-pass | verifier | rounds | wall | turns | report |
|---|---|---|---|---|---|---|---|---|---|
| rich-3569 | 1 | yes | green | **yes** | concerns | 1 | 10m30s | 23 | [report](results/rich-3569.report.md) |
| rich-3577 | 1 | no | needs-attention | no | – | 1 | 11m25s | 36 | [report](results/rich-3577.report.md) |
| rich-3708 | 3 | yes | green | **yes** | concerns | 1 | 15m59s | 23 | [report](results/rich-3708.report.md) |
| rich-3727 | 2 | yes | green | **yes** | concerns | 1 | 11m39s | 23 | [report](results/rich-3727.report.md) |
| rich-3796 | 3 | yes | green | **yes** | concerns | 1 | 9m29s | 22 | [report](results/rich-3796.report.md) |
| rich-3841 | 2 | yes | green | **yes** | concerns | 1 | 12m10s | 27 | [report](results/rich-3841.report.md) |
| rich-3871 | 2 | no | needs-attention | **yes** | fail | 3 | 34m23s | 35 | [report](results/rich-3871.report.md) |
| rich-3881 | 1 | yes | green | **yes** | concerns | 1 | 8m12s | 21 | [report](results/rich-3881.report.md) |
| rich-4038 | 2 | yes | green | **yes** | pass | 2 | 22m30s | 30 | [report](results/rich-4038.report.md) |
| rich-4041 | 1 | yes | green | **yes** | pass | 1 | 5m02s | 18 | [report](results/rich-4041.report.md) |
