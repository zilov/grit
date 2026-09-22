# 56 — Canonical Pretext map in the canonical-files table

## Problem

`grit status -t <ticket>` resolves and displays the canonical assembly FASTA,
haplotigs FASTA and chromosome list per haplotype, but not the canonical
Pretext map. The map is what the curator actually opens next, and "which map is
the current one?" is asked as often as "which FASTA is the current one?" —
today it is answered by hand, by looking at which `hic_remapping` run dir is
newest.

## Design

Add a fourth canonical type resolved the same way as the existing three: a flat,
mtime-ordered pool of the tracker steps that produce a map, freshest existing
tracked output wins, with a filesystem fallback when nothing is tracked
(`find_canonical_map` in `grit/utils/helpers.py`, mirroring `find_canonical_fa`).

Open points to settle before implementing:

- **Which steps own a map.** `hic_remapping` / `hic_remapping_hap2`
  certainly. Does `setup`'s staged draft map count as the canonical map before
  any remapping, the way the draft FASTA does for the FASTA fallback? Does
  `curationpretext` output from any other step qualify?
- **Per-haplotype or not.** `hic_remapping` is exclusive per haplotype, so a
  diploid ticket has two maps; the table should show one row per haplotype like
  the other types.
- **The Canonical column.** `_canonical_mark()` in `grit/core/status.py` emits
  per-type codes (`fa`/`hap`/`chr`); this adds a `map` code, and
  `docs/recuration-canonical-priority.md` needs the new type in its decision
  path and flowchart.
- **finalize-qc** does not ship the map, so this is display and
  curator-guidance only — no step should start consuming "the canonical map"
  without a separate decision.
