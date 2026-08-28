# TODO 38: dedupe BUSCO runs inside busco-synteny

## Problem

`busco_synteny.py` shells out to `busco_dependent_scripts/busco_synteny.sh`,
which runs BUSCO on ref + query fasta *and* the circos plot in one bsub job.
Every re-run (retry after a failure, re-running with `-k` to inspect output,
running the step again for whatever reason) redoes both BUSCO runs from
scratch, and at the end `busco_synteny_format_and_plot.py`'s
`tidy_busco_run()` deletes the whole `busco5_mini{ID}/` dir (all of it,
`busco_downloads/` included), so there's nothing left to reuse even within
the same ticket. Disk fills up with leftover BUSCO output files transiently
during the run (there's a per-user file count limit on the cluster), and
reruns pay the full BUSCO cost again.

Out of scope: reuse between `busco-curated` and `busco-synteny`'s query run
(they can happen to run BUSCO on the same curated fasta) — that overlap
exists but isn't worth the cross-command bookkeeping it'd take to dedupe.
This task only fixes the two BUSCO runs *within* `busco-synteny` itself.

## Design

`busco_synteny.py` keeps its existing single `tracker.start("busco_synteny",
...)` call exactly as today — no tracker or `grit/core/manifests.py` changes
needed. Everything below is a small rewrite of the two existing scripts
(`busco_synteny.sh` and `busco_synteny_format_and_plot.py`) plus one one-line
fix in `busco_synteny.py`.

### 0. Move the scripts into the repo's `scripts/` dir, referenced from there

`sex_matcher.py` already establishes the convention for repo-bundled
scripts: `scripts/sex-matcher.sh`, referenced via `_REPO_ROOT / "scripts" /
"sex-matcher.sh"` (`_REPO_ROOT = Path(__file__).parent.parent.parent.parent`),
run with `bash {_SEX_MATCHER_SCRIPT} ...` — not the `/software/grit/projects/
vgp_curation_scripts/...` absolute path that `busco_synteny.py` currently
uses for both `_BUSCO_SYNTENY_SCRIPT` and the plot script invocation inside
`busco_synteny.sh` itself.

As part of this change:

- Move (and apply all the edits below to) the scripts into `scripts/` at
  the repo root: `scripts/busco-synteny.sh` and
  `scripts/busco_synteny_format_and_plot.py` (matching the existing
  `sex-matcher.sh` naming/location, not the `busco_dependent_scripts/`
  staging copies currently sitting untracked in the repo — those were just
  pulled from `/software/grit/projects/vgp_curation_scripts/` for reference
  and aren't the final location).
- In `busco_synteny.py`, add `_REPO_ROOT` (or reuse it if already present)
  and change `_BUSCO_SYNTENY_SCRIPT` to `_REPO_ROOT / "scripts" /
  "busco-synteny.sh"`, invoked the same way `sex_matcher.py` invokes its
  script (`bash {_BUSCO_SYNTENY_SCRIPT} ...`).
- Inside `busco-synteny.sh`, change the hardcoded call to
  `busco_synteny_format_and_plot.py` from the `/software/grit/projects/
  vgp_curation_scripts/` path to a path resolved relative to the script's
  own location (e.g. `SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &&
  pwd)`, then `python "$SCRIPT_DIR/busco_synteny_format_and_plot.py" ...`),
  so the pair keeps working when checked out anywhere, same as it would
  when deployed onto the cluster from the repo.
- Leave the untracked `busco_dependent_scripts/` directory alone — don't
  delete it as part of this change unless the user confirms it's fine to
  remove; it's out of scope for this task.

### 1. Make the output directory an explicit, required argument — not `pwd`

Today `busco_synteny.sh` defaults `myDirPath=$(pwd)` when `-p` isn't given,
and `busco_synteny_format_and_plot.py` defaults `base_path=os.getcwd()` when
`-p` isn't given. Both scripts are only correct by accident, dependent on
whatever directory they happen to be invoked from — `busco_synteny.py`
currently doesn't even pass `-p`, so both scripts silently fall back to
`pwd`/`getcwd()`, which for a bsub job is whatever directory it happens to
inherit, not necessarily `ctx.workdir`.

Fix this at the source instead of papering over it with a `cd`: make `-p`
**required** in both scripts (drop the `pwd`/`getcwd()` fallback entirely —
error out via `usage`/`argparse required=True` if it's missing). Both
scripts then read their inputs and write all outputs solely via that
explicit path, with no dependency on the invoking shell's cwd. This makes
them safe to invoke from anywhere — a bsub job, a curator's shell, a test
— and makes "where did the output go" always answerable from the command
line alone, not from tracing an implicit `cd`.

`busco_synteny.py`'s `inner_cmd` passes `ctx.workdir` explicitly via `-p`
(no `cd` needed):

```python
inner_cmd = (
    f"bash {_BUSCO_SYNTENY_SCRIPT} -r {ref_reheader} -q {query_fa} -l {lineage} -p {ctx.workdir}"
)
```

So all of ref/query BUSCO output, the flattened full tables, and the circos
plot land in `ctx.workdir` directly (matching where `busco_curated.py`
already puts its own `{tol_id}_busco_singularity/` output, for consistency).

### 2. Reuse the existing flattened full-table file as the cache marker,
   and flatten the short summary alongside it

`busco_synteny_format_and_plot.py` already produces a flat full-table file
per genome — `move_busco(ID)` renames
`busco5_mini{ID}/run_{lineage}/full_table.tsv` to
`{ID}_BUSCO_full_table.tsv` in the working dir — it just does this *after*
plotting, then deletes the whole `busco5_mini{ID}/` dir regardless (taking
the short summary with it — today it isn't preserved anywhere at all). Flip
the order: flatten (and trim) each genome's BUSCO output **immediately after
its own BUSCO call finishes**, in the bash script, before the plot script
even runs. That flat full-table file then doubles as the "already done"
marker for next time — no separate marker format needed.

At the same time, also flatten BUSCO's short summary file
(`busco5_mini{ID}/short_summary.specific.{lineage}.busco5_mini{ID}.txt`) to
`{ID}_BUSCO_short_summary.txt` in the same step, so both the full table and
the short summary for ref and query survive the `busco5_mini{ID}/` cleanup
and are left in `ctx.workdir` at the end of every run — not just the full
table. Since both files are produced together, before the `busco5_mini{ID}/`
dir is removed, the full-table marker check also guarantees the short
summary is present from a prior run.

In `busco_synteny.sh`:

```bash
run_busco_if_needed() {
    local fasta=$1 id=$2
    local flat_table="${myDirPath}/${id}_BUSCO_full_table.tsv"
    local flat_summary="${myDirPath}/${id}_BUSCO_short_summary.txt"
    if [ -f "$flat_table" ]; then
        echo "BUSCO already run for ${id} (${buscoLineage}), reusing ${flat_table}"
        return
    fi
    local outdir="busco5_mini${id}"
    singularity exec -B /lustre $IMAGE busco -i "$fasta" -o "$outdir" -m genome \
        -l /lustre/scratch122/tol/resources/busco/latest/lineages/$buscoLineage -c 32
    mv "${outdir}/run_${buscoLineage}/full_table.tsv" "$flat_table"
    mv "${outdir}/short_summary.specific.${buscoLineage}.${outdir}.txt" "$flat_summary"
    if [ -z "$filesKeep" ]; then
        rm -rf "$outdir"
    fi
}

run_busco_if_needed "$myReference" "$ref_short_id"
run_busco_if_needed "$myQuery" "$query_short_id"

python /software/grit/projects/vgp_curation_scripts/busco_synteny_format_and_plot.py \
    -r "$myReference" -q "$myQuery" -ri "$ref_short_id" -qi "$query_short_id" -p "$myDirPath"
```

Confirm the exact short-summary filename BUSCO emits for this version/mode
before implementing (it may be `short_summary.specific.<lineage>.<outdir>.txt`
or `short_summary.txt` depending on BUSCO version) — adjust the `mv` source
path accordingly, since a wrong path here would fail silently different from
a wrong full-table path (BUSCO always writes a full_table.tsv, but the exact
short-summary name is more version-dependent).

This directly solves the file-count-limit concern too: the heavy
`busco5_mini{ID}/` tree (`busco_sequences/`, `logs/`, hmmer/blast
intermediates, etc.) is deleted right after its one relevant file is
extracted, rather than sitting on disk until the plot script finishes and
does the cleanup at the very end.

`-k`/`filesKeep` keeps working the same way — when set, `run_busco_if_needed`
just doesn't `rm -rf` the busco5_mini dir, same intent as today.

`busco_downloads/` (the downloaded lineage dataset) — leave the existing
behavior (deleted at the end unless `-k`) as is; re-downloading the lineage
set on every busco-synteny run is wasteful too, but that's a separate,
lower-priority cleanup, not part of this dedup fix.

### 3. Simplify `busco_synteny_format_and_plot.py` to match

Since the bash script now always hands it pre-flattened, pre-trimmed input:

- `readfulltables(ID)` reads directly from
  `f'{base_path}/{ID}_BUSCO_full_table.tsv'` — drop the
  `busco5_mini{ID}/run_{lineage}/` path derivation entirely.
- Drop `-l/--lineage` — it was only used for that path derivation.
- Delete `move_busco()` and `tidy_busco_run()` entirely — flattening and
  `busco5_mini` cleanup now happen in the bash script, right after each
  BUSCO call, not in the plot script after the fact.
- Keep `-r/--ref`, `-q/--query` (still needed for chromosome length data via
  `get_chroms_data`), `-ri/-qi` short ids, `-k`/`--keep` (now only gates the
  `busco_downloads/` cleanup, since `busco5_mini` cleanup moved to bash).
- Make `-p/--path` (`base_path`) `required=True` and drop the
  `os.getcwd()` fallback — see point 1. The script always reads/writes via
  the explicit path it's given, never the invoking process's cwd.

### 4. Verification: add `busco-synteny` to the farm smoke test

`tests/local_smoke_test.sh` runs every step with `--print-only` against real
farm paths, for steps whose print-only path still checks for a prior step's
output on disk (`fastga`, `blast-contaminants`, `rename-and-orient`,
etc.) — `busco-synteny` belongs there, not in the hermetic
`tests/test_smoke.py`, since `run_busco_synteny` looks for real prior
`find-reference` output on disk (via `find_latest_dir`/`glob.glob`) even
under `--print-only` (see the `ctx.print_only` branch in `busco_synteny.py`
that only takes a shortcut for the ref-fasta name, not the up-front
existence check). Add one line to the "Optional" section of
`local_smoke_test.sh`, alongside the other steps that need farm paths:

```bash
$GRIT --yaml "$HAP_YAML" busco-synteny -l <lineage>       && ok "busco-synteny"
```

(fill in whatever `-l` lineage value the fixture ticket's reference actually
uses — check the other optional steps / fixture YAML for the right one).

This is how the rewritten scripts get exercised without real cluster/farm
access or a `bsub` submission: `--print-only` prints the constructed
`inner_cmd` (now `bash {_BUSCO_SYNTENY_SCRIPT} -r ... -p {ctx.workdir}`)
without executing it, so the smoke test validates the Python-side command
construction and path wiring (repo-relative script path, `-p` argument,
`bash` invocation) end-to-end, the same way it already does for
`blast-contaminants`/`rename-and-orient`. It does not exercise the bash
script's internals (`run_busco_if_needed`, the `mv`/`rm -rf` logic, the
short-summary filename) — those aren't runnable without `singularity` and
the BUSCO image, so they're out of scope for automated verification here
and should be sanity-checked by inspection (e.g. `bash -n scripts/busco-
synteny.sh` for a syntax check, and a careful read of the `mv` source paths
against real BUSCO output) rather than executed.

### Net effect

- Re-running `busco-synteny` for the same ticket/lineage after a failure (or
  just re-running the plot step) skips BUSCO entirely for whichever
  genome(s) already have a flat full-table file on disk, via a plain
  `[ -f ... ]` check per genome in the bash script.
- Heavy BUSCO working directories never accumulate past the single call
  that produced them.
- Both the full table and short summary, for ref and query alike, are left
  behind in `ctx.workdir` at the end of every run — not just as an internal
  cache marker but as user-facing output a curator can inspect directly.
- No changes to `busco_curated.py`, `grit/core/manifests.py`, or
  `RunTracker` — `busco_synteny` stays a single tracked step, same as today.
</content>
