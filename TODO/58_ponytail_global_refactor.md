# TODO 58: repo-wide over-engineering cleanup (ponytail audit)

## Problem

A whole-repo ponytail audit (2026-09-28) estimated about 1,100 removable lines
and no removable dependencies. biopython, pymysql and requests are needed by
GritJiraIssue, and the plotting libraries run in the job environment. The
excess is dead code, back-compat shims, repeated boilerplate and duplicated
logic. Start after TODO 57 and the TODO 50 branch are merged.

The defensive patterns in CLAUDE.md were reviewed and stay: fail-closed
registry reads, `.bak`/dated snapshots, `_atomic_write`, `gone` vs `unknown`,
and `BsubSubmissionError`.

## Design

### A. Safe cuts (no CLAUDE.md rule involved)

1. **Delete the back-compat re-exports** in `grit/__init__.py`, `grit/steps/__init__.py`,
   the `grit/steps/*/__init__.py` files and the `__all__` in `post_curation.py`.
   Point the two test importers at the real modules.
2. **Make `CurationContext.tracker` required.** Drop the ~80 `if ctx.tracker` /
   `ctx.tracker and` guards and dead fallbacks such as `hic_remapping.py`
   `... / "untracked"`. Tests pass a stub tracker.
3. **Move command boilerplate into `GritCommand.invoke()` or a decorator.** The 26
   `*_cmd` bodies repeat `build_context` / try / `log.exception` / `SystemExit(1)`.
4. **Remove the 179 lines of `# -----` section banners.** Several are stale ("Argparse", empty "Constants").
5. **Declare `_PTA_ALIASES` and `_HAPLOTIG_KEYWORDS` once each**, at module level in
   `helpers.py`, instead of redefining them in 5 and 3 functions. `"haplotigs" not in f` replaces the keyword `any()`.
6. **Shrink `modules.py`.** Drop the unused `FASTGA`, collapse the three `"grit"` keys,
   make `module_cmd` one line with no hand-written `KeyError`, and trim the docstrings.
7. **Tidy `status.py` helpers:**
   - `_canonical_haps` becomes `is_single_hap`;
   - month arithmetic uses `divmod` and `strftime("%b")`;
   - drop the always-None `key_filter`, the one-entry `_LESS_TIP_STEPS` loop and the identity `_CANONICAL_TYPE_MARKS`;
   - the colour if/elif chain becomes a dict;
   - delete the dead `"started"`/`"EXIT"`/`"running"` branches.
8. **Simplify `cleanup.py`:**
   - merge the nextflow sweeps into one loop over `("work", ".nextflow", ".nextflow.log*")`;
   - reduce the ticket marking to one line;
   - delete the `pragma: no cover` branch and the always-False `dry_run`.
9. **`result_parsers.collect_curation_results`:** use one `_safe()` wrapper instead
   of 5 try/except blocks, and a loop over pretext_to_asm and its micro variant.
10. **Delete dead CLI state in `click_cli.py`:**
    - `--verbose`, `GlobalState.verbose` and `logging_level`;
    - the `ensure_object` call and the `getattr` guards;
    - the double `add_command(untrack/retrack)`;
    - the exists check that `click.Path(exists=True)` already does;
    - `_state-update --job-id`.

    Also move the `done`/`reopen`/`remove` boilerplate onto `_resolve_tracker`.
11. **Replace `build_scp_tip`/`build_less_tip`** with 3-line helpers next to `_print_scp_tips`.
12. **Use `click.Path(path_type=Path)`** instead of 13 `Path(x) if x else None`.
13. **Register `pp`** with `cli.add_command(post_processing_cmd, name="pp")` instead of the copied `pp_cmd`.
14. **Delete `RunTracker.log_path()` and `grit_dir`**, and fix the stale module docstring.
15. **Remove `CurationContext.assembly_type`**, which always equals `hap1_prefix`.
    `haplotig_files.py:56` uses `not is_single_hap(ctx)` instead.
16. **Use the stdlib in small places:**
    - `max(files, key=os.path.getmtime)` replaces `_sort_by_mtime(...)[0]`;
    - move `_pick_highest_version` into `setup.py`;
    - `argparse` replaces `_arg_value` in `paf_top_targets_by_coverage.py`.
17. **Small fixes:**
    - collapse the duplicate `refresh_statuses` branches;
    - drop the `ImportError` catch in `_get_step_specs`;
    - `context.py:313` becomes `tol_id.split(".")[0]`.

### B. Needs a decision: each item conflicts with a CLAUDE.md rule

Decide each item, then update CLAUDE.md in the same change.

- **B1. Delete `add_pretext_view_tracks.py`,** its test, its `STEP_TO_STATUS` entries and the
  commented-out CLI blocks. The commands are disabled, and it hardcodes a path
  under `~dz11`. Also remove the CLAUDE.md dry-run note about it.
- **B2. Drop `_DRY_RUN_SUPPORTED_COMMANDS`** once B1 is done. The only commands
  outside the allowlist are the disabled track commands. Alternatively, flip it to an opt-out kwarg.
- **B3. Add a `submit_tracked(ctx, step, run_dir, inner_cmd, opts)` helper** to replace the
  7 hand-written start → epilogue → `_submit_bsub` → `record_job` → except-finish-failed
  blocks. Retarget `tests/test_bsub_submission.py` and the CLAUDE.md rule at the helper.
  The guarantee stays; only its location changes.
- **B4. Remove `status.py`'s inline bjobs → `finish("success")` path**
  (`show_ticket_history`, `_auto_step_outputs`). `refresh_statuses()` has already
  reconciled by then, so keep bjobs for display labels only. Check the
  cluster/authoritative rule before removing it.
- **B5. `_run(timeout=)` / `_run_with_timeout`** have no callers. The recommendation is to
  **keep** them, because CORR-22 asked for them and they are documented.
- **B6. Replace `UnsupportedAssemblyTypeError`** with `click.ClickException`. It is named in CLAUDE.md.
- **B7. Remove the dead `paternal`/`maternal` branches.** CLAUDE.md keeps them on purpose, pending trio support.

## Verification

- `pytest tests/ -v` and `ruff check .` after each item, with one commit per item
- dry-run section of `tests/local_smoke_test.sh`
- on the farm: `grit --print-only` for one ticket across the post-curation chain; compare command strings before and after
