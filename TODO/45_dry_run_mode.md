# TODO 45: `--dry-run` mode for testing pipeline/tracking logic without HPC

## Problem

Testing anything about how steps sequence and how canonical-output resolution
behaves (`find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs`
in `grit/utils/helpers.py`, the flat mtime pool from `TODO/done/44_canonical_fa_flat_mtime_priority.md`,
`grit status -t`'s ★ marker, `grit untrack`) currently means either writing a
unit test (good for the logic itself, but not a real end-to-end CLI check) or
actually running the pipeline on the farm — which means waiting on real
`bsub`/HPC jobs and external tools (`decon_blastBTK`, `rename-and-orient`,
BUSCO, etc.) to finish, sometimes for a long time, just to see whether a
sequence of CLI commands produces the tracker state and canonical resolution
you expect.

`--print-only` (`grit/core/base_command.py:52-59`) already exists and does
its own job well — print the constructed command, execute nothing, touch no
files — but that's the opposite of what's needed here: it can't be used to
drive `grit status -t`/`find_canonical_fa`/`grit untrack` through a real
sequence of completed steps, because nothing is ever tracked as done.
`--print-only` stays exactly as-is; this task adds a second, independent
mode.

## Design

A new `--dry-run` flag, wired through the codebase exactly the way
`--print-only` already is, that makes a step **actually** create its final
tracked output file(s) and call `RunTracker.finish(..., "success", ...)` for
real — while never shelling out to any real external tool, never submitting
a real `bsub` job, and never touching any of the intermediate files a real
run's Python glue would read back. After running a sequence of steps with
`--dry-run`, `grit status -t`/`find_canonical_fa`/`grit untrack` all operate
on real tracker state, indistinguishable from a real run as far as they're
concerned.

### 0. Plumbing — mirror `--print-only`'s wiring exactly

- `grit/core/base_command.py`: `GritCommand.__init__` inserts `--ticket`,
  `--print-only`, `--untracked`, (`--bsub-ram`) in that order (lines 33-68,
  each via `self.params.insert(0, ...)`, so they end up in reverse
  declaration order). Add a fifth `click.Option(["--dry-run"], is_flag=True,
  default=False, help="Create placeholder outputs and mark steps done, "
  "without running any real command (for testing pipeline/tracking logic).")`
  the same way, and pop/OR it in `invoke()` (lines 70-96) alongside
  `print_only`/`untracked`/`bsub_ram`.
- `grit/core/click_cli.py`: `GlobalState.__init__` (lines 31-52) gains
  `dry_run: bool = False`; the group-level `cli()` command (line 72) gets a
  matching `--dry-run` option next to the existing `--print-only`
  (mirrors line 62's `@click.option("--print-only", ...)`); `build_context()`
  (line 93) passes `dry_run=state.dry_run` through alongside
  `print_only=state.print_only` (line 107).
- `grit/core/context.py`: `CurationContext` (class starting line 44) gains
  `dry_run: bool = False` next to `print_only` (line 87); `from_yaml`/
  `from_ticket` (lines 108, 191) gain a `dry_run: bool = False` parameter
  and thread it through to the constructed instance (lines 182, 231) the
  same way `print_only` already is. `RunTracker` itself needs no `dry_run`
  awareness — it just records whatever `finish()` is called with, same as a
  real run.

`ctx.dry_run` and `ctx.print_only` are mutually exclusive in intent but not
enforced as such — if both are somehow set, `print_only` takes precedence
(check it first in each step's fake branch) since printing-without-executing
is the more conservative behavior.

### 1. A shared fake-output writer, reusing the existing step-spec registry

`grit/utils/helpers.py` already has exactly the registry this needs:
`_get_step_specs(step)` (lines 768-800) maps a tracker step name to its
`_OUTPUT_SPECS`/`_OUTPUT_SPECS_HAP2` constant via lazy import, and
`collect_outputs(specs, run_dir, tol_id, ...)` (lines 748-765) globs `run_dir`
against those specs to build the `{key: path}` dict `tracker.finish()` wants.
Add the inverse next to it:

```python
def write_fake_outputs(
    step: str,
    run_dir: Path,
    tol_id: str,
    *,
    hap1: str = "hap1",
    hap2: str = "hap2",
    content: dict[str, bytes] | None = None,
) -> dict[str, str]:
    """
    Write one placeholder file per _OUTPUT_SPECS entry for *step* into
    run_dir, using the first concrete glob match (wildcards filled with a
    fixed placeholder token) as the filename. Returns the same {key: path}
    shape collect_outputs() would have found, ready for tracker.finish().
    """
```

Each spec's `pattern.format(tol_id=tol_id, hap1=hap1, hap2=hap2)` (same
substitution `collect_outputs` already does, `helpers.py:761`) still has
`*`/`?` wildcards for the parts a real run fills in dynamically (release
version, run-specific suffixes) — fill every such wildcard with a fixed
placeholder token (e.g. `1`) to get one concrete filename per spec. Skip
specs whose `key` was already written by an earlier spec in the same list
(mirrors `collect_outputs`'s own `if key in outputs: continue` dedup at line
759, since some specs are fallback patterns for the same key). Write
`content.get(key, b">fake\nACGT\n")` if `content` is given for that key,
otherwise a trivial one-line stub — see §3 for which steps actually need
`content=`.

### 2. Per-step fake branch — bypass `_run`/`_submit_bsub` entirely

Each step's public function gets an early branch, before any real
subprocess/external-tool path is constructed:

```python
if ctx.dry_run:
    run_dir = ctx.tracker.start(step_name, ctx.ticket_id, ctx.tol_id) if ctx.tracker else ctx.workdir / step_name / "fake"
    outputs = write_fake_outputs(step_name, run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix, content=...)
    if ctx.tracker:
        ctx.tracker.finish(step_name, run_dir, "success", outputs=outputs or None)
    print_done(f"[dry-run] {step_name} → {run_dir}")
    return
```

This must go **before** any per-step Python-level pre-processing that itself
does real filesystem/subprocess work — e.g. `blast_contaminants.py`'s
`_blast_contaminants_for_hap` runs the lineage script, writes/reads
`blast.me`, and calls `decon_blastBTK` across 6 sequential `_run()` calls with
real intermediate files feeding each other; faking each of those
individually would be as much work as the real function for no test value.
Short-circuiting the whole function early means only the *final* tracked
output needs to exist, which is all any downstream code (`find_canonical_fa`,
`grit status`) ever looks at.

Bsub-based steps (`rename_and_orient.py`, `hic_remapping.py`, `fastga.py`)
must **never** call `_submit_bsub()` in the fake branch — there's no real LSF
to fire the `-Ep` epilogue that would normally call `RunTracker.finish()` (see
`_state_update_epilogue()`, `helpers.py:84-95`, and the hidden `grit
_state-update` command, `click_cli.py:186-225`). Calling `tracker.finish()`
synchronously in the fake branch instead means these runs are written
straight to `"success"` with no `job_id` — so `RunTracker.pending_jobs()`
(`run_tracker.py:223-242`, which only returns `status == "started"` records
that *also* have a `job_id`) and `status.py`'s bjobs-poll fallback
(`show_ticket_history`, lines ~340-406) never see them at all. No changes
needed in either of those files — fake runs are invisible to the
pending-job machinery by construction, not by special-casing it.

**Rollout order** (add the branch to one step at a time; a step without one
yet simply doesn't support `--dry-run` and should raise a clear
`NotImplementedError`/log an error rather than silently falling through to a
real run):

1. `pretext_to_asm` — the root of the canonical-FASTA pool; needed before
   anything else can be tested.
2. `blast_contaminants`, `rename_and_orient` — the two steps this feature
   was originally motivated by testing (see the SCAFFOLD-header
   warn-and-continue mitigation and the flat-pool forward-chain from
   `TODO/done/44_canonical_fa_flat_mtime_priority.md`).
3. `microchromosome_combine`, `pretext_to_asm_recurate` — completes coverage
   of every step in the canonical-FASTA pool.
4. `hic_remapping` — needed to reach the recurate loop described in
   `recuration-canonical-priority.md`'s step 8.
5. Everything else (`fastga`, `qv`, `finalize_qc`, `busco_*`,
   `microchromosome_second_shot`, etc.) — follow-up, not blocking the
   canonical-FASTA testing use case that motivated this task.

### 3. Content realism — most outputs are stub-fine, two are not

`find_canonical_fa`/`find_canonical_chr_list`/`grit status`/`RunTracker` only
ever check existence and mtime — a one-line stub file is enough for those.
Two steps' outputs are read for their *content* by other Python code, and
need `content=` overrides in `write_fake_outputs()`:

- **`pretext_to_asm`'s curated FASTA** — `blast_contaminants.py`'s scaffold-ID
  extraction (`perl -nE 'say "true,$1" if /([HAP_\d]*SCAFFOLD_\d+)/i'`, line
  109) needs real `>SCAFFOLD_1`/`>HAP_SCAFFOLD_1`-style headers to exercise
  its actual matching logic — a fake FASTA with a couple of short records
  using this header convention.
- **`fastga`'s `*.top1_targets.tsv`** — parsed by `run_fastga_stats`
  (`fastga.py:47-50`); needs a few real tab-separated rows if `fastga-stats`
  is ever going to be run against fake `fastga` output (lower priority per
  the rollout order above — only needed once `fastga` itself gets a fake
  branch).

Everything else in the rollout list (pretext maps, mapping.tsv, chromosome
lists, decontaminated/renamed FASTAs used only for existence/mtime by later
steps) can be trivial stubs.

### 4. Verification

Add a `--dry-run` pass to `tests/local_smoke_test.sh` (the existing
farm-path smoke test) that chains a real sequence through the actual CLI —
e.g. `grit pretext-to-asm --dry-run` → `grit blast-contaminants --dry-run`
→ `grit rename-and-orient --dry-run` → `grit status -t` (assert the ★ marker
lands on `rename_and_orient`'s row) → `grit untrack --step rename_and_orient`
→ `grit status -t` again (assert the ★ moves to `blast_contaminants`). This
is exactly the kind of scenario from `recuration-canonical-priority.md` that
currently requires real farm time to check by hand. Add matching unit tests
per step alongside each fake branch (in that step's existing test file),
asserting `ctx.tracker.get_output(step_name, ...)` resolves to a real file
after a fake run — the same shape of assertion already used throughout
`tests/test_helpers_canonical.py`.

### 5. Docs

Once the first few steps have fake branches, add `--dry-run` to
`CLAUDE.md`'s "Key conventions" section next to the existing `print_only`
bullet, describing it as the way to exercise step-sequencing/tracking/
canonical-resolution logic through the real CLI without HPC access.

## Net effect

- A curator/developer can run a full sequence of pipeline commands with
  `--dry-run` and get real, inspectable tracker state — `grit status -t`
  shows the real step-history table and ★ marker, `grit untrack` really
  flips what's canonical — without waiting on `bsub`/HPC or touching any
  real external tool.
- `--print-only` is untouched; the two flags serve different, non-competing
  purposes (verify command construction vs. verify tracking/sequencing
  logic).
- Rollout is incremental and low-risk: each step's fake branch is one
  `if ctx.dry_run: ...; return` block, same shape as the `print_only`
  guards already scattered through these files, off by default.
</content>
