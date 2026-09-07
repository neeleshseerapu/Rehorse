# Rehearsal report: Empty form fields must fall back to the declared parameter's default (e.g. `None`) instead of being validated as the empty string, for both `application/x-www-form-urlencoded` and `multipart/form-data` bodies.

Task `t-20260907-form-default-value-regressions` · branch `rehorse/t-20260907-form-default-value-regressions` · base `c337320` · 2026-09-07

Worktree setup: linked .venv from the main checkout

## GREEN: 2579 passed, 0 failed · verifier PASS

## Summary

_Written by the model at report time; everything else in this report is generated from recorded state._

On merge you get a one-line-of-logic fix in `_extract_form_body()` (fastapi/dependencies/utils.py): the raw-body passthrough loop added by PR #12134 now skips keys that belong to a declared body field, instead of blindly re-adding every form key. That loop was resurrecting the empty string for fields whose empty value `_get_multidict_value()` had deliberately dropped, so `name=` yielded `""` instead of the declared default. Both MREs from the issue were reproduced on this checkout before the change and are now pinned by tests: the x-www-form-urlencoded case returns `None`, and the multipart case returns `None` for `name` both with and without a real file part. Contrary to the issue, there is only one root cause left here: the second regression it names (PR #12117 dropping the multipart empty check) was already repaired upstream — `_get_multidict_value()` now consults each field's own `field_info` rather than only the first field's — which I confirmed by patching out only the #12134 loop and watching both MREs pass. A required Form field sent empty still returns 422 `missing` rather than being silently defaulted, which is a behaviour change from the buggy state and is intentional. Everything is verified by executed tests, not inspection: 2579 pass, 133 skip, zero failures, with 16 new tests plus 8 from the independent verifier, and no pre-existing test was modified. The verifier's first round caught a real regression in my own spec's reasoning — I had assumed field names as well as aliases belonged in the suppression set, copying `request_params_to_args()`, but `_extract_form_body()` reads the body only by alias, so suppressing names broke `extra=\"forbid\"` rejection for aliased model fields and broke `populate_by_name=True` models posted by field name; both were fixed to alias-only and are now pinned by tests. Two things to know before merging: empty *file* parts (empty filename, empty content) still yield `b""` rather than the field default — that matches 0.112.4 and was left alone as out of scope; and for a single non-embedded form *model*, the model's own fields carry a plain Pydantic FieldInfo rather than `params.Form`, so the empty-string-means-default rule does not reach them — also unchanged from before, but it means the fix applies to parameter-level Form/File fields.

## Tests

| stage | passed | failed |
|---|---|---|
| baseline | 2555 | 0 |
| red (tests written, no implementation) | 2564 | 7 |
| green (last run) | 2579 | 0 |

Command: `/private/tmp/rehorse-eval/fastapi-13533/.venv/bin/python -m pytest -q --tb=short -rfE`

Diagnostic runs: 5 (narrowed to selected tests; not counted as baseline, red or green). Last: `/private/tmp/rehorse-eval/fastapi-13533/.venv/bin/python -m pytest -q --tb=short -rfE "tests/test_rehorse_verify_t-20260`

9 guard(s) expected to pass; 0 unexpected pass(es) (guards: tests/test_form_empty_value_defaults.py::test_aliased_form_field_sent_empty_uses_non_none_default, tests/test_form_empty_value_defaults.py::test_empty_value_uses_non_none_default, tests/test_form_empty_value_defaults.py::test_existing_single_model_form_behaviour_unchanged, tests/test_form_empty_value_defaults.py::test_model_extra_allow_still_collects_unknown_key, tests/test_form_empty_value_defaults.py::test_model_extra_forbid_still_rejects_unknown_key (+4 more))

Existing tests changed: none — every test in the diff is new.

## Changes (base..HEAD)

```
fastapi/dependencies/utils.py                      |  10 +-
 tests/test_form_empty_value_defaults.py            | 288 +++++++++++++++++++++
 ...fy_t-20260907-form-default-value-regressions.py | 225 ++++++++++++++++
 3 files changed, 522 insertions(+), 1 deletion(-)
```

## Verifier: PASS (round 2 of 3)

Its run: 2579 passed, 0 failed. Tests added: 8 in tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py

Verifier file: `tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py` — 8 test(s) collected when run alone.

Findings: none

| acceptance criterion | source | evidence | ref |
|---|---|---|---|
| A `POST` of `application/x-www-form-urlencoded` body `name=` to an endpoint declaring `name: Annotated[Optional[str], Form(embed=True)] = None` returns `200` and the parameter is `None`, not `""`. | – | test | tests/test_form_empty_value_defaults.py::test_urlencoded_empty_value_uses_none_default |
| A `POST` of a `multipart/form-data` body containing an empty `name` part to an endpoint declaring `file: Annotated[Optional[bytes], File()] = None` and `name: Annotated[Optional[str], Form(embed=True)] = None` returns `200`, `name` is `None`, and `file` is `None`. The same holds when a real file part *is* present: `name` is `None` and `file` is the uploaded bytes. | – | test | tests/test_form_empty_value_defaults.py::test_multipart_empty_value_uses_none_default, ::test_multipart_empty_value_with_real_file_uses_none_default, tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py::test_optional_uploadfile_empty_multipart_part_uses_default |
| `_extract_form_body()` must no longer re-add a value from the raw form body for a key that belongs to a declared body field. Only keys that match no declared field are passed through. | – | test | tests/test_form_empty_value_defaults.py::test_extract_form_body_does_not_readd_declared_field_keys, ::test_extract_form_body_does_not_readd_alias_keys |
| The default is honoured whatever it is, not just `None`: an empty value for `Annotated[str, Form()] = "fallback"` yields `"fallback"`. | – | test | tests/test_form_empty_value_defaults.py::test_empty_value_uses_non_none_default (guard: also passes at the base commit, since a non-None default was already stored in `values` and the old loop skipped keys already present) |
| A **required** `Form` field sent empty (`name=`) still produces a `422` with a `missing` error at `loc == ["body", "name"]` — the empty string must not be treated as a supplied value, and must not be silently defaulted either. | – | test | tests/test_form_empty_value_defaults.py::test_required_form_field_sent_empty_is_missing, tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py::test_required_form_field_empty_multipart_part_is_missing |
| Extra-field behaviour on single-model form bodies is unchanged: a model with `extra="forbid"` still returns `422` `extra_forbidden` for an undeclared form key; a model with `extra="allow"` still receives undeclared form keys in the parsed model. | – | test | tests/test_form_empty_value_defaults.py::test_model_extra_forbid_still_rejects_unknown_key, ::test_model_extra_allow_still_collects_unknown_key, tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py::test_undeclared_form_key_with_empty_value_is_still_passed_through, ::test_extra_forbid_model_still_rejects_key_matching_aliased_field_name |
| Non-empty values are unaffected: ordinary populated urlencoded and multipart forms, including `List[...]`/sequence `Form` fields and `UploadFile`/`bytes` `File` fields, behave exactly as before. | – | test | tests/test_form_empty_value_defaults.py::test_populated_urlencoded_form_unchanged, ::test_populated_sequence_form_unchanged, ::test_populated_multipart_file_and_form_unchanged, ::test_populated_bytes_file_unchanged, tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py::test_form_model_with_populate_by_name_still_accepts_field_name, ::test_whitespace_only_form_value_is_not_treated_as_empty |
| A `Form` field declared with an alias (`Form(alias="...")`) sent empty falls back to its default, and the alias key is not re-added from the raw body. | – | test | tests/test_form_empty_value_defaults.py::test_aliased_form_field_sent_empty_uses_default, ::test_aliased_form_field_sent_empty_uses_non_none_default, ::test_extract_form_body_does_not_readd_alias_keys |
| The whole existing test suite still passes; no currently-passing test is weakened or deleted. | – | test | full suite in worktree: 2579 passed, 133 skipped; no pre-existing test file modified by the diff |

Round 1: FAIL (2 finding(s); its run 2573 passed / 2 failed)
- [high] fastapi/dependencies/utils.py:907 Adding field.name (not just field.alias) to processed_keys suppresses a raw form key no declared field reads, so an extra="forbid" model with username: str = Field(alias="user") now returns 200 for user=Rick&username=sneaky where the base commit returned 422 extra_forbidden.
- [high] fastapi/dependencies/utils.py:907 The same field.name suppression makes a populated urlencoded POST of a populate_by_name=True form model by field name return 422 missing at ["body","user"] where the base commit returned 200.

## Test-file drift

none: test files unchanged since the tests phase (`e328dba`).

## Plan

- [x] 1. Restrict _extract_form_body's raw-body passthrough to keys with no declared field — In `/private/tmp/rehorse-eval/fastapi-13533/.rehorse/worktrees/t-20260907-form-default-value-regressions/fastapi/dependencies/utils.py`, `_extract_form_body()` now builds a `processed_keys` set of each declared body field's `alias` and `name` (the same pattern `request_params_to_args()` uses) and passes through raw `received_body` keys only when they are not in that set, so an empty declared field keeps its dropped value and falls back to its default while undeclared keys still reach the model for `extra="forbid"`/`"allow"`. Full suite: 2571 passed, 133 skipped, 0 failed; committed as a8bebee4e; nothing left.
- [x] 2. Fix (verifier round 1): Adding field.name (not just field.alias) to processed_keys suppresses a raw form key no declared field reads, so an extra="forbid" model with username: str = Field(alias="user") no... (fastapi/dependencies/utils.py:907) — Removed `processed_keys.add(field.name)` from `_extract_form_body()` in /private/tmp/rehorse-eval/fastapi-13533/.rehorse/worktrees/t-20260907-form-default-value-regressions/fastapi/dependencies/utils.py (alias-only, with a comment stating that `_get_multidict_value()` reads the raw body by `field.alias` alone), and corrected the now-wrong assumption line in REHORSE_SPEC.md; the change is confined to the caller the finding named, no shared helper touched. Full suite green (2575 passed, 133 skipped) and the verifier's case verified directly against the worktree: `extra="forbid"` + `username: str = Field(alias="user")` with `user=Rick&username=sneaky` now returns 422 `extra_forbidden` (was 200 on step 1's code), while criterion 1's `name=` still yields `None`; nothing left.
- [x] 3. Fix (verifier round 1): The same field.name suppression makes a populated urlencoded POST of a populate_by_name=True form model by field name return 422 missing at ["body","user"] where the base commit re... (fastapi/dependencies/utils.py:907) — No code change was needed: step 2's removal of `processed_keys.add(field.name)` in `/private/tmp/rehorse-eval/fastapi-13533/.rehorse/worktrees/t-20260907-form-default-value-regressions/fastapi/dependencies/utils.py` already resolved this finding — a throwaway script at `/tmp/check_pbn.py` confirms a `populate_by_name=True` form model posted by field name (`username=Rick`) and by alias (`user=Rick`) both return 200 with `{"user":"Rick"}`, matching the base commit; I made an empty commit `f3d6e4d0f`. Full suite green (2575 passed, 133 skipped, 0 failed) including `tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py::test_form_model_with_populate_by_name_still_accepts_field_name`; nothing left.
- [x] 4. Make the verifier's tests pass: tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py (2 failing) — No implementation change was needed; steps 2 and 3 already satisfy both verifier findings — `_extract_form_body()` in /private/tmp/rehorse-eval/fastapi-13533/.rehorse/worktrees/t-20260907-form-default-value-regressions/fastapi/dependencies/utils.py adds only `field.alias` to `processed_keys` (not `field.name`), which is exactly what the verifier's alias tests require, so I made an empty commit 7bb959634. All 4 tests in tests/test_rehorse_verify_t-20260907-form-default-value-regressions.py are collected and pass, and the full suite is green at 2575 passed / 133 skipped / 0 failed; nothing left.

## Try it yourself

```
cd /private/tmp/rehorse-eval/fastapi-13533/.rehorse/worktrees/t-20260907-form-default-value-regressions
/private/tmp/rehorse-eval/fastapi-13533/.venv/bin/python -m pytest -q --tb=short -rfE
# no run command detected (no package.json dev/start, Makefile run target, build.sh, cargo/go/swift project, or README run line)
```

## Next

```
/rehorse:merge t-20260907-form-default-value-regressions      merge rehorse/t-20260907-form-default-value-regressions into your branch and remove the worktree
/rehorse:discard t-20260907-form-default-value-regressions    drop the worktree and the branch
```
