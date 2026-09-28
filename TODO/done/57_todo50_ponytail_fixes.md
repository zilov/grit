# TODO 57: trim over-engineering the TODO 50 branch introduced

## Problem

A ponytail over-engineering review of `todo50-remediation`
(`git diff origin/main...HEAD`) found that nearly all added production code
traces to a TODO 50 item. A small amount, about 90 lines, duplicates existing
logic or goes beyond what the item asked for. This task removes that excess
before the branch is merged. It changes no behaviour.

Out of scope, because each one needs a decision against a CLAUDE.md rule (see TODO 58):
the `_run(timeout=)` machinery (CORR-22 asked for it), a shared
`submit_tracked` helper for the bsub try/except blocks, `UnsupportedAssemblyTypeError`,
and the dead `paternal`/`maternal` branches.

## Design

1. **One completion criterion.** `finished_run_outputs()` (`grit/utils/helpers.py`)
   re-implements the verdict logic already in `RegistryManager._resolve_gone_job`
   (`grit/core/registry.py`): `_get_step_specs` + `collect_outputs` +
   `verify_outputs`, and the sex_matcher special case. The two check things in a
   different order. Make `_resolve_gone_job` call `finished_run_outputs()`, and
   keep only its own `authoritative` → `failed` branch.
   **Behaviour must not change.** Today `_resolve_gone_job` never resolves a step
   that has no specs (sex_matcher aside). Check what `finished_run_outputs`
   returns for such a step, and keep the old result, with a test if one is missing.
2. **Delete `tests/test_package_exports.py`.** It asserts that private names are
   absent and repeats the import lines. The real fix was removing the re-exports.
3. **`.github/workflows/ci.yml`: replace the inline-Python wheel check** with
   `unzip -l dist/*.whl | grep -q …` for `grit/config/sanger_template.yaml` and `grit/scripts/`.
4. **`pretext_to_asm`: replace `required_outputs: Mapping[str, str]`** with
   `required_output: str | None`, and build the message in the core. Recurate's
   post-call check on the skip path stays.
5. **`helpers.py`: merge `_size`/`_mtime`** into one `_stat(p) -> os.stat_result | None`.
   Call sites use `.st_size`/`.st_mtime`, and missing files are handled as before.
6. **`run_tracker.py`: stop duplicating `run_dir_statuses`.** `_untracked_dirs`
   derives from `run_dir_statuses`, so there is one "last status per run_dir" loop.
7. **`qv.py`: inline `_QV_OUTPUT_KEYS`**, which is used once.

Each item is its own commit.

## Verification

- `pytest tests/ -v`, and `ruff check . && ruff format --check .`
- `tests/local_smoke_test.sh` dry-run section still passes
- `tests/test_bsub_submission.py`, the canonical tests and the registry tests pass unchanged
