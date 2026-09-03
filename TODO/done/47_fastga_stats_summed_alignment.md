# 47 — fastga-stats: replace top-1-longest-alignment with summed non-overlapping coverage

## Problem

`grit fastga-stats` (`grit/steps/optional/fastga.py:run_fastga_stats`) reads
`*.top1_targets.tsv`, which `paf_top_targets_add_top_longest.py` builds by
picking, for each query scaffold, the target of its **single longest**
alignment (`query_best_aln` in that script). This is noisy: one long
mismapped/repetitive alignment can outrank the target that actually has the
most real synteny, so the reported "best" reference chromosome per
super-scaffold is often wrong.

`rename-and-orient` (`/Users/dz11/github/rename-and-orient`) already solves
this correctly for its own chromosome-assignment step: it sums
**non-overlapping** query-interval coverage per (query, target) pair before
picking a winner, so one spurious long hit can't dominate. That logic lives
in `src/rename_and_orient/alignment.py`:
- `merge_intervals()` — merges overlapping `(start, end)` query intervals
- `calculate_target_alignments()` — per query, sums merged interval length
  per target (`total`/`plus`/`minus`)
- `determine_best_target()` — picks the target with max summed length

## Design

Add a new script (parallel to `paf_top_targets_add_top_longest.py`, not a
patch to it — `fastga-stats`'s current top1 output/consumers stay in place
until this is proven out) that:

1. Reads the FastGA PAF file.
2. Filters out alignments shorter than a length threshold (default 3000bp,
   flag-configurable) before merging — short spurious hits shouldn't count
   toward coverage at all.
3. For each (query scaffold, target reference chromosome) pair, merges
   overlapping query intervals and sums the non-overlapping aligned length
   (reuse/port `merge_intervals` + the summing logic from
   `rename_and_orient/alignment.py`, not `paf_top_targets_add_top_longest.py`'s
   per-target `merge_intervals` — same idea, but that file's version returns
   the length directly rather than a mapping structure).
4. Needs target chromosome lengths to compute `prc_of_ref_length` — PAF col 7
   (`target_length`) already carries this per record, no extra input file
   needed.
5. Writes one row per (query, target) pair with a summed length above the
   threshold:
   `curated_fa_chr,ref_fa_chr,aligned_length,prc_of_ref_length`

Open question to resolve during implementation: should the output keep only
each query's single best target row (one row per `curated_fa_chr`, replacing
today's top1 semantics with a correct one), or every (query, target) pair
above the length threshold (closer to the existing top-10 stdout report in
`paf_top_targets_add_top_longest.py`)? Check with the user which shape
`run_fastga_stats` should render — the CLAUDE.md-documented step keeps a
Rich `Table` per super scaffold today, so either shape is a straightforward
swap in `grit/steps/optional/fastga.py`.

## Files likely touched

- New script under `grit/scripts/` (e.g. `paf_summed_target_coverage.py`)
- `grit/steps/optional/fastga.py`: `_OUTPUT_SPECS`, `_PAF_TOP_TARGETS_SCRIPT`
  wiring, `run_fastga_stats()`, `FastGA_dot_dgenies_stats.sh` invocation (the
  shell script currently calls `paf_top_targets_add_top_longest.py` directly —
  check whether the new script runs alongside it or replaces that call)
- Possibly `grit/scripts/paf_filter_duckdb.py` (currently untracked in the
  working tree) — check whether it already does length-filtering on PAFs and
  could be reused/composed with the new summing step instead of duplicating
  filter logic
- Tests covering the new script's merge/sum/threshold logic
