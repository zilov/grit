# TODO 52: hic-remapping submits nextflow itself, with a `_state-update` epilogue

## Problem

`hic_remapping.py` runs `curationpretext.sh`, which issues its own `bsub`, so
grit only scrapes `Job <N>` from its stdout and never owns the job. No `-Ep`
epilogue can be attached, and the run stays `started` until some `grit status`
sweep reconciles it through `bjobs`. That fallback is fragile by construction:

- it only happens when a curator runs `grit status`; until then the previous
  run's map stays canonical, and `finalize-qc` would publish it;
- `bjobs` only answers for its own cluster (`gone` from farm22 for a tol22 job)
  and forgets jobs after the clean period;
- RC-4988 (2026-09-24): job 770835 ended 14:28 BST, the record was closed at
  15:13 BST by `grit status -t`, whose DONE branch ran after canonical files
  were printed — the curator saw the old map. f5cb3c3 moved DONE into the
  sweep, which fixes the display but not the dependence on someone polling.

Every other bsub step closes itself through `_state_update_epilogue()`
(`fastga.py`, `busco_synteny.py`, `rename_and_orient.py`). hic_remapping is the
exception only because of the wrapper.

`curationpretext.sh` (`/software/treeoflife/custom-installs/bin/sanger-tol/curationpretext/1.5.1/`)
is ~50 lines and does nothing grit can't do itself:

```bash
export NXF_DISABLE_CHECK_LATEST=1
export NXF_OPTS='-Xms128m -Xmx1024m'
# refuses to run in a non-writable cwd
# -profile X  →  -profile sanger,singularity,X
nxf_run_command="nextflow run <install>/sanger-tol/curationpretext-1.5.1/1_5_1/main.nf \
  -profile ${profile} -ansi-log false -with-weblog http://logstash.tol.sanger.ac.uk/http $user_inputs"
/software/treeoflife/custom-installs/tracking/tracking_usage.sh <module dir> 'nextflow run' ...
bsub -M1200 -R"select[mem>1200] rusage[mem=1200] span[hosts=1]" -n 1 -q oversubscribed \
  -o curationpretext_1_5_1_%J.log $nxf_run_command
```

Related open finding: `CORR-08` (TODO/50) — the "already done, skipping"
branch in `_submit_hic_remapping` finishes a still-`started` run as `success`
from the mere existence of `hr.pretext`, which may be mid-write.

## Design

### 1. Submit the nextflow head job through `_submit_bsub` with an epilogue

In `_submit_hic_remapping`, replace the `_run(hic_cmd)` + `Job <N>` scrape with
the standard pattern:

```python
epilogue = _state_update_epilogue(ctx.workdir, step_name, run_dir, untracked=ctx.untracked)
job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
if ctx.tracker and job_id: ctx.tracker.record_job(step_name, run_dir, job_id)
```

- `bsub_opts` via `build_bsub_opts(queue="oversubscribed", memory_mb=1200,
  output="curationpretext_%J.log", run_dir=run_dir)` — same resources as the
  wrapper. Check `%J` survives quoting.
- `inner_cmd`: `cd {run_dir} && {module_cmd('CURATIONPRETEXT')} &&
  export NXF_DISABLE_CHECK_LATEST=1 NXF_OPTS='-Xms128m -Xmx1024m' &&
  nextflow run $MAIN_NF -profile sanger,singularity -ansi-log false
  -with-weblog http://logstash.tol.sanger.ac.uk/http <existing args> -resume`.
  Watch the quoting: `_submit_bsub` wraps `inner_cmd` in double quotes, so
  any `$VAR` meant for the job must be escaped (`\$`) or it expands at submit
  time on the login node.
- Keep every existing pipeline argument exactly (`--map_order unsorted`,
  `--input`, `--sample`, `--cram`, `--reads`, `--read_type`, `--outdir`,
  `--split_telomere true`, teloseq, `-N email`, `-resume`).
- The nextflow head exits 0 only when the whole pipeline completed, so the
  epilogue's `$LSB_JOBEXIT_STAT` is exactly the completion signal, and it fires
  on the submitting cluster regardless of where anyone runs `grit status`.

### 2. Resolve `main.nf` from the loaded module, not a hardcoded path

The `grit` module (`MODULE_VERSIONS["CURATIONPRETEXT"]`) loads
`nextflow/25.04.6-5954` and `sanger-tol/curationpretext/1.5.1`; version bumps
happen in that module, not in grit. So do not pin a `main.nf` path in grit.
Inside the job, after `module load`, derive it from the wrapper the module put
on `PATH`:

```bash
MAIN_NF=$(grep -oE '/[^ ]+/main\.nf' "$(command -v curationpretext.sh)" | head -1) &&
test -n "$MAIN_NF" && test -f "$MAIN_NF" || { echo "cannot locate curationpretext main.nf" >&2; exit 1; }
```

A failure here exits non-zero → epilogue records `failed` — loud, not silent.
Verify on the farm (`bash -lc`) that this resolves to the real file.

Usage tracking (`tracking_usage.sh`) is the Tree of Life team's usage metric
for the module; call it best-effort (`[ -x ... ] && ... || true`) so it can
never fail the job. Resolve its module-dir argument the same way or drop it if
that proves brittle — note the decision in the commit.

### 3. Fix the "already done" branch (CORR-08)

With an epilogue, a `started` latest record means the job is in flight (or its
epilogue never fired, which the `grit status` sweep still recovers). The
skip branch must no longer call `finish(..., "success")` on a `started` run:
if the latest record for `prev_dir` is `started`, print that the run is still
in progress (with its `job_id`) and return without finishing or resubmitting.
Only a `success` record with an up-to-date map counts as "already done".
Keep the FASTA-newer-than-map rerun logic.

### 4. Leave the bjobs fallback in place

`_refresh_pending_jobs` (incl. f5cb3c3's DONE branch) stays: it covers runs
submitted before this change and any epilogue that fails to fire. Records from
old wrapper submissions keep working unchanged.

### Out of scope

- `CORR-03` (`_state-update` records `success` with no outputs). A nextflow
  exit 0 without `*normal.pretext` is unlikely; fix separately.
- `find_reference.py` / other nextflow callers.

### Tests

- Command construction (mock `_run`/`_submit_bsub`): `bsub` has `-Ep` with
  `_state-update --step hic_remapping[_hap2] --run-dir <run_dir>`, the
  `--untracked` flag propagates, `-q oversubscribed -M 1200`, `cd {run_dir}`
  first, all pipeline args preserved, `$MAIN_NF` not expanded at submit time.
- `record_job` called with the parsed job id.
- Skip branch: latest record `started` + `hr.pretext` on disk → no `finish`,
  no submission; latest `success` + up-to-date map → skipped as before;
  canonical FASTA newer → resubmits.
- `--print-only` output still shows the full command; `--dry-run` branch
  untouched.

### Verification on the farm

`grit --print-only hic-remapping -t <ticket>` on `farm22-agentic1`, then run
the `MAIN_NF` resolution line in `bash -lc` after `module load grit` to confirm
it finds the file. No real submission without the curator's go-ahead.

### Docs

Update CLAUDE.md's "Command execution" section: hic_remapping now uses the
epilogue; the bjobs reconciliation paragraph describes a fallback for old
records / failed epilogues rather than hic_remapping's primary path. Add a
CHANGELOG `[Unreleased]` entry.
