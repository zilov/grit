# 48 — decouple fastga-stats computation from the fastga bsub job

## Problem

Today, `paf_top_targets_by_coverage.py` (the script that computes the best
reference target per super scaffold by non-overlapping alignment coverage —
see `TODO/done/47_fastga_stats_summed_alignment.md`) runs *inside* the
`fastga` bsub job, invoked by `grit/scripts/FastGA_dot_dgenies_stats.sh` right
after the raw PAF is written. `grit fastga-stats` itself does nothing but
glob for the resulting `*.top1_targets.tsv` and print it as a table.

This coupling has a real cost, just hit in practice: when the stats script's
output format changed (TODO/47), every curator with an existing `fastga` run
had a stale-format `top1_targets.tsv` sitting in their run_dir, and the only
fix was to re-run the *entire* FastGA alignment (an expensive HPC job) just
to regenerate a small derived table from a PAF file that was already
correct and already on disk. More generally: any future bug fix or tweak to
the stats logic requires re-running FastGA to pick it up, even though the
stats computation itself is a fast, local, stdlib-only PAF parse.

## Design

Move the `paf_top_targets_by_coverage.py` invocation out of
`FastGA_dot_dgenies_stats.sh` and into `run_fastga_stats` itself. `grit
fastga-stats` becomes the thing that *computes* the stats (synchronously, no
bsub — it's a fast PAF parse), not just prints an already-computed table.

- `grit fastga` (`FastGA_dot_dgenies_stats.sh` via bsub) now only produces
  `.idx`/`.paf`/delta/dot outputs — the top-targets block is deleted from the
  shell script, and its `<top_targets_script>` 5th positional arg goes away.
- `grit fastga-stats` becomes its own tracked step, `"fastga_stats"` — a new
  run_dir per invocation (`ctx.tracker.start("fastga_stats", ...)`), separate
  from `fastga`'s. This is the first *synchronous* (non-bsub) tracked step in
  the codebase: no `_submit_bsub`/`_state_update_epilogue`/`record_job` — it
  runs `paf_top_targets_by_coverage.py` via the plain `_run()` helper
  (respects `print_only` like every other step) and calls
  `ctx.tracker.finish(..., "success", outputs=...)` directly once the
  subprocess returns, the same way `run_fastga`'s dry-run branch already
  calls `finish()` without ever going through bsub.
- `run_fastga_stats` locates the latest `fastga` run's `*FastGA.paf` via
  `find_latest_dir(ctx, "fastga")`, writes `top1_targets.tsv`/
  `top_targets_summary.txt` into its own new `fastga_stats` run_dir, then
  prints the table exactly as before.
- Side benefit: the "stale 3-column format" guard added as a stopgap in
  TODO/47 becomes genuinely unreachable and is removed — `fastga-stats` now
  always regenerates its output fresh from the current script version, so a
  leftover on-disk file in an old format can never be read again.
- `grit status`'s scp/less tips move from `fastga` to the new `fastga_stats`
  step for `top1_targets`/`top_targets_summary` (`fastga`'s tip keeps
  offering `.idx`/`.paf`).

## Files touched

- `grit/scripts/FastGA_dot_dgenies_stats.sh` — remove the top-targets block
  and the now-unused 5th arg.
- `grit/steps/optional/fastga.py` — split `_OUTPUT_SPECS` (drop
  `top1_targets`/`top_targets_summary`) into a new `_OUTPUT_SPECS_STATS` for
  the `fastga_stats` step; simplify `run_fastga`'s inner_cmd and dry-run
  fixture; rewrite `run_fastga_stats` to compute-then-print, with its own
  dry-run branch.
- `grit/core/manifests.py` — add a `"fastga_stats"` entry.
- `grit/utils/helpers.py` — register `"fastga_stats"` in `_get_step_specs`'s
  step→spec map (for `write_fake_outputs`/dry-run).
- `grit/core/status.py` — move the `top1_targets`/`top_targets_summary`
  scp/less tips from step `"fastga"` to `"fastga_stats"`.
- `CLAUDE.md` — document the new "synchronous tracked step" pattern
  (no bsub, no epilogue, `tracker.finish()` called directly).
- Tests: `tests/test_fastga.py` (largely rewritten), `tests/test_status.py`,
  `tests/test_helpers.py`.
