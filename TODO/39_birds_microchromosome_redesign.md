# TODO 39: modernize birds microchromosome second-shot + combine steps

## Problem

`grit/steps/pre_curation/microchromosome.py` implements a draft pair of
steps wrapping two production scripts from
`vgp_curation_scripts/birds_microchromosomes/` (`microchr_second_shot_curation.py`
and `combine_curated_micros.py`), used for birds and other genomes with many
small chromosomes. The draft predates grit's current conventions established
by `fastga.py`, `rename_and_orient.py`, and `busco_synteny.py`:

- It never calls `ctx.tracker.start`/`finish`/`record_job` — the step is
  invisible to `find_latest_dir`, `find_canonical_fa`, `find_canonical_chr_list`,
  and `grit status`.
- No `_OUTPUT_SPECS`, so it's absent from `_get_step_specs()`'s `_MAP` in
  `grit/utils/helpers.py` and from `STEP_MANIFESTS` in `grit/core/manifests.py`
  (only a bare `STEP_TO_STATUS["microchromosome"] = "in_curation"` entry
  exists, nothing for the post/combine half).
- Hardcodes an absolute `/software/grit/projects/vgp_curation_scripts/...`
  path for the pre step but a different, user-specific
  `~/gitlab/vgp_curation_scripts/...` path for the post step's call to
  `combine_curated_micros.py`.
- Writes chromosome lists as `*.chr_list.csv`, diverging from the rest of
  the codebase's `{tol_id}.{hap}.chromosome.list.csv` convention.
- Both pre and post functions live in one file under `pre_curation/`, even
  though the post half is a post-curation step by every other convention in
  the codebase.
- It's never been exercised end-to-end (no tests, not in the smoke test).

Because the step isn't tracker-integrated, downstream steps (fastga,
rename-and-orient, finalize-qc) never learn about the merged (large + micro)
assembly this workflow produces — a curator has to manually feed file paths
around, and `grit status`'s breaks/joins figure only reflects the first
`pretext-to-asm` run, not the second round done on microchromosomes.

Out of scope: the external scripts themselves
(`microchr_second_shot_curation.py`, `combine_curated_micros.py`) are not
modified beyond what grit already assumes about their CLI/output naming —
they're maintained in a separate repo and already in production use by
curators via their own README/`examples.md`. No persisted YAML/JSON
curation-summary file is introduced; breaks/joins aggregation stays a live
parse-and-sum, same shape as today's single-run parsing.

## Design

### 0. Execution mode stays synchronous — no outer bsub

The bundled `microchr_second_shot_curation.py` already submits its own
blocking `bsub -K` jobs internally (MicroFinder, the small-scaffold merge)
which stream their stdout live to whoever invokes the script. Wrapping the
whole script call in an async outer `_submit_bsub` (as `fastga`/`busco_synteny`
do) would redirect that live output into a log file instead of the curator's
terminal — the opposite of what's wanted. So both steps keep calling `_run(...,
capture=False)` directly, same as today; only tracker lifecycle wiring
(`ctx.tracker.start`/`finish`) is added around the call, matching the shape
`pretext_to_asm.py` already uses for its own synchronous `_run` call.

### 1. File layout — split into pre/post to match convention

- New: `grit/steps/pre_curation/microchromosome_second_shot.py`, home for
  `run_microchromosome_second_shot` (renamed from `run_microchromosome_curation`).
- New: `grit/steps/post_curation/microchromosome_combine.py`, home for
  `run_microchromosome_combine` (renamed from `run_microchromosome_post_curation`).
- Delete `grit/steps/pre_curation/microchromosome.py`.
- Update imports/registration in `grit/steps/pre_curation/__init__.py`,
  `grit/steps/post_curation/__init__.py`, `grit/steps/__init__.py`,
  `grit/core/click_cli.py` (command names become `microchromosome-second-shot`
  and `microchromosome-combine`).

### 2. `run_microchromosome_second_shot` (pre) — tracker integration

Keep the existing FASTA/chr-list discovery logic (glob against
`ctx.workdir` for `{tol_id}*.primary.curated.fa` etc.), wrap execution the
same way `pretext_to_asm.py` wraps its own `_run` call:

```python
run_dir = (
    ctx.tracker.start("microchromosome_second_shot", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
    if ctx.tracker
    else ctx.workdir / "microchromosome_second_shot" / "untracked"
)
second_shot_cmd = (
    f"{_SECOND_SHOT_SCRIPT} "
    f"-hap1 {hap1_fa} -hap1_chr {hap1_chr} {hap2_argument} "
    f"-hic {ctx.hic_dir} -lr {ctx.long_reads_dir}/fasta "
    f"-o {run_dir}"
)
try:
    _run(second_shot_cmd, ctx.print_only, capture=False)
    if ctx.tracker:
        outputs = collect_outputs(
            _OUTPUT_SPECS, run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
        )
        ctx.tracker.finish("microchromosome_second_shot", run_dir, "success", outputs=outputs or None)
except Exception:
    if ctx.tracker:
        ctx.tracker.finish("microchromosome_second_shot", run_dir, "failed")
    raise
```

- `-o` becomes the tracked `run_dir` instead of the fixed
  `ctx.workdir / "second_shot_microchromosomes"`, so re-runs get their own
  run dir like every other tracked step.
- Script path: `_SECOND_SHOT_SCRIPT = "/software/grit/projects/vgp_curation_scripts/birds_microchromosomes/microchr_second_shot_curation.py"`
  — matches `fastga.py`'s `FastGA_dot_dgenies.sh` convention (externally
  deployed, not repo-bundled — no `_REPO_ROOT`-relative path).
- `_OUTPUT_SPECS` (glob patterns to confirm against `setup_paths()` in
  `microchr_second_shot_curation.py` during implementation — see its
  `hap1_large_fa`/`hap1_large_chr_list`/`merged_small_fa` path templates):
  ```python
  _OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
      ("hap1_large_fa",   "*.hap1.large.fa",           []),
      ("hap2_large_fa",   "*.hap2.large.fa",           []),
      ("hap1_large_chr",  "*.hap1.large.chr_list.csv", []),
      ("hap2_large_chr",  "*.hap2.large.chr_list.csv", []),
      ("merged_small_fa", "*_curated_small_merged.fa", []),
  ]
  ```
- Keep the scp-reminder log line for pulling the micro pretext map locally
  (update the path it references to the new tracked `run_dir`).

### 3. Shared `pretext-to-asm` core (refactor)

Extract the invocation body of `run_pretext_to_asm` in
`grit/steps/post_curation/pretext_to_asm.py` into a reusable internal helper
so the combine step doesn't duplicate AGP-discovery/command-building logic:

```python
def _run_pretext_to_asm_core(
    ctx: CurationContext,
    step_name: str,
    original_fa: Path,
    agp_search_dir: Path,
    out_fa: Path,
    output_specs: list[tuple[str, str, list[str]]],
) -> Path:
    """Runs pretext-to-asm for one (original_fa, agp) pair under a tracked step.

    Looks for `{tol_id}*.agp*` in agp_search_dir, runs pretext-to-asm,
    records outputs via output_specs under step_name. Returns run_dir.
    """
```

`run_pretext_to_asm` becomes a thin wrapper calling this with
`agp_search_dir=ctx.workdir`, `original_fa=ctx.workdir/"original.fa"`,
`step_name="pretext_to_asm"`, `out_fa=run_dir/f"{tol_id}.fa"` — behavior
unchanged for existing callers/tests.

The combine step calls it again with `step_name="pretext_to_asm_micro"`,
`original_fa=merged_small_fa` (from the second-shot step's tracked outputs),
`agp_search_dir=<second-shot run_dir>`, `out_fa=.../{tol_id}_small.fa`,
producing per-hap curated small fasta/chr-list files the same way the main
run produces per-hap curated fasta from a merged multi-hap input.

### 4. `run_microchromosome_combine` (post)

- Locate the second-shot step's run dir via
  `find_latest_dir(ctx, "microchromosome_second_shot")` (the same helper
  `rename_and_orient.py` uses to find `fastga`'s output) instead of a fixed
  `ctx.workdir / "second_shot_microchromosomes"` path.
- Call `_run_pretext_to_asm_core(...)` (§3) to turn the curated micro AGP
  into small curated fasta/chr-lists, tracked as `pretext_to_asm_micro`.
- Call `combine_curated_micros.py` per haplotype exactly as today's logic
  (still two sequential local `_run()` calls, one per hap — no per-hap
  tracked steps needed, unlike `rename_and_orient`'s hap1/hap2 split),
  except:
  - fix the hardcoded `~/gitlab/vgp_curation_scripts/birds_microchromosomes/combine_curated_micros.py`
    path to `/software/grit/projects/vgp_curation_scripts/birds_microchromosomes/combine_curated_micros.py`
    (same convention as the second-shot script);
  - pass `--chr-output` using grit's standard naming
    (`{tol_id}.{hap}.chromosome.list.csv`) instead of the script repo's own
    `*.chr_list.csv` convention — no script change needed, this is just the
    filename grit tells it to write;
  - run under a tracked `run_dir` (`ctx.tracker.start("microchromosome_combine", ...)`),
    writing merged fasta/chr-list there instead of a fixed
    `second_shot_microchromosomes/final_curated/` path.
- `_OUTPUT_SPECS`:
  ```python
  _OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
      ("hap1_fa",       "{tol_id}.{hap1}.*.fa",                []),
      ("hap2_fa",       "{tol_id}.{hap2}.*.fa",                []),
      ("hap1_chr_list", "{tol_id}.{hap1}.chromosome.list.csv", []),
      ("hap2_chr_list", "{tol_id}.{hap2}.chromosome.list.csv", []),
  ]
  ```

### 5. Canonical-file lookup integration

In `grit/utils/helpers.py`, add `"microchromosome_combine"` to the priority
chains in `find_canonical_fa` and `find_canonical_chr_list`, positioned
between `blast_contaminants` and `pretext_to_asm`:

```
rename_and_orient → rename_and_orient_hap2 → blast_contaminants → microchromosome_combine → pretext_to_asm
```

Chronologically the micro workflow runs right after the first
`pretext-to-asm`, before blast-contaminants/rename-and-orient — so those
steps, when they've run, should still win; but the merged assembly must beat
the *plain* `pretext_to_asm` output once it exists.

### 6. Breaks/joins total

In `grit/utils/result_parsers.py`, extend `collect_curation_results`: after
computing `r.cuts/breaks/joins` from the main `pretext_to_asm` run, also
look up `tracker.latest_run_dir("pretext_to_asm_micro")`; if present and the
main parse succeeded, parse its log with `parse_pta_log` the same way and
add its `(cuts, breaks, joins)` into the totals. If the main parse didn't
find anything, leave `r.cuts/breaks/joins` as `None` (nothing to add a
partial total to). No new fields on `CurationResults` — a single combined
figure is what `grit status` should show, not a per-round breakdown.

### 7. Manifests / status registration

In `grit/core/manifests.py`:
- Rename `STEP_TO_STATUS` key `"microchromosome"` → `"microchromosome_second_shot"`.
- Add `"microchromosome_combine"` with whatever status value neighboring
  steps like `blast_contaminants`/`rename_and_orient` use (check at
  implementation time — mirror the closest existing step's status level).

In `grit/utils/helpers.py`'s `_get_step_specs()` `_MAP`, register both new
step names against their `_OUTPUT_SPECS`.

### 8. Tests

Add `tests/test_microchromosome_second_shot.py` and
`tests/test_microchromosome_combine.py`, following `tests/test_fastga.py` /
`tests/test_rename_and_orient.py`'s style: patch `_run` (and
`find_latest_dir`/`glob.glob` as needed) at module level, use the
`mock_ctx`/`mock_ctx_primary` fixtures, assert on built command strings and
`_OUTPUT_SPECS` keys. Cover:

- hap1-only vs hap1+hap2 command construction for the second-shot step;
- combine step's AGP-discovery-missing error path (today's
  `FileNotFoundError`), and `print_only` behavior;
- `_run_pretext_to_asm_core` exercised via both callers — existing
  `run_pretext_to_asm` behavior/tests must keep passing unchanged, since
  this is a refactor, not a behavior change, for that function;
- `collect_curation_results` summing breaks/joins across `pretext_to_asm`
  + `pretext_to_asm_micro` (add to `tests/test_result_parsers.py` if it
  exists, else a new test module).

### 9. Docs

- Update `CLAUDE.md`'s `pre_curation/`/`post_curation/` directory bullet
  lists to reflect the split (`microchromosome_second_shot`,
  `microchromosome_combine`).
- Move this file to `TODO/done/` once implemented.

### Net effect

- `microchromosome-second-shot`/`microchromosome-combine` become full
  tracked steps: `grit status` sees them, `find_canonical_fa`/
  `find_canonical_chr_list` automatically hand downstream steps the merged
  assembly once it exists, and re-runs get their own run dirs instead of
  clobbering a fixed path.
- Breaks/joins in `grit status` reflect both curation rounds combined for
  tickets that go through this workflow, with no change in shape for
  tickets that don't (micro steps never ran → `pretext_to_asm_micro` run
  dir doesn't exist → total is just the main run, same as today).
- Script paths and chromosome-list naming become consistent with the rest
  of the codebase.
- No change to `fastga.py`/`busco_synteny.py`/`rename_and_orient.py`
  themselves — only their patterns are being followed. `run_pretext_to_asm`'s
  public behavior is unchanged by the refactor.
</content>
