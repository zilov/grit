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

All shell commands go through `_run(cmd, print_only)` in `grit/utils/helpers.py`. When `print_only=True`, commands are printed but not executed — enables dry-run mode via `--print-only` flag. A captured command that fails raises `CommandError` (a `CalledProcessError` subclass, so existing `except` clauses still match) whose message ends with the tail of the tool's stderr, and the same tail is logged at error level — so the curator sees the tool's own diagnostic, not just an exit code. Callers that parse the return value get stdout only; stderr never leaks into it. `_run(..., timeout=seconds)` runs the command in its own process group and kills the whole group (shell and children) on expiry, raising `TimeoutExpired`; the default is no timeout, because the synchronous `_run` calls include multi-GB copies to NFS and tools whose runtime scales with the assembly, and a wrong default would kill real work. Never put a timeout on a `bsub` submission.

`bsub` jobs are submitted via `_submit_bsub()` → `_run()`. Job IDs are parsed (`Job <N> is submitted`) and logged; execution is non-blocking (fire-and-forget). If bsub exits 0 without that line, `_submit_bsub` raises `BsubSubmissionError` rather than return anything — only a numeric job ID may ever reach `record_job()`/the registry, since a non-numeric one reads as `gone` to `bjobs`.

**Tracking true completion of fire-and-forget bsub jobs:** `_state_update_epilogue()` builds a `bsub -Ep '...'` epilogue command that calls the hidden `grit _state-update --workdir --step --run-dir --status` CLI command; LSF runs it automatically when the job finishes, using `$LSB_JOBEXIT_STAT` to report success/failure; when that is unset or non-numeric the epilogue calls nothing, so the run stays `started` for the bjobs sweep. The grit it calls is `sys.argv[0]` made absolute, or `grit` from `$PATH` when argv[0] isn't an executable (e.g. a `.py`); every argument is `shlex`-quoted and `_submit_bsub` quotes the whole `-Ep` string the same way, so workdirs with spaces or quotes survive. `_state-update` re-globs the run_dir for that step's `_OUTPUT_SPECS` and calls `RunTracker.finish()` with the real outputs. **`success` requires outputs:** a job LSF reports as exit 0 is recorded `success` only when `finished_run_outputs()` (`grit/utils/helpers.py`) calls the run complete — `STEP_MANIFESTS` via `verify_outputs()` where the step has a manifest, else any `_OUTPUT_SPECS` match, the same criterion `_resolve_gone_job` uses. When it doesn't, `_state-update` writes nothing and the run stays `started` (with its `job_id`), so the next `grit status` bjobs sweep re-checks it; it is *not* marked `failed`, because an exit-0 job with missing outputs is not evidence of failure and `failed` is terminal. A new epilogue step therefore needs `_OUTPUT_SPECS` or a manifest entry, or it can never succeed. Every step that calls `_submit_bsub()` must pass this as `epilogue_cmd`, and must wrap the submission and its `record_job()` in a try/except that calls `finish(step, run_dir, "failed", untracked=ctx.untracked)` and re-raises — a rejected submission leaves no job for the epilogue or bjobs to resolve, so it would strand the `started` record (see `fastga.py`, `busco_synteny.py`, `rename_and_orient.py`). `tests/test_bsub_submission.py` enforces both for every call site under `grit/steps/`. This mechanism only works when grit's own `bsub` call is the thing LSF is tracking — if a step instead shells out to an external script that submits (or backgrounds) its own async work internally, grit never sees a job it can attach an epilogue to, and the step's tracked status can go "success" long before the real work finishes So when a tool ships as a wrapper that issues its own `bsub`, bypass the wrapper and submit what it runs: `hic_remapping.py` submits `grit/scripts/curationpretext.sh` (the module's wrapper minus its own `bsub`, same resources) so the nextflow head job is grit's job. The script resolves `main.nf` *inside the job* from the module-loaded wrapper (`grep` on `$(command -v curationpretext.sh)`) so version bumps stay in the `grit` module, never pinned in grit. Keep job-side shell logic in such a repo script, not inline in `inner_cmd`: `_submit_bsub` wraps `inner_cmd` in double quotes, so inline `$VAR`s need `\$` escaping and the printed command becomes unreadable. A nextflow head exits 0 only when the whole pipeline completed, so the epilogue's `$LSB_JOBEXIT_STAT` is the completion signal. A step that skips resubmission because a prior run exists must treat a latest record of `started` as in flight — report it and return — and never `finish()` it from outputs that may still be mid-write.

**Reconciling bsub jobs via `bjobs` (`_check_bjobs` → `_refresh_pending_jobs` →
`_resolve_gone_job`):** the fallback for runs whose epilogue never fired, and
for runs submitted without one — chiefly `hic_remapping` records from before it
owned its job (its `bsub` was then issued by `curationpretext.sh`). `_check_bjobs`
returns three kinds of answer and they must stay distinct: an LSF state,
`"gone"` (LSF explicitly answered `Job <N> is not found`, parsed from stderr)
and `"unknown"` (LSF could not be asked — no `bjobs`, an LSF library error).
Only the first two are evidence. `"gone"` is evidence *about the cluster that
was queried*: a job submitted from another cluster reads exactly the same way,
which is why `start()` records `cluster` (`lsf_cluster()`, from `LSF_ENVDIR`)
on every run. The rule `_resolve_gone_job` applies, and any new reconciliation
path must apply too: **output files on disk promote a run to `success` from any
host; their absence marks it `failed` only when the job's recorded cluster is
the one queried.** Records written before `cluster` existed have none, so they
are never auto-failed. Completion itself is judged by `STEP_MANIFESTS` via
`verify_outputs()` (the same criterion `grit status`'s table uses), falling back
to "any `_OUTPUT_SPECS` match" only for steps with no manifest entry.

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
recovery path but `grit untrack`. `qv` is the same kind of step:
`kmer_completeness.bash` blocks on its own `bsub -K` MerquryFK job but exits 0
whatever that job did, so `run_qv` judges completion by the `.qv` and
`.completeness.stats` files in `merquryk/`, never by the wrapper's exit status.

### HPC module loading

`grit/utils/modules.py` centralises all `module load` version strings in `MODULE_VERSIONS`. Step functions call `module_cmd("TOOL_KEY")` to get the shell fragment `". /etc/profile.d/modules.sh && module purge && module load <module>"`. Updating a tool version = changing one line in `modules.py`.

### CLI

Built with `rich-click`. Entry point: `grit/core/click_cli.py`.

```
grit [--yaml FILE] [--print-only] [--logging-level LEVEL] <COMMAND> -t RC-1234
```

`GlobalState` carries shared flags; `build_context()` constructs `CurationContext` from it. `GritCommand` (in `base_command.py`) is a shared Click base class that auto-injects `--ticket / -t`.

### Onboarding: `grit tutorial`

`grit tutorial` is the guided walkthrough new curators start with. The engine is
`grit/core/tutorial.py`; the lesson and scenario prose lives in
`grit/core/tutorial_lessons.py`, with one bundled fictional ticket YAML,
`grit/config/tutorial_demo.yaml` (hap1/hap2) — every scenario shares it, single-hap
tickets are only mentioned in tutorial 0's text, not modelled with a second
fixture. Every scenario after tutorial 0 never touches Jira, LSF, lustre or the
real registry — every command runs through grit's own CLI in-process
(`cli.main(..., standalone_mode=False)`) with `--config`/`--yaml`/`--dry-run`
injected, so a step is never re-implemented and a renamed command breaks the
tutorial loudly instead of teaching a stale interface.

Six scenarios, in `SCENARIOS` (`grit/core/tutorial_lessons.py`), selected with
`grit tutorial --scenario <key>`:

- `overview` — tutorial 0, no ticket, no commands to type (see below).
- `basic` (easy) — tutorial 1: `setup`, `pretext-to-asm`, `hic-remapping`, `qv`,
  `finalize-qc`, then `pp` with a global `grit status` before and after it.
- `references` (medium) — tutorial 2: `find-reference`, `busco-synteny`,
  `fastga`/`fastga-stats`, `super-to-scaffold`, then a hand re-curation and
  `post-curation`.
- `canonical-changes` (hard) — tutorial 3: `microchromosome-second-shot` +
  `microchromosome-combine`, `blast-contaminants`, `find-reference --local`,
  `rename-and-orient`.
- `recurate` (medium) — tutorial 4: `post-curation` then
  `post-curation-recurate` per haplotype.
- `other` (medium) — tutorial 5: `sex-matcher`, `blast-contaminants --untracked`,
  a `rename-and-orient` run that comes out wrong, `grit untrack` to back it out,
  then a corrected `rename-and-orient --mapping-table` redo.

#### Tutorial 0 — the one non-sandboxed scenario

Tutorial 0 has no ticket and nothing to type: five text screens (built with
`_read()` in `tutorial_lessons.py`, each a `manual_action` that just waits for
Enter) covering what happens to an assembly before curation, assembly types,
what a curator does, what grit is, and how it works. It has no sandbox to
reset and no `--dry-run` in its base args, so `Scenario` carries one more field
for it: `is_overview: bool = False`. `run_scenario()` checks it to skip the
usual `_reset_sandbox()` + `--dry-run` base setup. The overview ends with a
closing panel generated from `SCENARIOS` listing the `--scenario` flag for each.

Tutorial 1 has the learner type `grit status` with no ticket ("the global
view") just before and just after `pp`. Those lessons set
`needs_ticket=False`, so the expected answer carries no `-t` and `hint_for()`
says "drop -t" instead of "add -t". With the tutorial's `--yaml` injected,
plain `status` still shows the global view (only `GritCommand` steps derive a
ticket from the YAML filename). So `manual_action` has two uses — a text
screen, and "you press Enter once you've done a real-world action" — the
dataclass field doesn't distinguish them, only the callable's body does.

#### Typed lessons (tutorials 1-5)

The learner **types** each command; the lesson advances only on a match.
`parse_command()` normalises both sides to `(subcommand, ticket, flags)` — short
aliases expanded, `--dry-run` ignored, every option that takes a value (read from the click commands by `_value_opts()`, so a new one never needs listing) keeping it — and
`hint_for()` names the actual fault. Both are pure string logic and are
unit-tested in `tests/test_tutorial.py`, which also asserts that every typed
lesson names a registered command and explains every flag it demands.

`_safe_to_run()` is the safety rule and the non-obvious part: a command that
isn't the answer is executed only if it's `--help` or `grit status` for this
scenario's ticket. Another *step* is refused because running it would
invalidate the next lesson's "run status and find X" claim, and a missing
`--ticket` is refused because the tutorial's own `--yaml` would otherwise make
`GritCommand` derive a ticket from the YAML filename instead of failing.
`grit init` is refused explicitly — it's the one command that writes real state
without consulting `dry_run`.

`--auto` runs each lesson's expected command (plus its status check)
unprompted, `--scenario <key>` picks one chain and `--all` runs them all;
Scenario 5 of `tests/local_smoke_test.sh` drives each scenario separately and
asserts its final canonical table, so a `check` line that stopped being true
fails there — except `overview`, which it also runs (for parity with `--all`)
but only checks for the closing scenario list, since there is no canonical
table without a ticket. Design rationale: `TODO/done/53_tutorial_walkthrough.md`,
`TODO/done/54_tutorial_interactive.md` and `TODO/done/55_tutorial_curriculum.md`.

Before running a matched lesson's command for real under `--dry-run`,
`_show_farm_preview()` first runs the identical command in-process with
`--print-only` added (`_print_only_base()`), captures only what it prints
via `console.capture()`, and shows it under a "What this runs on the farm:"
heading — the one thing a learner otherwise never sees. `--dry-run` stays in,
so the step prints its real commands but resolves every input against the
sandbox's state (see `--dry-run` below) — without it, print-only would look up
the tutorial ticket in the real registry and fail on the first missing input.
Logging is muted for its duration (`logging.disable`), and `_run_grit()`
already swallows any exception. The capture is already-rendered ANSI, so it is
re-printed via `Text.from_ansi()`, never as a markup string (that mangles the
escape codes). It is shown only when it contains a printed `Command`;
otherwise it falls back to the lesson's own `shows` string, or skips the
heading silently if that is also empty. When a preview was shown,
`_run_lesson_command()` runs the real dry-run pass with INFO logging muted and
its output captured, drops the `print_step_header` panels (`_drop_step_headers`)
and its `Done:` lines, and prints what is left (e.g. the fastga-stats and
super-to-scaffold tables) — otherwise every header and log line appears twice.

The placeholder AGP the tutorial writes has ten SUPERs, and pretext-to-asm's
dry-run builds its chromosome list from the sandbox's latest AGP, naming a SUPER
by the painted tag after its `+` column. Tutorial 2's first AGP
(`_AGP_MANUAL_LESSON_UNTAGGED`) has no tag, so `grit status` shows 10 autosomes;
the re-curation AGP paints SUPER_7 as X (9 autosomes, XX), matching the
fastga-stats and super-to-scaffold example tables. The preview runs only for
`GritCommand` steps: plain `@cli.command`s (`status`, `untrack`, `retrack`)
ignore `--print-only` and would write the registry. Three lessons need
`shows`: `untrack` (a direct registry edit, no shell command), `super-to-scaffold` (runs locally,
submits nothing) and `sex-matcher` (refuses the tutorial's non-insect ToL ID
under `--print-only`; its dry-run branch skips that check).

A `Lesson` with `manual_action` set (a `Callable[[str], None]` taking the
ticket ID) has no command to type. Most uses are a real-world action with no
grit command — `_copy_agp_into_workdir` writes the placeholder AGP a curator
would have `scp`'d in — but tutorial 0's text screens reuse the same field for a screen that just
waits for Enter (see above). `_run_lesson()` handles these in the same loop: it explains the
action, waits for a bare Enter via the shared `_ask()` idiom,
then calls `manual_action(ticket)` before moving on — there is no
typed-command matching/hint machinery for these. `_run_scenario_auto()` runs
the action unprompted, matching how it runs a normal lesson's command.

`Scenario.outro`, when set, adds scenario-specific tips to the closing
"Scenario finished" panel (tutorial 1 uses it for the `post-curation` and
finalize-qc-runs-qv shortcuts).

`Scenario.difficulty` is shown in `_choose_scenario()`'s menu next to the
title when non-empty; tutorials 1-5 carry real easy/medium/hard values per the
curriculum above, tutorial 0 leaves it unset (it isn't difficulty-rated).

External config: `~/.grit/grit_curation_config.yaml` (not committed) — run `grit init` to create it pre-filled with your username; the global ticket registry lives alongside it in the same `~/.grit/` dir. In tests / CI use `--yaml` with a local fixture file.

### Registry durability

`RegistryManager` is the only record of step history and is written from every
login *and* compute node over NFS, so `grit/core/registry.py` is deliberately
defensive and must stay that way:

- **Reads fail closed.** An existing but unparseable registry raises
  `RegistryError` (a `ClickException`, so the curator sees a message, not a
  traceback). Never make `_load()` return `[]` on a read error — an empty read
  followed by any write erases every ticket and all step history.
- **Every write keeps the version it replaces**: `grit_registry.json.bak`, plus a
  once-a-day `grit_registry.<date>.json` snapshot (last `SNAPSHOT_RETENTION`
  kept). The `RegistryError` message lists them as `cp` commands.
- **All writes go through `_atomic_write()`**, which installs via a temp file
  named for the writing host and pid (never a shared `grit_registry.tmp`) and
  chmods 0600. Add new registry-adjacent files through it too.

Concurrent read-modify-write can still lose a record; serialising that is a
storage-format decision (`CORR-02`), not something to improvise per call site.

## Key conventions

- **`--untracked`** — injected into every step by `GritCommand` (same as
  `-t`/`--print-only`); all `tracker.start()` call sites pass
  `untracked=ctx.untracked`. Every
  `ctx.tracker.finish(...)` call for that run (including the bsub `-Ep`
  epilogue path, via `_state_update_epilogue(..., untracked=ctx.untracked)`)
  must also pass `untracked=ctx.untracked`. `RunTracker.finish()` writes
  `status="untracked"` instead of the given success/failed when `untracked=True`
  — omitting it there lets the finish record silently overwrite the untracked
  marker with `success`/`failed`, making the run canonical the moment it
  completes (the exact bug fixed in `TODO/tiny.md`). Outputs are still
  recorded on an untracked finish, so `grit retrack -t <ticket> -s <step>` can
  later promote the run to canonical using its own recorded outputs. The
  recovery paths that finish *without* `untracked` (`_refresh_pending_jobs`,
  `_resolve_gone_job`, `status`'s bjobs fallback, `sex_matcher`'s resubmit
  guard) only act on records with `status="started"`, which an untracked run
  never has — for the same reason `record_job()` finds nothing to patch, so an
  untracked bsub run stores no `job_id` and can't be recovered via bjobs.
  The resolvers' filesystem fallbacks honour the marker too: `find_latest_dir()`
  never returns a run dir whose latest record is `untracked` (for any caller), so
  an `--untracked` run cannot become canonical just by being the newest dir on disk.
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
  runs before a `CurationContext` exists. The paths still follow `--dry-run`:
  with both flags a step fakes nothing and prints its real commands, resolved
  against the sandbox's workdir/registry/curated dir (the tutorial's farm
  preview relies on this).

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
  other plain `@cli.command`s (`done`/`reopen`/`remove`/`cleanup`)
  have no dry-run support and raise `UsageError` if `--dry-run` is passed, since
  they mutate the real registry/workdir. Reset the sandbox with
  `rm -rf ~/.grit/dry_run`. See `tests/local_smoke_test.sh`'s dry-run section
  for a real chained example.

  `add_pretext_view_tracks.py` deliberately has no dry-run branch and is not in
  `_DRY_RUN_SUPPORTED_COMMANDS` — it mutates a `.pretext` binary in place, has
  no tracked output to fake, and plays no part in the canonical-resolution/
  step-sequencing logic this feature exists to exercise.

  Per-step design rationale and historical context for each dry-run branch
  lives in `TODO/done/45_dry_run_mode.md` and `TODO/done/46_dry_run_remaining_steps.md`,
  not here.
- **`is_single_hap(ctx)`** (`grit/utils/helpers.py`) — true for a `primary`/`paternal`
  (single-hap) assembly; the shared check for gating hap2-fabrication bugs, used by
  `pretext_to_asm`, `blast_contaminants`, `microchromosome_combine`,
  `super_to_scaffold`, `microchromosome_second_shot`, and `finalize_qc` (in both
  their dry-run branches and their real paths). All five canonical resolvers
  (`find_curated_fa`, `find_canonical_{fa,haplotigs,chr_list,map}`) raise
  `FileNotFoundError` for `ctx.hap2_prefix` on a single-hap ticket via
  `_refuse_missing_hap2()` — their alias/no-prefix fallbacks would otherwise
  hand back hap1's file as `alternate`'s — and `refuse_hap2_on_single_hap()`
  makes `hic-remapping --hap2` / `rename-and-orient --hap2` a `UsageError`
  before anything is started or submitted.
- **`--hap2` means hap1 *and* hap2** on `hic-remapping`, `post-curation` and
  `rename-and-orient` (without it, hap1 only). The recurate commands
  (`pretext-to-asm-recurate`, `post-curation-recurate`) are the exception: there
  `--hap2` means hap2 *instead of* hap1, since each haplotype is recurated from its
  own AGP. `hic_remapping._skip_hap()` skips a haplotype (real and dry-run paths
  alike) whose latest run is still `started` — unless that run's map already
  predates the canonical FASTA — or whose `find_canonical_map()` is newer than its
  `find_canonical_fa()`, so `--hap2` after a hap2-only change remaps only hap2.
  `post-curation` and `post-curation-recurate` call `run_hic_remapping(...,
  fresh_fasta=True)`, which drops the up-to-date check (not the in-flight one):
  they have just rebuilt the FASTA, and under `--print-only` that FASTA doesn't
  exist yet, so the check would wrongly skip the remap.
- **`require_workdir(ctx)`** — guards steps that need an existing workdir; skipped in print_only mode
- **`log.*` not `print()`** — use Python `logging`; `RichHandler` formats output
- **Minimal docstrings** — one line stating what the function returns/does, only
  what's necessary and sufficient. No multi-paragraph docstrings, no restating
  the implementation, no historical context about bugs/commits that motivated
  it (that belongs in the commit message, not the code)
- **`console.print()`** for structured step output (headers, tips, done messages) via `grit/utils/output.py`
- **Assembly type detection** — `_detect_assembly_type(yaml_data)` maps YAML keys to `(assembly_type, hap1_prefix, hap2_prefix)`: `hap1/hap2`, `primary/alternate`. A YAML with `paternal`/`maternal` keys is recognised but not supported: it raises `UnsupportedAssemblyTypeError` (`grit/core/context.py`, a `click.ClickException`) at context build with a clear message, rather than the generic "Cannot detect assembly type" `ValueError` an unrecognised key set gets, or silently mishandling a trio assembly. The `paternal`/`maternal` branches still present elsewhere (`helpers.py`'s `_PTA_ALIASES`, `is_single_hap`, a few step files) are dead code that can never be reached while detection rejects those keys — real trio support needs both sides done together.
- **Canonical FASTA priority** — `find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs`/`find_canonical_map`
  (`grit/utils/helpers.py`) resolve "the current canonical assembly" per haplotype from a single flat,
  mtime-ordered pool of tracker steps (`pretext_to_asm`, `microchromosome_combine`,
  `blast_contaminants`, `rename_and_orient[_hap2]`, `pretext_to_asm_recurate[_hap2]` — each `_hap2`
  step only in hap2's pool and its unsuffixed twin only in hap1's, via `_rename_and_orient_step_name()`
  / `_recurate_step_name()`, never by relying on output keys differing) — the freshest
  existing tracked output wins outright, with a filesystem fallback when nothing is tracked — that
  fallback skips run dirs the tracker marks `untracked` or still `started`
  (`find_latest_dir(..., settled_only=True)`, `_settled_matches()`), so it only ever sees dirs the
  tracker has no opinion on or has seen finish. A step
  whose latest successful run recorded no matching output key is not dropped from that comparison:
  `_step_output()` re-globs that run dir with the step's `_OUTPUT_SPECS` first, so a run with
  incompletely recorded outputs can't hand canonical back to an older step (canonical must never move
  backwards in time). The recorded output comes from `RunTracker.get_output()`, which reads only the
  step's latest successful run (any of that run dir's success records) and returns None rather than
  let an older run of the same step stand in — otherwise the re-glob never fires (report 06 T2). Only
  a *finished* run competes: `_step_output` asks for
  `latest_run_dir(step, include_started=False)`, because a `started` run is a bsub job that may still
  be writing the file (report 06 T3); the default `include_started=True` stays for callers that need
  to see in-flight runs (resubmit guards, `untrack`, `cleanup`). See
  `docs/recuration-canonical-priority.md` for the full curator-facing decision path and a flowchart — read
  it before touching any of these four functions or the recurate step. `grit status -t`'s step-history
  table surfaces this per row via a "Canonical" column showing per-type codes (`fa`/`hap`/`chr`/`map`), with a
  `(1)`/`(2)` haplotype-index suffix when a ticket has more than one haplotype — e.g. a recurate row can
  read `hap(1),chr(1)` while a later rename-and-orient row reads `fa(1)`, making clear they're each
  canonical for a *different* output, not in conflict. `_canonical_mark()` marks a row for a canonical
  file found in that row's run dir even when the run's recorded `outputs` never captured it, so the
  column can't disagree with the canonical-files table above it (that re-glob matches a canonical file
  anywhere under the run dir, since `hic_remapping` writes its map into a `pretext_maps_processed/`
  subdir rather than the run dir itself). `find_canonical_map` is the odd one out in that pool: its
  pool is a single step per haplotype (`hic_remapping` / `hic_remapping_hap2`) and it resolves each
  haplotype only from that haplotype's own step and output key (`hap{1,2}_normal_pretext`) — no alias
  or no-prefix fallback, because handing hap1's file back for hap2 here means publishing the wrong
  haplotype's Hi-C map to NFS. Only `*normal.pretext` is canonical; the `hr.pretext` beside it is the
  curation input and stays on the farm, and `setup`'s staged draft map never counts. Its consumers are
  `finalize_qc`'s NFS copy and `grit status`'s download tip
- **`GritJiraIssue`** is a shared server library injected via `sys.path` (path in user config), not a pip dependency

## Planning / design docs

Design docs and implementation plans for non-trivial changes live in
`TODO/<number>_<slug>.md` (next number = highest existing + 1), with
`## Problem` / `## Design` sections — see `TODO/done/38_busco_shared_step.md` for
the reference format. Small one-off fixes go in `TODO/tiny.md` instead of
getting their own file. Move a file to `TODO/done/` once implemented. Do not
use `docs/superpowers/specs/`.

When a finished task changes the architecture (new pattern, new shared
helper, a convention this file documents becoming outdated), update this
CLAUDE.md as part of that same task, not later — it has drifted out of date
before from changes that weren't reflected back here.

## Where this runs: laptop vs farm

grit is developed in two places and the difference decides what can actually be
verified.

**Laptop (macOS, `~/github/grit`)** — no LSF, no lustre, no Jira. Only
`pytest`, `ruff`, `--print-only` and `--dry-run` work here. Any claim that a
real step "works" cannot be made from the laptop: `--print-only` proves the
command string is well formed, `--dry-run` proves the sequencing/tracking logic
holds, neither proves the tool runs.

**Farm (`ssh farm22-agentic1`)** — the real environment: LSF, the `grit`
module, lustre curation trees, Jira via `GritJiraIssue`. Key-based SSH, no
password, reachable from the Sanger network/VPN only. The clone lives at
`~/github/grit` on the node's NFS home (same origin and branch as the laptop —
they diverge silently if both are committed to, so treat the farm clone as
primary and push/pull rather than editing both).

Preferred setup: VS Code Remote-SSH into the node and run Claude Code in its
terminal (`claude`, installed at `~/.local/bin/claude`). Then editor, agent,
repo, LSF and data are all on one side — no ssh round trip per command, and
lustre paths are directly readable. Driving the node over `ssh` from the laptop
works too, but every command pays the round trip and farm files can only be
read through `ssh cat`.

### Farm gotchas

These are not obvious and each one reads as a missing feature rather than a
misconfiguration:

- **LSF and `module` exist only in a login shell.** `ssh node 'bsub ...'`
  returns "command not found" and looks like LSF is absent; it lives in
  `/software/lsf-farm22/`. Always `ssh node 'bash -lc "..."'`.
- **`/tmp` is node-local.** A bsub job writing to `/tmp` leaves its output on
  the compute node, invisible from the login node. Anything crossing the job
  boundary belongs on lustre or in `$AGENT_SCRATCH` (`~/.agent_scratch`).
- **`/lustre/.../projects` is read-only at the top level**, but the per-species
  `working/` dirs inside are group-writable (`tolengine`, setgid). A `-w` test
  on the parent is misleading.
- **The node is shared** with other curators. Real compute goes through `bsub`,
  never into the login shell.
- **There is more than one LSF cluster, and `bjobs` only answers for its own.**
  `farm22-agentic1` is in the `farm22` cluster; curation jobs are typically
  submitted from a `tol22` node. Asking about a `tol22` job from `farm22` gives
  `Job <N> is not found` — indistinguishable from a job that never existed —
  and `bjobs -m tol22` gives `User permission denied`. So a `grit status` run on
  the agentic node cannot see the curator's jobs, and must never conclude
  anything from that (see the `_check_bjobs` note above). `lsid` names the
  current cluster, `lsclusters` lists them.
- **Everything runs as the curator's own account**, not a service account —
  same quota, same groups, same audit trail.

`~/.agentrc` on the node holds agent-session env (`PAGER=cat`, `GIT_PAGER=cat`,
`AGENT_SCRATCH`, `NXF_HOME`); `~/.bashrc` sources it only when `CLAUDECODE=1`,
so interactive shells keep normal paging. Agent tooling (`rg`, `fd`, `gh`,
`yq`, `bat`, node 20 + npm) is installed under `~/.local`, user-local and
invisible to other users on the node.

## Dev

```bash
uv sync
pytest tests/ -v
ruff check . && ruff format .
```

Tests use `mock_ctx` fixture (from `tests/conftest.py`) — builds `CurationContext` from fixture YAML files in `tests/fixtures/`, no Jira or filesystem access. Functions calling `subprocess` / `bsub` are mocked; tested via call inspection.
