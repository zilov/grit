# 56 — Canonical Pretext map in the canonical-files table

## Problem

`grit status -t <ticket>` resolves and displays the canonical assembly FASTA,
haplotigs FASTA and chromosome list per haplotype, but not the canonical
Pretext map. The map is what the curator actually opens next, and "which map is
the current one?" is asked as often as "which FASTA is the current one?" —
today it is answered by hand, by looking at which `hic_remapping` run dir is
newest.

It is not only a display gap. `finalize-qc` ships the map to the curated-maps
NFS dir, and resolved it with `find_latest_dir(ctx, "hic_remapping")` plus a
glob — the alphabetically-last run dir on disk, which ignores the tracker
entirely. A ticket accumulates one hic-remapping run per recuration round, so
that could ship an older or an explicitly untracked round's map.

## Design

A fourth canonical type resolved like the other three: `find_canonical_map` in
`grit/utils/helpers.py`, freshest existing tracked output winning, with a
filesystem fallback when nothing is tracked.

Points settled before implementing:

- **Which steps own a map.** Only `hic_remapping` / `hic_remapping_hap2`, and
  only their `*normal.pretext` output (`hap{1,2}_normal_pretext`). The
  `hr.pretext` beside it is the curation input and stays on the farm.
  `setup`'s staged draft map is *not* canonical — a ticket has a canonical map
  only once hic-remapping has run.
- **Per-haplotype.** One row per haplotype like the other types. The pool is a
  single step per haplotype, and each haplotype resolves only from its own step
  and output key: no alias or no-prefix fallback, since handing hap1's file
  back for hap2 would publish the wrong haplotype's Hi-C map to NFS. A
  single-hap assembly (`is_single_hap`) has no hap2 map and raises instead.
- **The Canonical column.** `_canonical_mark()` gained a `map` code. Its
  re-glob of the row's run dir now matches a canonical file anywhere *under*
  the run dir, because the map lives in a `pretext_maps_processed/` subdir
  rather than the run dir itself.
- **Consumers.** `finalize_qc`'s NFS copy and `grit status`'s scp download tip
  both take the canonical map. The tip is therefore no longer driven by
  `_SCP_TIP_STEPS`. No step consumes the canonical map as an *input*.

## Out of scope

`find_canonical_map`'s filesystem fallback still ignores untracked runs' dirs,
like the other three resolvers — that is `DOM-03` in `TODO/50` Batch 4, together
with item 2 of `TODO/52`. Switching `finalize-qc` to the resolver closes that
hole for the map on the normal (tracked) path only.
