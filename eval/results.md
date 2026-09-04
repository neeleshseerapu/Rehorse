# Eval results

## Methodology

- **Tasks** are closed GitHub issues whose merged PR touched 1-5 files, at least one of them a test file and at least
  one not (`eval/find_tasks.py`). `base_sha` is the merge commit's first parent: the base branch the moment before the
  fix landed, for true merges and squashes alike. Rehorse sees only the issue title and body.
- **Grade.** The PR's test files are taken from the PR's *merge commit* (what landed on the base branch), never from
  the PR head, whose branch can predate the base. They are checked out whole into the rehearsal worktree, replacing
  Rehorse's edits to the same files, and run with the task's test command; `upstream-tests-pass` is that run green.
  Rehorse's own tests therefore never count toward the grade; `merged-green` is only Rehorse's self-report (phase
  `report` reached with 0 failed). `verifier` is its verdict and how many rounds it took.
- **Environment.** Each task gets a fresh clone and its own venv (`setup_cmd`). For `rich`, `pygments` is pinned to the
  version in the repo's `poetry.lock` (the syntax tests are golden ANSI output that drift with pygments) and `attrs`, a
  dev dependency the tests import, is installed. The machine runs Python 3.13, so tasks are chosen from bases that
  support it (`rich` 14.x, 2025 and later): earlier bases fail at baseline on 3.13-only repr changes, and a baseline
  that is not green would make `merged-green` unreachable regardless of Rehorse.

## Results

| task | tier | merged-green | upstream-tests-pass | verifier | rounds | wall | turns | report |
|---|---|---|---|---|---|---|---|---|
| rich-3881 | 1 | yes | **yes** | pass | 1 | 5m46s | 20 | [report](results/rich-3881.report.md) |

1 of 1 tasks pass the upstream PR's tests; 1 self-reported green; 0 errored.
