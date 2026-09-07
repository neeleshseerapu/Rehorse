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
- **Version.** Rows may come from different Rehorse versions, and each row says which: `rehorse` is the short commit the
  plugin directory was on when the task ran, read at run time and suffixed `-dirty` when the working tree that ran was
  not that commit. A `~` marks a version back-filled from the run's timestamp rather than recorded by the run itself.
- **Environment.** Each task gets a fresh clone and its own venv (`setup_cmd`). For `rich`, `pygments` is pinned to the
  version in the repo's `poetry.lock` (the syntax tests are golden ANSI output that drift with pygments) and `attrs`, a
  dev dependency the tests import, is installed. The machine runs Python 3.13, so tasks are chosen from bases that
  support it (`rich` 14.x, 2025 and later): earlier bases fail at baseline on 3.13-only repr changes, and a baseline
  that is not green would make `self-green` unreachable regardless of Rehorse.

## Results

12 of 13 tasks pass the upstream PR's tests; 12 self-reported green; 0 errored.

Wall time is dominated by verify round-trips, not by the size of the fix: every failing verdict sends the task back to
implement and buys another verifier round, so the number of rounds sets the slowest rows.

| task | rehorse | tier | self-green | rehorse-outcome | upstream-tests-pass | verifier | rounds | wall | turns | report |
|---|---|---|---|---|---|---|---|---|---|---|
| fastapi-13533 | ~15b5eff | 1 | yes | green | **yes** | pass | 2 | 25m29s | 37 | [report](results/fastapi-13533.report.md) |
| fastapi-5623 | ~15b5eff | 1 | yes | green | **yes** | pass | 1 | 11m06s | 20 | [report](results/fastapi-5623.report.md) |
| fastapi-9424 | ~15b5eff | 1 | yes | green | **yes** | pass | 1 | 12m40s | 26 | [report](results/fastapi-9424.report.md) |
| rich-3569 | ~ddfa5b7 | 1 | yes | green | **yes** | concerns | 1 | 10m30s | 23 | [report](results/rich-3569.report.md) |
| rich-3577 | ~7cb16d8 | 1 | yes | green | no | pass | 1 | 15m53s | 42 | [report](results/rich-3577.report.md) |
| rich-3708 | ~ddfa5b7 | 3 | yes | green | **yes** | concerns | 1 | 15m59s | 23 | [report](results/rich-3708.report.md) |
| rich-3727 | ~ddfa5b7 | 2 | yes | green | **yes** | concerns | 1 | 11m39s | 23 | [report](results/rich-3727.report.md) |
| rich-3796 | ~ddfa5b7 | 3 | yes | green | **yes** | concerns | 1 | 9m29s | 22 | [report](results/rich-3796.report.md) |
| rich-3841 | ~ddfa5b7 | 2 | yes | green | **yes** | concerns | 1 | 12m10s | 27 | [report](results/rich-3841.report.md) |
| rich-3871 | ~63d0bdc | 2 | no | needs-attention | **yes** | – | 0 | 9m17s | 17 | [report](results/rich-3871.report.md) |
| rich-3881 | ~ddfa5b7 | 1 | yes | green | **yes** | concerns | 1 | 8m12s | 21 | [report](results/rich-3881.report.md) |
| rich-4038 | ~ddfa5b7 | 2 | yes | green | **yes** | pass | 2 | 22m30s | 30 | [report](results/rich-4038.report.md) |
| rich-4041 | ~ddfa5b7 | 1 | yes | green | **yes** | pass | 1 | 5m02s | 18 | [report](results/rich-4041.report.md) |

17 of the 30 tasks in `eval/tasks.json` have not run yet: the `fastapi`/`zod` batch was stopped after three so that
shipping an installable plugin could come first, and the rest run against the version that ships.
