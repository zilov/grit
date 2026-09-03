# TODO 44: pretext-to-asm-recurate — curating an already-curated map

## Problem

Some curators, after finishing `pretext-to-asm` → `hic-remapping`, find issues
in the resulting remapped Hi-C map and curate it *again* in PretextView,
producing a second AGP. They then want to run `pretext-to-asm` a second time
using that second AGP — but with the *first* round's curated FASTA as the
`original.fa` input, not the ticket's actual `original.fa`. This can happen
independently per haplotype: hap1 commonly goes through this "recuration"
round, hap2 sometimes does not.

Grit has no support for this today:

- `pretext_to_asm.py`'s `run_pretext_to_asm` always reads `original.fa` from
  `ctx.workdir` and a single `{tol_id}*.agp*` glob — it can't be pointed at a
  different "original" input or a second AGP.
- Every step is tracked in the registry under one fixed `step` name string
  (`grit/core/run_tracker.py`), and `RunTracker.latest_run_dir()`/`get_output()`
  always return the most recent record for that step name. If a second
  `pretext-to-asm` run were tracked under the *same* `"pretext_to_asm"` step
  name, and that second run only covers hap1 (because hap2 wasn't
  recurated), the "latest" run's `outputs` dict would have no `hap2_fa`/
  `hap2_chr_list`/`hap2_haplotigs` keys at all — silently breaking hap2's
  canonical resolution, which today assumes one `pretext_to_asm` run covers
  whichever haps exist.
- `pretext_to_asm.py`'s haplotig outputs are whatever the `pretext-to-asm`
  binary happens to emit for that single invocation — there's no concept of
  combining haplotigs across two separate runs of the tool.
- `find_canonical_fa` / `find_canonical_chr_list` / `find_canonical_haplotigs`
  (`grit/utils/helpers.py`) walk a fixed, fixed-depth priority chain of step
  names (`rename_and_orient(_hap2)` → `blast_contaminants` →
  `microchromosome_combine`/`pretext_to_asm` [→ filesystem/`find_curated_fa`
  fallbacks]) with no slot for a step that is logically "more downstream than
  everything else, always."

This overlaps directly with [TODO 40 (canonical file selection by
mtime)](40_canonical_file_selection_by_mtime.md), because that task is what
makes the *existing* tiers (`rename_and_orient`/`blast_contaminants` vs
`pretext_to_asm`/`microchromosome_combine`) resolve correctly by recency
rather than fixed order — this task depends on that fix being correct, but
does not itself need mtime-based comparison at its own tier (see Design).

## Design

### New command: `grit pretext-to-asm-recurate [--hap2]`

A new step file, `grit/steps/post_curation/pretext_to_asm_recurate.py`,
exporting `run_pretext_to_asm_recurate(ctx, hap_prefix, step_name)` and a
Click command `pretext_to_asm_recurate_cmd`, matching `hic_remapping_cmd`'s
CLI shape exactly: a single boolean `--hap2` flag ("Recurate hap2 instead of
hap1."), defaulting to hap1/primary when omitted. One invocation handles
exactly one haplotype — same shape as `hic_remapping`'s existing hap1/hap2
split, since the two haps' AGP inputs are curated and supplied independently
and at different times. No `--hap1` flag exists, same as `hic-remapping`
has no `--hap1`.

This reuses the same `_run_pretext_to_asm_core` helper `pretext_to_asm.py`
and `microchromosome_combine.py` already share (see Problem) — a third
caller with its own `step_name` and its own `_OUTPUT_SPECS`, following
existing precedent rather than inventing a new execution path.

### Step names: `pretext_to_asm_recurate` / `pretext_to_asm_recurate_hap2`

Tracked as two independent step names, mirroring `hic_remapping` /
`hic_remapping_hap2`. This sidesteps the "second run silently drops the
other hap's keys" problem entirely — hap2's canonical resolution is
unaffected by whether or when hap1 recurates, and vice versa, because each
hap's recuration status lives in its own step history.

### Input FASTA: whatever is *currently* canonical for this hap

`run_pretext_to_asm_recurate(ctx, hap_prefix)` resolves its `original.fa`
input via `find_canonical_fa(ctx, hap_prefix)` — the same function
`hic_remapping.py` already uses to resolve its own input — rather than
hardcoding "the first `pretext_to_asm` run's output." This was a deliberate
choice over the alternative (always chase back to the literal first
`pretext_to_asm` run): a curator may have already run `blast-contaminants`,
`rename-and-orient`, or `microchromosome-combine` on the first round's output
before deciding to recurate the remapped map, and recuration should build on
top of whatever that latest state is, not silently discard it.

No ordering is enforced. Grit does not check or block on which upstream
steps have or haven't run for this hap — the command just resolves and uses
whatever `find_canonical_fa` currently returns. But since running
`blast-contaminants`/`rename-and-orient`/etc. *after* recuration won't
actually change canonical resolution (see next section — recuration always
wins), the command prints an informational tip (via
`grit/utils/output.py`, matching the existing tip-printing convention) before
running:

> "This uses the current canonical FASTA as input. If you still need to run
> blast-contaminants, rename-and-orient, or microchromosome-combine on this
> haplotype, do that *before* running pretext-to-asm-recurate — recuration
> output always takes canonical priority over those steps once it exists
> (see `grit undo` to reverse this if needed)."

This mirrors `_raise_if_yaml_pta_mismatch`'s existing informational-not-
blocking style in `finalize_qc.py`, but as a tip rather than a hard error,
since the user has explicitly decided a hard order check isn't warranted
here.

This also means `find_canonical_fa` must already be correct about recency
*before* recuration is layered on top — i.e., [TODO 40's mtime-based fix](40_canonical_file_selection_by_mtime.md)
should land first (or as part of this same effort), otherwise a stale
canonical fa could silently become the recuration input.

### AGP location: `{workdir}/recurate/`, hap-qualified filename

The recuration AGP is a distinct file from the ticket's primary
`{tol_id}*.agp*` (which stays wherever `pretext_to_asm.py` already expects
it). Curators drop the recuration AGP into a dedicated `{workdir}/recurate/`
directory, with the haplotype in the filename so the same directory can hold
both haps' AGPs without collision:

```
{workdir}/recurate/{tol_id}.{hap_prefix}.recurate.agp[.gz]
```

`run_pretext_to_asm_recurate` globs `{workdir}/recurate/{tol_id}*{hap_prefix}*.agp*`
for this hap, following the same "glob, single match expected" pattern
`pretext_to_asm.py` already uses for the primary AGP.

### Output specs and haplotig merging

`_OUTPUT_SPECS` for this step covers only the requested haplotype's keys
(`{hap_prefix}_fa`, `{hap_prefix}_chr_list`, `{hap_prefix}_haplotigs`) —
there is no dual-hap ambiguity to resolve here the way there is in the
primary `pretext_to_asm` (the recuration AGP was curated for exactly one
hap, so there's no "did the tool emit one file or two" guessing needed).

Haplotig merging happens inside `run_pretext_to_asm_recurate`, before
`tracker.finish()` records the step's outputs, covering all four presence
combinations:

1. **Prior canonical haplotigs non-empty, new run's haplotigs non-empty** —
   concatenate the two FASTA files' records into one file in the run_dir
   (plain concatenation, no dedup/sequence comparison).
2. **Prior non-empty, new empty/absent** — carry the prior file forward
   unchanged as this run's haplotigs output; a recuration round that didn't
   surface new haplotigs must not make previously-known ones disappear from
   canonical resolution.
3. **Prior empty/absent, new non-empty** — use the new run's file as-is.
4. **Both empty/absent** — no haplotigs output tracked for this run (same
   as today when `pretext_to_asm` produces none).

"Prior canonical haplotigs" is resolved via `find_canonical_haplotigs(ctx,
hap_prefix)` *before* this run's `tracker.start()`/`finish()` calls happen,
so it still reflects the pre-recuration state and isn't accidentally
comparing the new run's output against itself. "Empty" means missing or a
zero-content placeholder (the same touched-empty-file convention
`haplotig_files.py` already establishes) — not merely "file doesn't exist."

### Canonical file resolution: new, unconditional top tier

`find_canonical_fa`, `find_canonical_chr_list`, and `find_canonical_haplotigs`
(`grit/utils/helpers.py`) each gain a new lookup, checked *before* their
existing chains, for `pretext_to_asm_recurate` (hap1) /
`pretext_to_asm_recurate_hap2` (hap2). If a tracked, non-untracked output
exists for this hap's recurate step name, it wins unconditionally — no
mtime comparison against `rename_and_orient`/`blast_contaminants`/etc., even
if one of those is re-run and produces a newer file *after* recuration. This
is a deliberate, fixed ordering choice (not folded into TODO 40's
mtime-based tiering): recuration is being treated as inherently the final
step in the pipeline for that haplotype, full stop.

If a curator genuinely wants to go back and run `blast-contaminants` or
`rename-and-orient` against the *original* (pre-recurate) `pretext_to_asm`
output instead, the escape hatch is the existing untrack mechanism: `grit
untrack pretext-to-asm-recurate` (extending the CLI's existing untrack
command to recognize this new step name, plumbing straight into
`RunTracker.untrack(step)` which is already step-name-agnostic) removes the
recuration run from consideration, and canonical resolution falls back to
the pre-existing chain immediately.

If a hap's recurate step was never run (the common case for hap2), all three
`find_canonical_*` functions simply find nothing at this new top tier and
fall through to the existing chain unchanged — hap1 and hap2 recuration
status are fully independent, exactly as intended.

### Composite command: `grit post-curation-recurate [--hap2]`

Mirroring the existing `post_curation.py` (`run_pretext_to_asm` →
`run_haplotig_files` → `run_hic_remapping(ctx, run_hap2=run_hap2)`, chained
under one `post-curation` Click command with an *additive* `--hap2`), add
a second composite step file `grit/steps/post_curation/post_curation_recurate.py`
exporting `run_post_curation_recurate(ctx, *, run_hap2: bool = False)` and a
`post-curation-recurate` Click command with the same `--hap2` flag name —
but, unlike `post-curation`'s additive semantics, `--hap2` here is
**exclusive**, matching `pretext-to-asm-recurate`'s own per-hap-exclusive
CLI shape rather than `post-curation`'s "hap1 always plus optional hap2"
shape (recuration is fundamentally a choice of *which single haplotype* to
recurate, not "recurate hap1 and optionally also hap2"):

```python
def run_post_curation_recurate(ctx, *, run_hap2: bool = False) -> None:
    """Run pretext-to-asm-recurate followed by hic-remapping for one haplotype.

    Recurates hap1 by default; pass ``run_hap2=True`` to recurate hap2
    instead (not in addition).
    """
    hap_prefix = ctx.hap2_prefix if run_hap2 else ctx.hap1_prefix
    step_name = "pretext_to_asm_recurate_hap2" if run_hap2 else "pretext_to_asm_recurate"
    run_pretext_to_asm_recurate(ctx, hap_prefix, step_name)
    run_hic_remapping(ctx, run_hap1=not run_hap2, run_hap2=run_hap2)
```

No `run_haplotig_files` call — haplotig presence/merging is already fully
handled inside `run_pretext_to_asm_recurate` itself (see above), so there's
nothing left for that separate step to do for a recuration run.

### Downstream steps — no changes needed

- `hic_remapping.py` needs no changes. Its existing re-run check (compare
  the mtime of its own tracked `*hr.pretext` output against
  `find_canonical_fa(ctx, hap_prefix)`) already re-triggers correctly once
  recuration produces a newer canonical fa — it just runs again under the
  same `hic_remapping`/`hic_remapping_hap2` step name, appending a new
  history record, "latest" naturally becoming the post-recuration remap.
- `finalize_qc.py` needs no changes to its own logic — it already calls
  `find_canonical_fa`/`find_canonical_haplotigs`/`find_canonical_chr_list`
  and will pick up recuration output automatically once those three
  functions are updated. Worth double-checking `_raise_if_yaml_pta_mismatch`
  doesn't choke on a hap whose only `pretext_to_asm`-family record is a
  single-hap recurate run (it currently only inspects the primary
  `pretext_to_asm` record) — expected to be a non-issue since that check is
  about YAML-declared hap count vs. the *original* `pretext_to_asm` run, not
  about recuration, but confirm during implementation.

### Explicitly out of scope

- More than one recuration round (curate → pretext-to-asm →
  hic-remapping → curate again → ...). Confirmed with curators this happens
  in ~5-10% of cases; deliberately not supported, to avoid a
  numbered/unbounded step-name scheme. A curator who needs this today is
  already out of grit's supported path.
- Any hard validation/blocking of step order before recuration — only the
  informational tip described above.
- Haplotig dedup by sequence/name across merged files — plain concatenation
  only.

## Test plan

- `tests/test_helpers_canonical.py`: new cases —
  `pretext_to_asm_recurate` present wins over `rename_and_orient`/
  `blast_contaminants` regardless of relative mtimes; absent falls through
  to the existing (TODO 40) chain unchanged; untracking the recurate step
  reverts resolution to the pre-recuration chain.
- New `tests/test_pretext_to_asm_recurate.py`: the four haplotig-merge
  branches; AGP glob resolves the hap-qualified file under
  `{workdir}/recurate/` and ignores the other hap's file; input FASTA
  resolution delegates to `find_canonical_fa` (mocked `ctx.tracker`, no real
  subprocess, matching existing step test conventions).
- No changes expected to existing `pretext_to_asm`/`hic_remapping` tests —
  new step name, new code path, no shared mutable state.
- New `tests/test_post_curation_recurate.py`: default (no `--hap2`) calls
  `run_pretext_to_asm_recurate` with hap1/`pretext_to_asm_recurate`, then
  `run_hic_remapping(run_hap1=True, run_hap2=False)`; `--hap2` calls the
  hap2 equivalents exclusively (never both) — assert via call inspection on
  mocked `run_pretext_to_asm_recurate`/`run_hic_remapping`, matching how
  `post_curation.py` is already tested.
