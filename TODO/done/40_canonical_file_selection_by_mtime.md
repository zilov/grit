# TODO 40: pick canonical FASTA/chr-list by recency, not fixed step order

## Problem

`find_canonical_fa` (`grit/utils/helpers.py:309`) and `find_canonical_chr_list`
(`grit/utils/helpers.py:442`) both walk a **fixed** step-priority list and
return the first step's tracker-recorded output that still exists on disk:

- `find_canonical_fa`: `rename_and_orient → rename_and_orient_hap2 →
  blast_contaminants → microchromosome_combine → pretext_to_asm` (loop at
  `helpers.py:330-341`).
- `find_canonical_chr_list`: `rename_and_orient → rename_and_orient_hap2 →
  microchromosome_combine → pretext_to_asm` (loop at `helpers.py:469-482`).

Neither loop ever compares *when* each step actually ran or when its output
file was actually written — it just takes the first hit in a hardcoded order.
`_print_canonical_files()` in `grit/core/status.py:142` calls these directly
to build the "canonical files" table in `grit status`, so this is exactly
the table a curator trusts to know what's going to QC/submission.

Concrete failure: a curator runs `blast-contaminants`, then `rename-and-orient`
(now the tracker's newest recorded output for this hap). They then notice a
problem in PretextView, fix the AGP, and re-run `pretext-to-asm` to regenerate
the curated FASTA. `find_canonical_fa` still returns the **stale**
`rename_and_orient` file, because it's earlier in the fixed list — the fresh
`pretext_to_asm` output is silently ignored. Same bug shape for
`blast-contaminants` re-run after `rename-and-orient`.

Note `rename_and_orient.py:69-77` reinforces why this matters: a
`rename-and-orient` run bakes in whatever `blast_contaminants` (or
`pretext_to_asm`) output existed *at submission time* as its input — it does
not re-derive itself if the upstream input changes later. So "which stage
ran last, chronologically" is the only correct signal for which output
reflects the curator's latest intent; pipeline stage order alone is not
sufficient once any stage can be re-run out of sequence.

`find_canonical_haplotigs` (`helpers.py:361`) only ever looks at one step,
`pretext_to_asm` (loop at `helpers.py:387-395`) — `blast-contaminants` and
`rename-and-orient` never touch haplotig files (confirmed: `blast_contaminants.py`
only calls `find_curated_fa`, never anything haplotig-related), so there is no
multi-stage chain here and therefore no staleness bug to fix. Out of scope.

There's already a working pattern for this exact kind of comparison:
`agp_newer_than_curated_fa(workdir, tol_id, pta_dir)` (`helpers.py:242`)
compares `Path.stat().st_mtime` between an AGP file and a curated FASTA to
decide whether to tell the curator to re-run post-curation
(`status.py:436-444`). It only compares two file sets for one specific
purpose, but the `stat().st_mtime` comparison itself is exactly the primitive
this task needs, generalized across N tracked stages.

## Design

### Compare file mtimes, not tracker record timestamps

Two candidate signals exist:

- **Tracker record timestamp** — `RunTracker.finish()` stamps a
  `%Y-%m-%dT%H_%M_%S` string (`run_tracker.py:131`) when `finish()` is called
  (immediately after a synchronous step, or whenever the bsub `-Ep` epilogue /
  `_state-update` fires for async ones). Already in memory via
  `ctx.tracker.history()` — no extra syscalls.
- **Actual file mtime** — `Path(val).stat().st_mtime` on the resolved output
  path, same primitive `agp_newer_than_curated_fa` already uses.

Recommendation: **use file mtime**, for three reasons:

1. The user's own framing of the priority rule is already in terms of file
   mtime ("newer... by file mtime"), not tracker bookkeeping.
2. It matches the one existing precedent in this codebase
   (`agp_newer_than_curated_fa`) instead of introducing a second, inconsistent
   notion of "recency."
3. Tracker timestamp and file mtime *can* legitimately diverge (e.g. a
   `finish()` call recorded well after slow output-flushing, or a curator
   `scp`-restoring a file some steps back), and in that mismatch the file
   mtime is the more honest answer to "which file is actually newest on
   disk" — which is what actually gets copied to QC. Both signals fail
   equally under a fully manual, out-of-band file copy that doesn't go
   through grit at all, so this isn't a completeness argument, just a
   correctness-when-available one.

Cost: an extra `stat()` per candidate (a handful of syscalls per `grit
status` call) — negligible, and the existing code already calls
`Path(val).exists()` on every candidate today, so this is one more syscall
on paths already being stat'd.

### One shared helper, used by both `find_canonical_fa` and `find_canonical_chr_list`

Add to `grit/utils/helpers.py`, near `agp_newer_than_curated_fa`:

```python
def _latest_tracked_output(
    ctx: "CurationContext",
    steps: list[str],
    key_variants: list[str],
) -> Path | None:
    """
    Among *steps* (tracker step names), return the Path with the newest
    mtime whose tracker output for any of *key_variants* still exists on
    disk. Steps with no matching output are skipped. Ties (equal mtime, or
    only one candidate) resolve to the first-listed step in *steps*.
    """
    if not ctx.tracker:
        return None
    best: tuple[float, int, Path] | None = None  # (mtime, -priority_index, path)
    for idx, step in enumerate(steps):
        for k in key_variants:
            val = ctx.tracker.get_output(step, k)
            if val and Path(val).exists():
                p = Path(val)
                mtime = p.stat().st_mtime
                # -idx so earlier-listed steps win ties (idx=0 is highest fixed priority)
                candidate = (mtime, -idx, p)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
                break  # first matching key for this step wins, same as today
    return best[2] if best else None
```

Both callers pass their own hap-prefix/alias key variants (computed the same
way they do today) and their own fixed step list — the fixed list still
exists, but only as a tie-break order, not as a hard cutoff.

### `find_canonical_fa` (`helpers.py:309`)

Replace the tracker loop (lines 330-341) with two tiers instead of one flat
list, matching the user's stated 3-tier priority while folding
`microchromosome_combine` into the same tier as `pretext_to_asm`:

```python
if ctx.tracker:
    keys = [f"{hap_prefix}_fa", f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_fa"]
    baseline = _latest_tracked_output(ctx, ["microchromosome_combine", "pretext_to_asm"], keys)
    result = _latest_tracked_output(
        ctx, ["rename_and_orient", "rename_and_orient_hap2", "blast_contaminants"], keys
    )
    if result and (baseline is None or result.stat().st_mtime > baseline.stat().st_mtime):
        return result
    if baseline:
        return baseline
```

Why `microchromosome_combine` joins `pretext_to_asm`'s tier rather than the
`rename_and_orient`/`blast_contaminants` tier: it's a bird-specific
*replacement* for `pretext_to_asm`'s output (it internally runs
`pretext_to_asm_micro` then merges — see `microchromosome_combine.py:101-112`),
consumed by `rename_and_orient`/`blast_contaminants` the same way plain
`pretext_to_asm` output is (`rename_and_orient.py`'s `_submit_rename_and_orient_for_hap`
doesn't special-case it — it only ever reads `blast_contaminants` or
`find_curated_fa`). It sits at the same pipeline depth as `pretext_to_asm`,
not alongside the later refinement stages. Existing
`tests/test_helpers_canonical.py::test_blast_contaminants_beats_microchromosome_combine`
and `::test_rename_and_orient_beats_microchromosome_combine` both use
timestamps where `blast_contaminants`/`rename_and_orient` are already
chronologically newer than `microchromosome_combine`, so this change doesn't
regress them — it just makes the "why" (recency, not hardcoded order) also
correct for those cases, and additionally fixes the previously-untested
mirror case (a `pretext_to_asm`/`microchromosome_combine` re-run *after*
`blast_contaminants`/`rename_and_orient` should now correctly win).

The remaining two fallback tiers of the function are unaffected:
- Filesystem-only fallback (`rao_dir` glob at `helpers.py:343-357`) — used
  only when `ctx.tracker` found nothing above; leave as-is, still only
  checks `rename_and_orient`, no `blast_contaminants` filesystem equivalent
  exists today. Out of scope for this task (pre-existing gap, only reachable
  when there is no tracker at all).
- `find_curated_fa(ctx, hap_prefix)` final fallback — unchanged.

### `find_canonical_chr_list` (`helpers.py:442`)

Same shape, minus the `blast_contaminants` tier (blast-contaminants doesn't
touch chromosome lists — it only filters the FASTA):

```python
if ctx.tracker:
    keys = [f"{hap_prefix}_chr_list", f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_chr_list"]
    baseline = _latest_tracked_output(ctx, ["microchromosome_combine", "pretext_to_asm"], keys)
    result = _latest_tracked_output(ctx, ["rename_and_orient", "rename_and_orient_hap2"], keys)
    if result and (baseline is None or result.stat().st_mtime > baseline.stat().st_mtime):
        return result
    if baseline:
        return baseline
```

Filesystem fallbacks below it (`rao_dir` glob, `pta_dir` glob,
no-hap-prefix glob) are unchanged.

### `find_canonical_haplotigs` — no change

Confirmed by reading `blast_contaminants.py` and `rename_and_orient.py`:
neither step ever produces or consumes a haplotigs file — only
`pretext_to_asm` does. `find_canonical_haplotigs`'s tracker loop
(`helpers.py:387-395`) already only checks one step, so there's no
fixed-order-vs-recency conflict possible. Leave it exactly as-is.

### Test changes (`tests/test_helpers_canonical.py`)

Existing tests all use chronologically-increasing timestamps matching the
old fixed order, so they should pass unchanged against the new logic (worth
running them first to confirm before adding anything). Add:

- `test_pretext_to_asm_rerun_after_rename_and_orient_wins` — `finish()`
  `pretext_to_asm` → `blast_contaminants` → `rename_and_orient` in that
  order (mtimes increasing), then `finish()` `pretext_to_asm` *again* with a
  newer output file/mtime than all three. Assert `find_canonical_fa` now
  returns the fresh `pretext_to_asm` file, not the stale `rename_and_orient`
  one. This is the regression test for the bug described above.
- `test_blast_contaminants_rerun_after_rename_and_orient_wins` — same shape,
  one tier up: `rename_and_orient` finishes, then `blast_contaminants` is
  re-run with a newer mtime. Assert `blast_contaminants`'s fresh file wins
  even though `rename_and_orient` is higher fixed-priority.
- `test_microchromosome_combine_rerun_after_blast_contaminants_wins` —
  `blast_contaminants` finishes, then `microchromosome_combine` re-runs with
  a newer mtime. Assert the fresh `microchromosome_combine` file now wins
  over the stale `blast_contaminants` one. This is the same bug shape as
  `test_pretext_to_asm_rerun_after_rename_and_orient_wins`, just with
  `microchromosome_combine` standing in for `pretext_to_asm` in the baseline
  tier — confirms folding `microchromosome_combine` into that tier didn't
  quietly exempt it from the recency fix the rest of this task exists for.
  (Earlier drafts of this doc asserted the opposite — that `blast_contaminants`
  should keep winning here — but that contradicts the `_latest_tracked_output`
  pseudocode above, which always returns `baseline` once it's newer than
  `result`, and it would reintroduce a staleness bug in the tier the fix is
  supposed to cover. Recency wins within and across both tiers; tier order is
  only a tie-break for equal mtimes.)
- Existing `test_untracking_blast_contaminants_falls_back_to_pretext_to_asm`
  should still pass unchanged (untracking removes the candidate entirely,
  independent of mtime logic).

Since file writes in the same test can land within the same filesystem mtime
tick, tests must give files distinct mtimes explicitly (e.g.
`os.utime(path, (ts, ts))` with deliberately spaced-out `ts` values) rather
than relying on real wall-clock gaps between `_write()` calls.
</content>
