# grit — CLAUDE.md

Genome curation pipeline CLI for the Sanger Tree of Life curation team. Wraps HPC job submission (`bsub`), file operations, and external tools behind a consistent interface.

## What it does

Automates pre- and post-curation steps around manual genome assembly curation in PretextView. A curator runs `grit setup -t RC-1234`, curates manually, then runs a chain of post-curation steps (`pretext-to-asm`, `hic-remapping`, `qv`, `finalize-qc`).

## Architecture

### Core pattern: `CurationContext` passed everywhere

`CurationContext` is a frozen dataclass created once from a Jira ticket ID + user config. It holds all parsed YAML fields, computed file paths, and flags (`print_only`). All step functions accept `ctx: CurationContext` and have no global state.

```python
ctx = CurationContext.from_ticket("RC-1234", user_config)
# or for tests / local YAML:
ctx = CurationContext.from_yaml("RC-1234", yaml_data, user_config)
```

**Workdir derivation:** computed from the draft assembly path by replacing `assembly/draft` → `working`, appending `/<username>_curation/<tol_id>/`. No separate `curations_dir` setting.

### Step structure

```
grit/steps/
├── pre_curation/    # setup, pretext tracks, sex-matcher, microchromosome-second-shot, find-reference
├── post_curation/   # pretext-to-asm, haplotig-files, hic-remapping, microchromosome-combine, qv, validate, finalize-qc
└── optional/        # blast-contaminants, busco-curated, busco-synteny, fastga, rename-and-orient
```

Each step file exports:
- A plain function (`setup_curation(ctx)`) — usable from Python/notebooks
- A Click command (`setup_cmd`) — registered in `click_cli.py`

### Command execution

All shell commands go through `_run(cmd, print_only)` in `grit/utils/helpers.py`. When `print_only=True`, commands are printed but not executed — enables dry-run mode via `--print-only` flag.

`bsub` jobs are submitted via `_submit_bsub()` → `_run()`. Job IDs are parsed and logged; execution is non-blocking (fire-and-forget).

**Tracking true completion of fire-and-forget bsub jobs:** `_state_update_epilogue()` builds a `bsub -Ep '...'` epilogue command that calls the hidden `grit _state-update --workdir --step --run-dir --status` CLI command; LSF runs it automatically when the job finishes, using `$LSB_JOBEXIT_STAT` to report success/failure. `_state-update` re-globs the run_dir for that step's `_OUTPUT_SPECS` and calls `RunTracker.finish()` with the real outputs — so the tracker's "success" only ever reflects verified on-disk state, not just "the submission succeeded." Every step that calls `_submit_bsub()` should pass this as `epilogue_cmd` (see `fastga.py`, `busco_synteny.py`, `rename_and_orient.py`). This mechanism only works when grit's own `bsub` call is the thing LSF is tracking — if a step instead shells out to an external script that submits (or backgrounds) its own async work internally, grit never sees a job it can attach an epilogue to, and the step's tracked status can go "success" long before the real work finishes.

Any step that shells out to an external script/pipeline should `cd {run_dir} && ...` before invoking it, even when the tool also takes an explicit output-dir flag — nextflow pipelines (e.g. `curationpretext`) always write `.nextflow.log`/`work/`/`.nextflow/` into the invoking cwd regardless of other flags, and `cd`-ing first keeps stray files out of wherever grit happened to be run from. See `fastga.py`, `hic_remapping.py`, `find_reference.py`, `sex_matcher.py` for the pattern.

**Synchronous (non-bsub) tracked steps:** most tracked steps submit a bsub
job and rely on `_state_update_epilogue` to report completion later. A step
that does real work synchronously in-process (e.g. `fastga-stats`, which
runs a fast local PAF-parsing script rather than an HPC job) skips
`_submit_bsub`/`_state_update_epilogue`/`record_job` entirely: call
`ctx.tracker.start(step, ...)`, do the work via `_run()` (so `print_only`
is still respected), then call `ctx.tracker.finish(step, run_dir, "success",
outputs=...)` directly once the work is done. See `run_fastga_stats` in
`grit/steps/optional/fastga.py`. Because there's no bsub epilogue and no
`job_id` for this kind of step, `grit status`'s bjobs-based recovery for
stuck "started" rows can never apply to it — the step must wrap its
post-`start()` work in try/except and call `ctx.tracker.finish(step, run_dir,
"failed", untracked=ctx.untracked)` itself on any failure (a script error,
or a "success" exit that produced none of the expected outputs), then
re-raise, or a crash strands the record as "started" forever with no
recovery path but `grit untrack`.

### HPC module loading

`grit/utils/modules.py` centralises all `module load` version strings in `MODULE_VERSIONS`. Step functions call `module_cmd("TOOL_KEY")` to get the shell fragment `". /etc/profile.d/modules.sh && module purge && module load <module>"`. Updating a tool version = changing one line in `modules.py`.

### CLI

Built with `rich-click`. Entry point: `grit/core/click_cli.py`.

```
grit [--yaml FILE] [--print-only] [--logging-level LEVEL] <COMMAND> -t RC-1234
```

`GlobalState` carries shared flags; `build_context()` constructs `CurationContext` from it. `GritCommand` (in `base_command.py`) is a shared Click base class that auto-injects `--ticket / -t`.

External config: `~/.grit/grit_curation_config.yaml` (not committed) — run `grit init` to create it pre-filled with your username; the global ticket registry lives alongside it in the same `~/.grit/` dir. In tests / CI use `--yaml` with a local fixture file.

## Key conventions

- **`--untracked`** — for steps that thread `ctx.untracked` through, every
  `ctx.tracker.finish(...)` call for that run (including the bsub `-Ep`
  epilogue path, via `_state_update_epilogue(..., untracked=ctx.untracked)`)
  must also pass `untracked=ctx.untracked`. `RunTracker.finish()` writes
  `status="untracked"` instead of the given success/failed when `untracked=True`
  — omitting it there lets the finish record silently overwrite the untracked
  marker with `success`/`failed`, making the run canonical the moment it
  completes (the exact bug fixed in `TODO/tiny.md`). Outputs are still
  recorded on an untracked finish, so `grit retrack -t <ticket> -s <step>` can
  later promote the run to canonical using its own recorded outputs.
- **No global state** — everything flows through `ctx`
- **`print_only` everywhere** — every step respects `ctx.print_only`; `_run()` enforces it
- **`--dry-run`** — a separate mode from `print_only`, for exercising step-sequencing/
  tracking/canonical-resolution logic through the real CLI without HPC/NFS access.
  `ctx.dry_run` isolates the registry, every ticket's workdir, and
  `ctx.assembly_curated_dir` under `~/.grit/dry_run/` (see `dry_run_root()` in
  `grit/core/registry.py`) — never the real `~/.grit/grit_registry.json`, a real
  farm workdir, or the real curated-release directory — and each supporting step
  writes placeholder outputs via `write_fake_outputs()` (`grit/utils/helpers.py`,
  or a small local writer for steps whose real output isn't tracked via
  `_OUTPUT_SPECS`) instead of running any real command. `--print-only` always
  takes precedence over `--dry-run` when both are set — resolved once in
  `CurationContext.from_yaml` (`dry_run = dry_run and not print_only`) and
  independently in `GritCommand.invoke()`'s pre-callback guard, since that check
  runs before a `CurationContext` exists.

  `setup`, `pretext-to-asm`, `blast-contaminants`, `rename-and-orient`,
  `microchromosome-combine`, `pretext-to-asm-recurate`, `busco-synteny`,
  `fastga-synteny`, `fastga`, `microchromosome-second-shot`, `hic-remapping`,
  `fastga-stats`, `haplotig-files`, `super-to-scaffold`, `busco-curated`,
  `find-reference`, `sex-matcher`, `qv`, `finalize-qc`, `post-processing`
  (aliased as `pp`), `post-curation`, and `post-curation-recurate` have a
  dry-run branch (`_DRY_RUN_SUPPORTED_COMMANDS` in `grit/core/base_command.py`).
  `GritCommand.invoke()` refuses `--dry-run` up front for every other (not yet
  ported) step with a `UsageError`. `status`/`untrack`/`retrack` support `--dry-run` as a
  group-level flag (`grit --dry-run status -t <ticket>`, never per-command); the
  other plain `@cli.command`s (`done`/`reopen`/`remove`/`summary`/`cleanup`)
  have no dry-run support and raise `UsageError` if `--dry-run` is passed, since
  they mutate the real registry/workdir. Reset the sandbox with
  `rm -rf ~/.grit/dry_run`. See `tests/local_smoke_test.sh`'s dry-run section
  for a real chained example.

  `validate-files` is allowlisted in `_DRY_RUN_SUPPORTED_COMMANDS` for when it's
  eventually registered on the CLI group, but its Click command is currently
  commented out in `click_cli.py` (pre-existing, unrelated gap) — `grit
  validate-files`/`grit --dry-run validate-files` are not reachable today.

  `add_pretext_view_tracks.py` deliberately has no dry-run branch and is not in
  `_DRY_RUN_SUPPORTED_COMMANDS` — it mutates a `.pretext` binary in place, has
  no tracked output to fake, and plays no part in the canonical-resolution/
  step-sequencing logic this feature exists to exercise.

  Per-step design rationale and historical context for each dry-run branch
  lives in `TODO/done/45_dry_run_mode.md` and `TODO/46_dry_run_remaining_steps.md`,
  not here.
- **`is_single_hap(ctx)`** (`grit/utils/helpers.py`) — true for a `primary`/`paternal`
  (single-hap) assembly; the shared check for gating hap2-fabrication bugs, used by
  `pretext_to_asm`, `blast_contaminants`, `microchromosome_combine`,
  `super_to_scaffold`, `microchromosome_second_shot`, and `finalize_qc` (in both
  their dry-run branches and their real paths).
- **`require_workdir(ctx)`** — guards steps that need an existing workdir; skipped in print_only mode
- **`log.*` not `print()`** — use Python `logging`; `RichHandler` formats output
- **Minimal docstrings** — one line stating what the function returns/does, only
  what's necessary and sufficient. No multi-paragraph docstrings, no restating
  the implementation, no historical context about bugs/commits that motivated
  it (that belongs in the commit message, not the code)
- **`console.print()`** for structured step output (headers, tips, done messages) via `grit/utils/output.py`
- **Assembly type detection** — `_detect_assembly_type(yaml_data)` maps YAML keys to `(assembly_type, hap1_prefix, hap2_prefix)`: `hap1/hap2`, `primary/alternate`
- **Canonical FASTA priority** — `find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs`
  (`grit/utils/helpers.py`) resolve "the current canonical assembly" per haplotype from a single flat,
  mtime-ordered pool of tracker steps (`pretext_to_asm`, `microchromosome_combine`,
  `blast_contaminants`, `rename_and_orient[_hap2]`, `pretext_to_asm_recurate[_hap2]`) — the freshest
  existing tracked output wins outright, with a filesystem fallback when nothing is tracked. See
  `recuration-canonical-priority.md` for the full curator-facing decision path and a flowchart — read
  it before touching any of these three functions or the recurate step. `grit status -t`'s step-history
  table surfaces this per row via a "Canonical" column showing per-type codes (`fa`/`hap`/`chr`), with a
  `(1)`/`(2)` haplotype-index suffix when a ticket has more than one haplotype — e.g. a recurate row can
  read `hap(1),chr(1)` while a later rename-and-orient row reads `fa(1)`, making clear they're each
  canonical for a *different* output, not in conflict
- **`GritJiraIssue`** is a shared server library injected via `sys.path` (path in user config), not a pip dependency

## Planning / design docs

Design docs and implementation plans for non-trivial changes live in
`TODO/<number>_<slug>.md` (next number = highest existing + 1), with
`## Problem` / `## Design` sections — see `TODO/38_busco_shared_step.md` for
the reference format. Small one-off fixes go in `TODO/tiny.md` instead of
getting their own file. Move a file to `TODO/done/` once implemented. Do not
use `docs/superpowers/specs/`.

When a finished task changes the architecture (new pattern, new shared
helper, a convention this file documents becoming outdated), update this
CLAUDE.md as part of that same task, not later — it has drifted out of date
before from changes that weren't reflected back here.

## Dev

```bash
uv sync
pytest tests/ -v
ruff check . && ruff format .
```

Tests use `mock_ctx` fixture (from `tests/conftest.py`) — builds `CurationContext` from fixture YAML files in `tests/fixtures/`, no Jira or filesystem access. Functions calling `subprocess` / `bsub` are mocked; tested via call inspection.
