# Rehearsal report: Goal: make `Security(...)` scope inheritance additive per branch — each sub-dependency receives its ancestors' scopes plus its own, and never the scopes of a sibling dependency.

Task `t-20260907-fix-security-scopes-propagation` · branch `rehorse/t-20260907-fix-security-scopes-propagation` · base `c6487ed` · 2026-09-07

Worktree setup: linked .venv from the main checkout

## GREEN: 2564 passed, 0 failed · verifier PASS

## Summary

_Written by the model at report time; everything else in this report is generated from recorded state._

Fixes the reported scope leak: `get_dependant()` in fastapi/dependencies/utils.py inherited the parent's `security_scopes` list *by reference* and then called `.extend()` on it, so each `Security(...)` sibling both mutated its parent's list and started out carrying the previous sibling's scopes. The fix is two copies — `list(security_scopes or [])` for sub-dependencies and `list(security_scopes or use_scopes)` for the `SecurityRequirement` — after which the issue's example gives `security1` exactly `['scope3','scope1']` and `security2` exactly `['scope3','scope2']`. Verified by running the code: 5 new tests fail on the base commit and pass after (issue example, scope ordering, leakage across a plain-`Depends` branch, `Dependant.security_scopes` stability, and the OpenAPI `security` scopes), plus 5 guard tests for paths that were already correct; an independent verifier re-executed the pre-fix module to confirm which assertions genuinely detect the bug and added 6 more tests, 4 of which also fail pre-fix — covering the `dependency_overrides` rebuild path that hands the stored list back into `get_dependant`, a scope-less sibling, non-deduplication of a scope declared twice, and stability across repeated requests and schema generations. Full suite: 2564 passed, 133 skipped, 0 failed; no existing test was modified. One pre-existing, out-of-scope issue the verifier flagged and deliberately did not change or enshrine in a test: `SecurityScopes.__init__` stores `scopes or []` without copying, so user code that mutates `security_scopes.scopes` still mutates the route's recorded list.

## Tests

| stage | passed | failed |
|---|---|---|
| baseline | 2548 | 0 |
| red (tests written, no implementation) | 2553 | 5 |
| green (last run) | 2564 | 0 |

Command: `/private/tmp/rehorse-eval/fastapi-5623/.venv/bin/python -m pytest -q --tb=short -rfE`

Diagnostic runs: 4 (narrowed to selected tests; not counted as baseline, red or green). Last: `/private/tmp/rehorse-eval/fastapi-5623/.venv/bin/python - <<'EOF' 2>&1 | tail -20
import subprocess, sys
WT = "/private/`

5 guard(s) expected to pass; 0 unexpected pass(es) (guards: tests/test_security_scopes_propagation.py::test_nested_scopes_do_not_leak_between_dependencies_list_entries, tests/test_security_scopes_propagation.py::test_router_level_dependencies_list_entries_are_isolated, tests/test_security_scopes_propagation.py::test_scopes_inherited_through_plain_depends_chain, tests/test_security_scopes_propagation.py::test_single_chain_scopes_unchanged, tests/test_security_scopes_propagation.py::test_top_level_sibling_security_params_are_isolated)

Existing tests changed: none — every test in the diff is new.

## Changes (base..HEAD)

```
fastapi/dependencies/utils.py                      |   4 +-
 ...y_t-20260907-fix-security-scopes-propagation.py | 268 +++++++++++++++++++
 tests/test_security_scopes_propagation.py          | 297 +++++++++++++++++++++
 3 files changed, 567 insertions(+), 2 deletions(-)
```

## Verifier: PASS (round 1 of 3)

Its run: 2564 passed, 0 failed. Tests added: 6 in tests/test_rehorse_verify_t-20260907-fix-security-scopes-propagation.py

Verifier file: `tests/test_rehorse_verify_t-20260907-fix-security-scopes-propagation.py` — 6 test(s) collected when run alone.

Findings: none

| acceptance criterion | source | evidence | ref |
|---|---|---|---|
| For the issue's example — `dep3` declared with `Security(security1, scopes=["scope1"])` and `Security(security2, scopes=["scope2"])`, reached through `Security(dep3, scopes=["scope3"])` — the `SecurityScopes.scopes` seen by `security1` is exactly `["scope3", "scope1"]` and the one seen by `security2` is exactly `["scope3", "scope2"]`. Neither sees `scope2`/`scope1` respectively. | issue | test | tests/test_security_scopes_propagation.py::test_sibling_security_dependencies_do_not_leak_scopes (confirmed to fail against the base implementation) |
| The order of scopes is outermost-ancestor-first, then each nested level's own scopes appended in declaration order (i.e. `["scope3", "scope1"]`, not `["scope1", "scope3"]`) — this is the order the issue's expectation states and the order the current code already produces for a single chain. | inferred | test | tests/test_security_scopes_propagation.py::test_scope_order_is_outermost_ancestor_first |
| Scope inheritance still works through more than two levels and through plain `Depends`: a `Security(a, scopes=["s1"])` whose dependency declares `Depends(b)` whose dependency is `Security(c, scopes=["s2"])` gives `c` the scopes `["s1", "s2"]`. | inferred | test | tests/test_security_scopes_propagation.py::test_scopes_through_plain_depends_do_not_leak_to_sibling; the plain-chain guard test passes on the unfixed code, as expected for a non-regression criterion, and tests/test_rehorse_verify_t-20260907-fix-security-scopes-propagation.py::test_sibling_declaring_no_scopes_is_not_polluted_by_a_later_sibling adds a Depends sibling that does fail pre-fix |
| Sibling isolation also holds at the top level: two `Security(...)` parameters on the *path operation function* itself, and two entries in a router/app-level `dependencies=[...]` list, do not contaminate each other. | inferred | test | tests/test_security_scopes_propagation.py::test_top_level_sibling_security_params_are_isolated, ::test_router_level_dependencies_list_entries_are_isolated, ::test_nested_scopes_do_not_leak_between_dependencies_list_entries — all three pass on the unfixed code because `get_parameterless_sub_dependant` already builds a fresh list and top-level `security_scopes` is None; they are correctly marked guards rather than bug-detecting tests |
| A `Dependant`'s recorded `security_scopes` is stable once built: constructing sibling dependencies afterwards does not change a previously built sub-dependant's `security_scopes` list. | inferred | test | tests/test_security_scopes_propagation.py::test_dependant_security_scopes_are_stable_and_not_shared plus tests/test_rehorse_verify_t-20260907-fix-security-scopes-propagation.py::test_recorded_scopes_survive_repeated_schema_generation_and_requests, which extends stability past construction to after requests and schema generation, and ::test_overridden_dependency_rebuild_does_not_accumulate_scopes, which covers the dependency_overrides rebuild at fastapi/dependencies/utils.py:612 that hands the stored list back to get_dependant. Unchanged from the base commit and outside this spec: fastapi/dependencies/utils.py:693 constructs SecurityScopes with the Dependant's own list and SecurityScopes.__init__ (fastapi/security/oauth2.py:657) stores `scopes or []` without copying, so user code that mutates `security_scopes.scopes` still mutates the route's recorded list; no test here enshrines that. |
| The scopes reported in the generated OpenAPI schema (`SecurityRequirement.scopes`, i.e. the `security` entries of each operation) match the scopes actually handed to the scheme, with no sibling leakage. | inferred | test | tests/test_security_scopes_propagation.py::test_openapi_security_scopes_have_no_sibling_leakage plus tests/test_rehorse_verify_t-20260907-fix-security-scopes-propagation.py::test_openapi_keeps_both_scope_sets_of_one_scheme_reached_twice for one scheme reached through two branches |
| No behaviour change for anything else: the existing test suite passes unchanged. No existing test is rewritten — none of them asserts the leaking behaviour as far as this spec is concerned. | inferred | test | full suite run in the worktree: 2564 passed, 133 skipped, 0 failed; git diff confirms no existing test file was modified, and tests/test_security_scopes_propagation.py::test_single_chain_scopes_unchanged guards the single-chain path |

## Test-file drift

none: test files unchanged since the tests phase (`3e2672f`).

## Plan

- [x] 1. Copy inherited scope lists in get_dependant so siblings cannot mutate each other — In `/private/tmp/rehorse-eval/fastapi-5623/.rehorse/worktrees/t-20260907-fix-security-scopes-propagation/fastapi/dependencies/utils.py` I made both inheritance points copy instead of alias the parent list: `use_security_scopes = list(security_scopes or [])` in `get_dependant`'s sub-dependency loop, and `use_scopes = list(security_scopes or use_scopes)` for the `SecurityRequirement`, so `.extend()` no longer mutates an ancestor's or sibling's list and the OpenAPI scopes stop drifting. Full suite passes: 2558 passed, 133 skipped, 0 failed (including `tests/test_security_scopes_propagation.py`); nothing left.

## Try it yourself

```
cd /private/tmp/rehorse-eval/fastapi-5623/.rehorse/worktrees/t-20260907-fix-security-scopes-propagation
/private/tmp/rehorse-eval/fastapi-5623/.venv/bin/python -m pytest -q --tb=short -rfE
# no run command detected (no package.json dev/start, Makefile run target, build.sh, cargo/go/swift project, or README run line)
```

## Next

```
/rehorse:merge t-20260907-fix-security-scopes-propagation      merge rehorse/t-20260907-fix-security-scopes-propagation into your branch and remove the worktree
/rehorse:discard t-20260907-fix-security-scopes-propagation    drop the worktree and the branch
```
