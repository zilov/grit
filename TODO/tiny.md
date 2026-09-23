# Tiny TODOs

Small fixes and improvements — close in one batch when still relevant.

---

- [x] **`grit reopen -t RC-XXXX`** — set ticket status back to active after it's been
  marked done (currently requires manual JSON edit in `~/.grit/registry.json`).
  One-liner: `registry.find_ticket(ticket_id)["status"] = "in_curation"` + save.

- [x] **`grit summary`** — show ticket counts from registry.json grouped by status
  and time period (done this week / month / quarter). Read-only, no new data needed.

- [x] **Sex chromsome count off when some sex-chromsome unlocs are in genome ** — genome with 30 autosomes + ZZ and 10 Z unlocks `Sex chromsomes: ZZZZZZZZZZZZ`.

- [x] **Status: runs count inflated 2x** — runs.jsonl writes one entry on
  `start` (status=started) and one on `finish` (status=success/failed).
  `step_counts` in `status.py` counts both, so a single run shows as 2.
  Fix: count only terminal entries (`success` or `failed`) per step,
  or count unique `run_dir` values instead of raw lines.

- [x] **Any step's `--untracked` run becomes canonical once it finishes** —
  root cause: `RunTracker.start(untracked=True)` wrote `status="untracked"`,
  but `RunTracker.finish()` had no idea the run was untracked and always
  overwrote it with `status="success"/"failed"` — since `_untracked_dirs()`
  keys off the *last* record per `run_dir`, the finish record always won,
  silently promoting the untracked run to canonical (this is what corrupted
  `pretext-to-asm`'s canonical resolution after a `post-curation --untracked`
  run, and what made `blast-contaminants -t RC-4896 --untracked` show up as
  `fa(1,2)` canonical in `grit status`). Fixed by threading `untracked=...`
  into `finish()` (and the bsub `-Ep` epilogue path via `_state-update
  --untracked`) so it keeps writing `status="untracked"` instead of
  clobbering it — `grit untrack --undo` still works (and now also promotes a
  run that was `--untracked` from the start, not just one marked untracked
  after the fact, using the outputs its own finish() call recorded).

- [x] **Generalize `--untracked` to all steps** — done: `GritCommand` injects
  `--untracked/-u` for every step (same pattern as `-t`/`--print-only`), and
  all 16 `tracker.start()` call sites pass `untracked=ctx.untracked`. The
  `finish()` calls that don't take it are the recovery/promotion paths
  (`_refresh_pending_jobs`, `_resolve_gone_job`, `status`'s bjobs fallback,
  `sex_matcher`'s resubmit guard, `retrack`), which only act on records with
  `status="started"` — an untracked run is written as `status="untracked"`
  from the start, so it never reaches them. Known limitation: for the same
  reason `record_job()` finds no `"started"` record to patch, so an untracked
  bsub run stores no `job_id` and can't be recovered via bjobs.

- [x] **Canonical went backwards: a fresh `pretext-to-asm` left `chr list`
  canonical on the older `rename-and-orient` run (RC-4833)** — the newest
  `pretext_to_asm` run recorded only `hap1_fa` in its registry `outputs`,
  even though its run dir held the chromosome list and haplotig FASTA on
  disk. `_latest_tracked_output()` compared *recorded* paths only, so that
  run simply dropped out of the chr_list comparison and the stale
  `rename_and_orient` output won — canonical moving backwards in time with
  nothing in `grit status` to explain it. Fixed in `_step_output()`
  (`grit/utils/helpers.py`): when a pool step's latest successful run has no
  matching output key, its latest run dir is re-globbed with that step's
  `_OUTPUT_SPECS` (recurate steps via `_output_specs_for_hap`) before the
  step is skipped. `_canonical_mark()` in `status.py` now also credits a
  canonical file sitting in the row's own run dir, so the step-history
  "Canonical" column agrees with the canonical-files table.

- [x] **Validate the AGP has a `primary` tag for `primary` + `combine_for_curation`
  tickets** — a single-hap (`primary`) assembly curated in a combined window
  needs the primary sequences tagged as such in the AGP; without the tag
  pretext-to-asm can't tell the primary assembly apart from what was merged
  into the map, and the run produces a wrong/empty primary FASTA instead of
  failing. Add a pre-run check on the AGP picked up by
  `_run_pretext_to_asm_core` (gate it on `is_single_hap(ctx) and
  ctx.combine_for_curation`): if no `primary` tag is present anywhere in the
  file, fail before submitting anything, with a message telling the curator to
  tag the primary scaffolds in PretextView and re-export the AGP.

- [x] **`pretext-to-asm-recurate`: fail when pre-existing unlocs lost their
  `unloc` tag** — on a second curation round the scaffolds carried over from
  the first round already have "unloc" in their names, but the tag itself has
  to be re-applied in PretextView; curators forget, and the recurated assembly
  silently promotes those unlocs to normal scaffolds. `grit status`'s recurate
  tip already says "don't forget to tag old unlocs" (`status.py`), so turn the
  reminder into a check: in the recurate step, scan the input AGP for SUPER
  entries whose name contains `unloc` but which carry no `unloc` tag, and fail
  with the list of offending scaffolds plus a tip to re-tag them and re-export
  the AGP. Implemented against the real PretextViewAI AGPs in
  `~/curations/work/*/*.agp_1`: the carried-over unloc name lives in the
  *component* column (6), not the object name (1, always `Scaffold_N`), and the
  `Unloc` tag is per row in columns 10+ — so the check scans components, not
  object names.

- [x] **Show reference info in `grit status -t`** — the ticket's reference
  (as picked up / produced by `find-reference`) isn't surfaced anywhere in
  `grit status -t RC-XXXX`; the curator has to dig through the run dirs to
  see which reference was used. Add it to the status output (name/path of the
  selected reference, and whether one was found at all).

- [x] **`microchromosome-combine` can pick up the wrong AGP** — `pretext-to-asm`
  writes an AGP next to every curated FASTA it produces, so a run dir can end up
  holding several `{tol_id}*.agp*` files. The curator then copies the curated
  *small merged* AGP into the same `microchromosome-second-shot` run dir, and
  `_run_pretext_to_asm_core` (called with `agp_search_dir=second_shot_dir` and no
  `agp_glob`) globs `{tol_id}*.agp*` and takes `agp_files[0]` — an unsorted,
  arbitrary match that can be a pretext-to-asm-generated AGP instead of the
  curated one, so the combine step silently runs on the wrong AGP. Fix: give the
  curated small merged AGP its own directory (e.g.
  `{second_shot_dir}/curated_small_agp/`) — create it in
  `microchromosome-second-shot`, point the `scp` tip printed by that step and by
  `grit status` at it, and have `microchromosome-combine` pass that dir (plus a
  narrow `agp_glob`) to `_run_pretext_to_asm_core`. While there, make the AGP
  pick deterministic (sort, and fail loudly on more than one match) rather than
  `agp_files[0]`.

- [x] **`microchromosome-second-shot` output globs don't match what the script
  actually writes** — `_OUTPUT_SPECS` in
  `grit/steps/pre_curation/microchromosome_second_shot.py` was inferred from
  `microchr_second_shot_curation.py`'s docs and never checked against a real run
  (see the `# Confirm these globs` comment). A real run (RC bGraRel1,
  `microchromosome_second_shot/2026-08-13T13_06_35/`) writes everything into a
  `{tol_id}/` **subdirectory** of the run dir, with different names:

  | tracked key | current glob | real file |
  |---|---|---|
  | `hap1_large_fa` | `*.hap1.large.fa` | `bGraRel1/bGraRel1.hap1.1.primary.curated.large.fa` |
  | `hap1_large_chr` | `*.hap1.large.chr_list.csv` | `bGraRel1/bGraRel1_hap1.large.chr_list.csv` (underscore, not dot) |
  | `merged_small_fa` | `*_curated_small_merged.fa` | `bGraRel1/bGraRel1_curated_small_merged.fa` |

  `collect_outputs()` globs non-recursively, so every spec misses and the step
  finishes "success" with no recorded outputs. `microchromosome-combine` then
  falls back to its hand-built `second_shot_dir / f"{tol_id}.hap1.large.fa"`
  paths and `combine_curated_micros.py` dies with
  `FileNotFoundError: .../2026-08-13T13_06_35/bGraRel1.hap1.large.fa`.
  Fix: point the second-shot `_OUTPUT_SPECS` at `{tol_id}/…` with the real
  patterns (`{tol_id}/*.{hap1}.*.curated.large.fa`,
  `{tol_id}/*_{hap1}.large.chr_list.csv`,
  `{tol_id}/*_curated_small_merged.fa`), check whether
  `hic/pretext_maps_processed/*hr.pretext` (and the `scp` tip built from it)
  also sits under that subdir, and update `microchromosome-combine`'s own
  merged-small glob, `large_glob_specs`, and every
  `second_shot_dir / f"{tol_id}.…"` fallback to match — plus fail loudly when a
  required input is missing instead of handing a non-existent path to the
  external script. Also note the `.large.fa`/`.small.fa` names carry the
  hap-suffix token (`.1.primary.`) from the unmerged `add-hap-suffix-handling`
  branch the step's `_SECOND_SHOT_SCRIPT` TEMP comment mentions — confirm the
  final naming before pinning the globs.

- [x] **`curationpretext`: use `-N` instead of `--email`** — `hic-remapping`
  passes the curator's address as `--email {ctx.email}`, which the pipeline
  accepts but never notifies on, so no mail ever arrives. `-N <addr>` is
  nextflow's own notification flag and works as expected. Change the flag in
  `grit/steps/post_curation/hic_remapping.py` (and the `--email` mentions in
  `grit/config/sanger_template.yaml` / the tests asserting on the rendered
  command).

- [x] **`busco-curated`: add `module load grit`** — singularity is available in
  the `grit` module, so the step should load it like the other module-based
  steps (`module_cmd(...)` in `grit/utils/modules.py`) instead of relying on
  singularity already being on PATH.

