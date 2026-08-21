# TODO 46: extend `--dry-run` to every remaining file-generating step

## Problem

`TODO/done/45_dry_run_mode.md` built `--dry-run` for six steps (`setup`,
`pretext-to-asm`, `blast-contaminants`, `rename-and-orient`,
`microchromosome-combine`, `pretext-to-asm-recurate`) — enough to exercise the
canonical-FASTA flat mtime pool, but every other `GritCommand`-based step still
rejects `--dry-run` outright via `GritCommand.invoke()`'s
`_DRY_RUN_SUPPORTED_COMMANDS` allowlist (`grit/core/base_command.py`). The user
wants every step that *generates files* to also support `--dry-run`, so a full
pipeline sequence can be exercised end-to-end without HPC/farm access. Registry-
mutating commands (`remove`, `done`, `reopen`, `summary`, `cleanup`) are explicitly
**out of scope** — they stay blocked exactly as `TODO/done/45`'s final review left
them (see `TODO/done/45_dry_run_mode.md`'s Finding 1 fix).

A survey of the 17 remaining `GritCommand`-based step commands (excluding the three
`add_pretext_view_tracks.py` commands — see below) found:

- Five (`busco-synteny`, `fastga-synteny`, `fastga`, `microchromosome-second-shot`,
  `hic-remapping`) already have an `_OUTPUT_SPECS` constant registered in
  `_get_step_specs()`'s `_MAP` (`grit/utils/helpers.py`) — `write_fake_outputs()`
  already works for them today, they just need the `if ctx.dry_run:` branch.
- Several (`fastga-stats`, `haplotig-files`, `validate-files`, `post-curation`,
  `post-curation-recurate`) do no subprocess/tracker work of their own that would
  need a branch — `post-curation`/`post-curation-recurate` are composites that
  just call other (now dry-run-aware) step functions; `fastga-stats`/
  `haplotig-files`/`validate-files` are synchronous, read-only, and already work
  correctly against fake upstream output. These only need adding to
  `_DRY_RUN_SUPPORTED_COMMANDS`.
- Several (`busco-curated`, `qv`, `find-reference`, `sex-matcher`) write their real
  output *outside* the tracked `run_dir` (e.g. `qv`'s output lives under
  `ctx.assembly_curated_dir/merquryk/`, not `run_dir`) and have no `_OUTPUT_SPECS`
  at all in the real path — these need a small local fake-writer rather than
  `write_fake_outputs()`.
- One (`super-to-scaffold`) tracks its output as a raw dict, not via
  `_OUTPUT_SPECS` — needs a small new spec added to the map.
- `finalize-qc` is hap-gated, multi-file, and calls `run_qv(ctx)` internally when
  a `merquryk` dir is missing — its dry-run branch needs to call the dry-run-aware
  `qv` (once it exists), not the real one.
- `post-processing`/`pp` (two command names, one function) has a real hazard: on
  success it unconditionally calls `RegistryManager().mark_done(ctx.ticket_id)` —
  the **real, non-isolated default registry**, never `dry_run_root()`. A dry-run
  branch must skip this call entirely, not just the `subprocess.run()`.

**Excluded from this rollout:** `add_pretext_view_tracks.py`'s three commands
(`add-bedgraph-track`, `add-gap-track`, `add-telo-track`) mutate an existing
`.pretext` binary file in place via `PretextGraph`, produce no new tracked output,
and have no role in the canonical-FASTA/step-sequencing logic this feature exists
to test. `write_fake_outputs`'s "one new file per glob spec" model doesn't fit an
in-place mutation of an externally-supplied binary, and there's no test-value
payoff. They stay blocked by the existing allowlist mechanism — no code change,
just document the decision in `CLAUDE.md`.

## Global Constraints

(binding on every task below — from `CLAUDE.md` and `TODO/done/45_dry_run_mode.md`'s
established conventions)

- Every dry-run branch goes as early as possible in its function — before ANY real
  subprocess/`_run()`/`_submit_bsub()`/external-tool call, mirroring the six
  existing branches (read `grit/steps/optional/blast_contaminants.py`'s and
  `grit/steps/post_curation/pretext_to_asm.py`'s dry-run branches as the reference
  pattern before writing a new one).
- Async (`_submit_bsub`-based) steps' dry-run branches must NEVER call
  `_submit_bsub()` — write the placeholder output directly into the `run_dir` from
  `ctx.tracker.start(...)` and call `ctx.tracker.finish(..., "success", ...)`
  synchronously instead (same pattern `rename_and_orient`'s dry-run branch
  already uses).
- Use `is_single_hap(ctx)` (`grit/utils/helpers.py`) for any step whose real path
  has hap-gating logic — do not reintroduce a fourth/fifth copy of the literal
  `ctx.hap1_prefix in ("primary", "paternal")` check.
- `log.*` for internal logging, `console.print()` only for curator-facing output.
- Minimal docstrings; no comments referencing this task/ticket.
- Tests use the `mock_ctx`/`mock_ctx_primary` fixtures; no real filesystem/Jira
  access; any test touching `RegistryManager`/`RunTracker` must point them at a
  `tmp_path`, never real `~/.grit`.
- Every command added to `_DRY_RUN_SUPPORTED_COMMANDS`
  (`grit/core/base_command.py`) must use its exact registered Click command-name
  string (e.g. `"fastga-stats"`, not `"fastga_stats"`) — verify against each file's
  `@click.command("...", cls=GritCommand)` decorator before adding it.
- After each task: `uv run pytest tests/ -v` (full suite) and
  `uv run ruff check . && uv run ruff format .` must both be clean before
  committing.
- Do not touch files outside this task's listed scope.

---

## Task 1: Batch — five steps whose `_OUTPUT_SPECS` are already registered

**Scope:** `grit/steps/optional/busco_synteny.py`, `grit/steps/optional/fastga_synteny.py`,
`grit/steps/optional/fastga.py` (the `fastga` command only, not `fastga-stats` —
that's Task 2), `grit/steps/pre_curation/microchromosome_second_shot.py`,
`grit/core/base_command.py` (the allowlist), plus each step's existing test file
(`tests/test_fastga_synteny.py`, `tests/test_fastga.py`, `tests/test_microchromosome.py`
— check whether `busco_synteny` has its own test file or is covered elsewhere before
assuming a filename).

These four steps' `_OUTPUT_SPECS`/`_OUTPUT_SPECS_HAP2` constants are already
registered in `_get_step_specs()`'s `_MAP` (`grit/utils/helpers.py`) — no map
changes needed. Add an early `if ctx.dry_run:` branch to each, following the
established `ctx.tracker.start(...)` → `write_fake_outputs(...)` →
`ctx.tracker.finish(..., "success", outputs=...)` → `print_done(...)` → `return`
shape (all four are `_submit_bsub`-based, so no `_submit_bsub()` call must be
reached).

- `busco_synteny`/`fastga_synteny`: no hap gating, no content realism needed
  (plain stubs — `*.png`/summary files are never content-parsed).
- `fastga`: no hap gating. **Content realism matters**: `fastga-stats`
  (Task 2) parses `*.top1_targets.tsv` as tab-separated `(super, ref_chr, len)`
  rows filtered to names starting `"SUPER_"` — pass a `content=` override with a
  header line plus at least one `SUPER_1\t<chr>\t<len>` row, e.g.
  `b"super\ttop_longest_ref_chr\tlen\nSUPER_1\tchr1\t1000000\n"`.
- `microchromosome_second_shot`: HAS hap gating — the real path computes
  `is_single_hap`/`has_hap2` (currently a hand-rolled literal check) to decide
  whether to build `hap2_argument`. Use the shared `is_single_hap(ctx)` helper in
  the dry-run branch to pop `hap2_large_fa`/`hap2_large_chr`/`hap2_fa`/`hap2_chr_list`
  for single-hap tickets — same pattern as `blast_contaminants`'s dry-run branch.
  Add a `mock_ctx_primary`-based test proving this.

Add `"busco-synteny"`, `"fastga-synteny"`, `"fastga"`, `"microchromosome-second-shot"`
to `_DRY_RUN_SUPPORTED_COMMANDS`.

**Tests:** one test per step confirming `ctx.tracker.get_output(...)` resolves to a
real file and the `_run`/`_submit_bsub` mock was never invoked; the single-hap test
for `microchromosome_second_shot`; a test that `fastga`'s dry-run FASTA/TSV content
is actually parseable by `fastga-stats`'s real `_read_top1_table` (a small
integration check, not just existence).

**Report file:** `.superpowers/sdd/46_dry_run_remaining_steps/task-1-report.md`

---

## Task 2: `hic_remapping` (own task) + allowlist-only additions depending on it

**Scope:** `grit/steps/post_curation/hic_remapping.py`, `grit/core/base_command.py`
(allowlist), plus `tests/test_post_curation.py`/`tests/test_post_curation_recurate.py`
(check which file covers `hic_remapping`'s and the two composites' tests). Depends
on Task 1 landing first only for shared conventions, not files (no overlap).

`hic_remapping` gets its own task because of a real divergence worth reviewing in
isolation: the REAL (non-dry-run) success path **never calls
`ctx.tracker.finish(..., "success")` at all** — only on an exception, or in the
"already done" skip branch. The dry-run branch should still call
`tracker.finish(..., "success", outputs=...)` synchronously (matching every other
async step's dry-run pattern in this codebase), even though that means dry-run's
observable tracker behavior for this one step doesn't byte-for-byte replicate the
real path's. Document this explicitly as a deliberate, reasoned choice in the
commit/report — not a copy-paste oversight.

- `_OUTPUT_SPECS`/`_OUTPUT_SPECS_HAP2` already registered in `_get_step_specs`'s
  `_MAP` — no map change needed.
- Hap gating: the function's own `run_hap1`/`run_hap2` boolean parameters
  (default `run_hap1=True, run_hap2=False`) directly control which haplotype(s)
  to fake — honor them exactly (two independent `tracker.start`/
  `write_fake_outputs`/`tracker.finish` calls, one per requested hap, mirroring
  `rename_and_orient`'s two-call dry-run structure).
- Never call the plain `_run()` this step normally shells out through (it invokes
  `curationpretext.sh`, a nextflow pipeline that submits its own internal LSF
  jobs — short-circuit before any of that).

Once `hic_remapping`'s branch exists, add `"post-curation"` and
`"post-curation-recurate"` to `_DRY_RUN_SUPPORTED_COMMANDS` — both are composites
(`grit/steps/post_curation/post_curation.py`, `post_curation_recurate.py`) that
only call already-dry-run-aware sub-functions (`run_pretext_to_asm`/
`run_haplotig_files`/`run_hic_remapping`, or `run_pretext_to_asm_recurate`/
`run_hic_remapping`) and do no I/O of their own — confirm this by reading both
files, but they should need NO branch of their own, just the allowlist entry.

**Tests:** dry-run tests for `hic_remapping` covering both the `run_hap1`-only and
`run_hap2=True` cases, asserting `_run` was never called and tracker output
resolves; a test invoking the `post-curation`/`post-curation-recurate` CLI commands
(or their underlying functions) end-to-end under `dry_run=True`, asserting every
sub-step's tracked output appears (proving the composite genuinely needs no branch
of its own).

**Report file:** `.superpowers/sdd/46_dry_run_remaining_steps/task-2-report.md`

---

## Task 3: Batch — allowlist-only steps with no branch needed

**Scope:** `grit/core/base_command.py` (allowlist) only, plus a small proof test per
command in whichever existing test file already covers it. No production step-file
changes. Depends on Task 1 (for `fastga`, since `fastga-stats` reads its output) and
Task 2 (for `hic_remapping`, since `haplotig_files` reads `pretext_to_asm`'s output
which is independent, but `validate_files` reads `qv`'s output — see the note below).

Add to `_DRY_RUN_SUPPORTED_COMMANDS`:
- `"fastga-stats"` — synchronous, read-only, no subprocess/tracker call of its
  own; already works correctly against `fastga`'s fake output from Task 1 (its
  content-realism requirement was satisfied there).
- `"haplotig-files"` — synchronous, no external tool call, no tracker call;
  already works correctly against `pretext_to_asm`'s existing fake output
  (confirmed: `pta_curated_fa_exists`'s literal `"hap1"`/`"hap2"` token check
  correctly matches the dry-run FASTA's naming for dual-hap tickets and correctly
  fails for single-hap ones).
- `"validate-files"` — synchronous, read-only, untracked by design. Note: it reads
  `ctx.tracker.get_output("qv", ...)`, so its own dry-run smoke path is only fully
  exercisable once Task 4 (`qv`) lands — but `validate_files` itself needs no code
  change either way; add the allowlist entry now, the "qv output missing" case is
  already handled gracefully (reports MISSING) if run before Task 4.

**Tests:** one CLI-level test per command (via `CliRunner`, following
`tests/test_click_cli.py`'s pattern) confirming `--dry-run <cmd>` no longer raises
`UsageError` and runs to completion; for `fastga-stats`, chain it after a dry-run
`fastga` run and assert it actually prints the fake `SUPER_1` row (proving Task 1's
content-realism choice paid off end-to-end, not just in isolation).

**Report file:** `.superpowers/sdd/46_dry_run_remaining_steps/task-3-report.md`

---

## Task 4: Batch — `super_to_scaffold`, `busco_curated`, `find_reference`, `sex_matcher` (independent local writers)

**Scope:** `grit/steps/optional/super_to_scaffold.py`, `grit/steps/optional/busco_curated.py`,
`grit/steps/pre_curation/find_reference.py`, `grit/steps/pre_curation/sex_matcher.py`,
`grit/utils/helpers.py` (one new `_OUTPUT_SPECS`/map entry, for `super_to_scaffold`
only), `grit/core/base_command.py` (allowlist), plus each step's existing test file.
These four are grouped because each needs its own small, independent fake-writer
with no cross-dependency on each other — same shape of work, different files.

- **`super_to_scaffold`**: currently tracks its output as a raw
  `{"table_csv": str(csv_path)}` dict, not via `_OUTPUT_SPECS`. Add
  `_OUTPUT_SPECS = [("table_csv", "{tol_id}.super_to_scaffold.csv", [])]` (or
  whatever the real filename pattern actually is — read the real path's exact
  `csv_path` construction first) and register it in `_get_step_specs`'s `_MAP` as
  `"super_to_scaffold"`, then use `write_fake_outputs` normally in its dry-run
  branch. Has hap gating (`is_single_hap` check, currently hand-rolled — replace
  with the shared helper as part of this change, not just in the new dry-run
  branch) — read the real path's exact single-hap fallback behavior (it also
  drops hap2 if `find_hap_agp` raises for it) and mirror it.
- **`busco_curated`**: async (`_submit_bsub`). Real output dir
  (`ctx.workdir / f"{tol_id}_busco_singularity"`) is a **sibling of `run_dir`**,
  not inside it — `write_fake_outputs` doesn't fit. Write a small local
  fake-writer that creates that directory directly under `ctx.workdir` with a
  trivial placeholder file inside, then `tracker.finish(..., "success")` with no
  `outputs=` (matching the real path, which also tracks no outputs). No hap
  gating.
- **`find_reference`**: synchronous. Real path never passes `outputs=` to
  `tracker.finish` either — output is discovered later purely by re-globbing
  `run_dir` via `find_reheadered_reference` (`helpers.py`). Dry-run branch: write
  one placeholder `{tol_id}_reheader.fna` directly into `run_dir`, then
  `tracker.finish("success")` with no outputs dict — no `_OUTPUT_SPECS`/map entry
  needed. No hap gating.
- **`sex_matcher`**: async. Has substantial pre-submission idempotency/polling
  logic (tracker history + bjobs check) — place the dry-run branch immediately
  after `print_step_header`, before ANY of that, including the tol_id validation
  check. Write a placeholder `Best_match_1` file directly into `run_dir`,
  `tracker.finish("success")` with no outputs — nothing downstream reads this
  step's output structurally. No hap gating.

Add `"super-to-scaffold"`, `"busco-curated"`, `"find-reference"`, `"sex-matcher"`
to `_DRY_RUN_SUPPORTED_COMMANDS`.

**Tests:** one test per step confirming the placeholder file exists at the
expected real-path location (sibling dir for `busco_curated`, `run_dir` for the
other three) and that `_run`/`_submit_bsub` mocks were never invoked; the
single-hap test for `super_to_scaffold` using `mock_ctx_primary`.

**Report file:** `.superpowers/sdd/46_dry_run_remaining_steps/task-4-report.md`

---

## Task 5: `qv` + `finalize_qc` (finalize_qc depends on qv)

**Scope:** `grit/steps/post_curation/qv.py`, `grit/steps/post_curation/finalize_qc.py`,
`grit/core/base_command.py` (allowlist), plus their existing test files. These two
are grouped because `finalize_qc`'s dry-run branch must call the now-dry-run-aware
`run_qv(ctx)` internally (matching its real behavior of calling `run_qv` when a
`merquryk` dir is missing), so `qv` must land first within this same task.

- **`qv`**: synchronous. Real output lives under
  `ctx.assembly_curated_dir/merquryk/` — **not `run_dir`** — discovered via the
  existing `_find_qv_outputs(ctx)` helper (`qv.py`), not `_OUTPUT_SPECS`. Dry-run
  branch: `mkdir -p` that `merquryk/` dir, write trivial stub `{tol_id}.qv` and
  `{tol_id}.completeness.stats` files into it, then call the REAL
  `_find_qv_outputs(ctx)` to build the outputs dict passed to `tracker.finish`
  (reuse the real helper rather than hand-rolling the same glob). No hap gating.
- **`finalize_qc`**: synchronous, hap-gated (hand-rolled `_IS_SINGLE_HAP` — replace
  with the shared `is_single_hap(ctx)` helper as part of this change), and calls
  `_raise_if_yaml_pta_mismatch(ctx)` (a real-filesystem glob check, today only
  skipped under `ctx.print_only`, not `ctx.dry_run`) before doing anything else.
  Dry-run branch must: skip `_raise_if_yaml_pta_mismatch` entirely, `mkdir`
  `dest_dir` (`ctx.assembly_curated_dir/<tol_id>.<version>/` or whatever the real
  `dest_dir` computation is), write trivial placeholder files for whichever
  haplotype(s) `is_single_hap(ctx)` selects, call `run_qv(ctx)` (now itself
  dry-run-aware) if the real path's "merquryk missing" condition would trigger it,
  and finish with `{"curated_dir": str(dest_dir)}` (the real path's exact outputs
  shape — no `_OUTPUT_SPECS` needed, it's a raw dict).

Add `"qv"` and `"finalize-qc"` to `_DRY_RUN_SUPPORTED_COMMANDS`.

**Tests:** `qv`'s dry-run test confirming `_find_qv_outputs(ctx)` resolves both
files after the dry-run call; `finalize_qc`'s dry-run test (both dual-hap and
`mock_ctx_primary` single-hap cases) confirming the right placeholder files exist
and that calling `finalize_qc`'s dry-run branch actually exercises `qv`'s dry-run
branch too (not the real `run_qv`) — assert via mock that `qv`'s real subprocess
path was never reached.

**Report file:** `.superpowers/sdd/46_dry_run_remaining_steps/task-5-report.md`

---

## Task 6: `post_processing`/`pp` (the registry hazard) + `CLAUDE.md` doc update

**Scope:** `grit/steps/post_curation/post_processing.py`, `grit/core/base_command.py`
(allowlist), `CLAUDE.md`, plus its existing test file. Depends on nothing else in
this plan (independent), but scheduled last since it's the one step with a real
safety hazard worth extra care, and the doc update should describe the final,
complete state of every task above.

`post_processing`/`pp` (two Click command names, one shared Python function) is a
synchronous step that shells to an external Snakemake wrapper via raw
`subprocess.run(["bash"], ...)` (not `_run()`), and — critically — on success
**unconditionally calls `RegistryManager().mark_done(ctx.ticket_id)`, the real,
non-dry-run-isolated default registry**. A dry-run branch placed early (before the
`subprocess.run` call) but naively let the function continue past that call would
still corrupt real registry state.

Fix: place the dry-run branch early enough to skip BOTH the `subprocess.run()`
call AND the `RegistryManager().mark_done(...)` call entirely — call
`ctx.tracker.start(...)` / `ctx.tracker.finish("post_processing", run_dir,
"success")` (no `outputs=` — the real path never passes any either) and `return`
before either real side effect is reached. Add both `"post-processing"` and
`"pp"` to `_DRY_RUN_SUPPORTED_COMMANDS` (they're two distinct Click command
name strings mapping to the same function — `GritCommand.invoke()`'s check is
keyed on `self.name`, so both need their own allowlist entry).

**Tests:** a dry-run test asserting BOTH `subprocess.run` was never called AND
`RegistryManager.mark_done` (mock it, or assert the real ticket's registry entry
status is unchanged using the `tmp_path`-isolated pattern from earlier tasks) was
never invoked — this is the one test in this whole plan that must prove a
*negative real-world side effect* didn't happen, not just that a fake file exists.

Then update `CLAUDE.md`'s `--dry-run` bullet (added in `TODO/done/45_dry_run_mode.md`)
to list the complete, final set of supported commands (all six from Task 45 plus
everything added across Tasks 1-6 here), and explicitly document the
`add_pretext_view_tracks.py` exclusion decision and why (in-place binary mutation,
no tracked output, no role in the canonical-resolution/step-sequencing logic this
feature tests).

**Report file:** `.superpowers/sdd/46_dry_run_remaining_steps/task-6-report.md`
</content>
