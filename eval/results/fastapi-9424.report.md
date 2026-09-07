# Rehearsal report: Goal: a path operation annotated `-> None` must be accepted (and produce the same route, response model and OpenAPI schema) whether or not the module uses `from __future__ import annotations`, so that `@app.post("/", status_code=204)` on an `async def root() -> None:` no longer raises `AssertionError: Status code 204 must not have a response body`.

Task `t-20260907-204-status-with-pep-563-none` · branch `rehorse/t-20260907-204-status-with-pep-563-none` · base `0bdc3ca` · 2026-09-07

Worktree setup: linked .venv from the main checkout

## GREEN: 2378 passed, 0 failed · verifier PASS

## Summary

_Written by the model at report time; everything else in this report is generated from recorded state._

On merge you get a three-line fix in fastapi/dependencies/utils.py: get_typed_return_annotation now collapses an evaluated NoneType back to None, so a path operation annotated '-> None' behaves identically whether or not its module uses 'from __future__ import annotations'. The reported crash is gone — '@app.post("/", status_code=204)' on 'async def root() -> None:' under the future import now declares cleanly and answers 204 with an empty body — and the same normalisation removes a subtler divergence at other status codes, where the future import previously turned '-> None' into a null-typed response schema and a 500 on any real payload. Verified by 16 new tests plus the full 2378-test suite passing: route attributes (response_model/response_field/secure_cloned_response_field) and the generated OpenAPI compared byte-for-byte against a twin module without the future import, at 204 and at 200/201/304; async and sync endpoints; a route declared on an APIRouter and rebuilt by include_router; and guards that the 204 assertion still fires for a real body type, that an explicit response_model still wins, and that 'Optional[Item]' is not swallowed by the normalisation. One behaviour change beyond the PEP 563 case, and it is unavoidable at any fix location because the two are indistinguishable after evaluation: an explicit '-> NoneType' annotation in a module WITHOUT the future import previously produced a null response schema and now produces no response model — the verifier pinned this in a test rather than flagging it, since the spec prescribes normalising the evaluated NoneType. Nothing here was only type-checked or eyeballed; every criterion is backed by an executed test.

## Tests

| stage | passed | failed |
|---|---|---|
| baseline | 2355 | 0 |
| red (tests written, no implementation) | 2362 | 11 |
| green (last run) | 2378 | 0 |

Command: `/private/tmp/rehorse-eval/fastapi-9424/.venv/bin/python -m pytest -q --tb=short -rfE`

Diagnostic runs: 1 (narrowed to selected tests; not counted as baseline, red or green). Last: `/private/tmp/rehorse-eval/fastapi-9424/.venv/bin/python -m pytest -q --tb=short -rfE tests/test_return_annotation_none_p`

**Warning:** no test ids in the runner output; red was judged by counts.

7 guard(s) expected to pass; 0 unexpected pass(es) (guards: tests/test_return_annotation_none_pep563.py::test_204_with_a_real_response_body_still_raises, tests/test_return_annotation_none_pep563.py::test_existing_return_annotation_expectations_are_unchanged, tests/test_return_annotation_none_pep563.py::test_explicit_response_model_none_is_unchanged, tests/test_return_annotation_none_pep563.py::test_explicit_response_model_wins_over_none_return_annotation, tests/test_return_annotation_none_pep563.py::test_no_future_none_204_route_keeps_working (+2 more))

Existing tests changed: none — every test in the diff is new.

## Changes (base..HEAD)

```
fastapi/dependencies/utils.py                      |  10 +-
 tests/return_annotation_none_no_future.py          |  97 +++++++
 ...rify_t-20260907-204-status-with-pep-563-none.py | 152 +++++++++++
 tests/test_return_annotation_none_pep563.py        | 296 +++++++++++++++++++++
 4 files changed, 554 insertions(+), 1 deletion(-)
```

## Verifier: PASS (round 1 of 3)

Its run: 2378 passed, 0 failed. Tests added: 5 in tests/test_rehorse_verify_t-20260907-204-status-with-pep-563-none.py

Verifier file: `tests/test_rehorse_verify_t-20260907-204-status-with-pep-563-none.py` — 5 test(s) collected when run alone.

Findings: none

| acceptance criterion | source | evidence | ref |
|---|---|---|---|
| The example from the issue imports without raising. A module with `from __future__ import annotations` that declares `@app.post("/", status_code=http.HTTPStatus.NO_CONTENT)` on `async def root() -> None:` can be created, and calling that route returns `204` with an empty body. - The same holds for the plain integer form `status_code=204`. | issue | test | tests/test_return_annotation_none_pep563.py::test_pep563_none_204_route_can_be_declared_and_returns_empty_204 (both ids); extended to sync endpoints and to router+include_router by tests/test_rehorse_verify_t-20260907-204-status-with-pep-563-none.py::test_pep563_sync_def_none_204_returns_empty_body and ::test_pep563_none_204_route_declared_on_router_and_included |
| The two documented workarounds are no longer needed: the identical app **without** `from __future__ import annotations` keeps working exactly as it does today (no regression), and the `-> None` return annotation may stay on the route. | issue | test | tests/test_return_annotation_none_pep563.py::test_no_future_none_204_route_keeps_working, plus the unchanged suite (2378 passed, 131 skipped) |
| The normalisation is not specific to 204. For any status code, a route whose return annotation is `None` under `from __future__ import annotations` must produce the same `APIRoute` state as the same route without the future import — specifically `route.response_model is None`, `route.response_field is None` and `route.secure_cloned_response_field is None`. | inferred | test | tests/test_return_annotation_none_pep563.py::test_pep563_none_route_state_matches_no_future_route_state (None/200/201/204/304); the runtime consequence at 200, which that test does not assert, is covered by tests/test_rehorse_verify_t-20260907-204-status-with-pep-563-none.py::test_pep563_none_route_at_200_does_not_filter_the_body |
| The generated OpenAPI schema for a `-> None` route is identical with and without `from __future__ import annotations` (i.e. the future import must not introduce a `null`-typed response schema, and a 204 route must not gain a response body schema). | inferred | test | tests/test_return_annotation_none_pep563.py::test_pep563_none_route_openapi_matches_no_future_openapi (None/200/201/204); the included-router variant is covered by tests/test_rehorse_verify_t-20260907-204-status-with-pep-563-none.py::test_pep563_none_204_route_declared_on_router_and_included |
| A route explicitly given `response_model=None` continues to behave as it does today, and an explicit non-`None` `response_model` still wins over the return annotation — the change must only affect the inferred (`DefaultPlaceholder`) path. | inferred | test | tests/test_return_annotation_none_pep563.py::test_explicit_response_model_none_is_unchanged and ::test_explicit_response_model_wins_over_none_return_annotation |
| Regression guard: the assertion itself is still raised when it should be. A route with `status_code=204` and a real response body type (e.g. `-> Item` or an explicit `response_model=Item`) must still raise `AssertionError` mentioning "Status code 204 must not have a response body", both with and without the future import. | inferred | test | tests/test_return_annotation_none_pep563.py::test_204_with_a_real_response_body_still_raises; the `Union[X, None]` over-normalisation case is added by tests/test_rehorse_verify_t-20260907-204-status-with-pep-563-none.py::test_pep563_optional_model_return_annotation_is_not_normalised_away |
| Other return annotations are unaffected by the change: under `from __future__ import annotations`, a return annotation naming a Pydantic model still yields that model as `response_model` and still filters the response, and a return annotation naming a `Response` subclass still yields `response_model is None` (the `lenient_issubclass(return_annotation, Response)` branch). | inferred | test | tests/test_return_annotation_none_pep563.py::test_pep563_model_return_annotation_still_infers_and_filters and ::test_pep563_response_subclass_return_annotation_still_has_no_response_model; note that a bare `-> NoneType` annotation without the future import does change (null schema and 500 on a non-null payload at the base commit, no response model now), which the spec's Background prescribes when it says to normalise the evaluated `None`/`NoneType` annotation — pinned by tests/test_rehorse_verify_t-20260907-204-status-with-pep-563-none.py::test_bare_nonetype_return_annotation_is_normalised_without_future_import |
| The existing test suite still passes unchanged. No existing test's expectation is wrong under this spec, so no existing test should be rewritten. | inferred | test | full run in the worktree: 2378 passed, 131 skipped, 0 failed; diff touches no existing test file, and tests/test_return_annotation_none_pep563.py::test_existing_return_annotation_expectations_are_unchanged re-asserts the closest existing coverage |

## Test-file drift

none: test files unchanged since the tests phase (`2ce702e`).

## Plan

- [x] 1. Normalise a None/NoneType return annotation so PEP 563 routes match non-PEP-563 routes — In `/private/tmp/rehorse-eval/fastapi-9424/.rehorse/worktrees/t-20260907-204-status-with-pep-563-none/fastapi/dependencies/utils.py`, `get_typed_return_annotation` now returns `None` when the evaluated annotation is `type(None)`, so a PEP 563 `"None"` string annotation collapses to the same value the bare `None` annotation already produces (only caller is `APIRoute.__init__`'s `DefaultPlaceholder` branch, so the explicit-`response_model` path is untouched). Full suite: 2373 passed, 131 skipped, 0 failed; nothing left.

## Try it yourself

```
cd /private/tmp/rehorse-eval/fastapi-9424/.rehorse/worktrees/t-20260907-204-status-with-pep-563-none
/private/tmp/rehorse-eval/fastapi-9424/.venv/bin/python -m pytest -q --tb=short -rfE
# no run command detected (no package.json dev/start, Makefile run target, build.sh, cargo/go/swift project, or README run line)
```

## Next

```
/rehorse:merge t-20260907-204-status-with-pep-563-none      merge rehorse/t-20260907-204-status-with-pep-563-none into your branch and remove the worktree
/rehorse:discard t-20260907-204-status-with-pep-563-none    drop the worktree and the branch
```
