# TODO 33: Multi-haplotype support + canonical FASTA resolution

## 1. hic-remapping and rename-and-orient for hap2

### Design decision (agreed)

- `--hap2` CLI flag on `hic-remapping` and `rename-and-orient` commands
- Default behaviour unchanged (hap1 only)
- Internally: extract `_submit_hic_remapping(ctx, hap_prefix, step_name)` and
  `_run_rename_and_orient_for_hap(ctx, hap_prefix, paf, step_name, *, csv_from_hap1)` helpers
- Tracker step names: `hic_remapping` (hap1, existing) + `hic_remapping_hap2` (new);
  `rename_and_orient` (hap1, existing) + `rename_and_orient_hap2` (new)
- `rename_and_orient --hap2` runs hap1 first (synchronous), passes output CSV to hap2 script
- `hic_remapping --hap2` submits hap2 independently of hap1

### Blocked on

Confirm how `rename_and_orient.py` accepts the hap1 table for hap2 run
(flag name: `--csv`? `--table`? — check `rename_and_orient.py --help`).

### Also extract

`find_curated_fa(ctx, hap_prefix) -> Path` helper in `grit/utils/helpers.py` —
hic_remapping, rename_and_orient, and fastga all duplicate the same glob logic.

---

## 2. Canonical FASTA resolution after rename-and-orient

### Problem

After `rename-and-orient` runs, its output FASTA becomes the assembly that goes to
publication and all subsequent steps (hic-remapping, finalize-qc, etc.).
Currently downstream steps always look in `pretext_to_asm/` and would ignore the
renamed assembly.

### Proposed solution

Add `find_canonical_fa(ctx, hap_prefix: str) -> Path` to `grit/utils/helpers.py`.

Priority order:
1. Latest `rename_and_orient` run dir — `{tol_id}*{hap_prefix}*.renamed*.fa`
2. Latest `pretext_to_asm` run dir — `{tol_id}*{hap_prefix}*.curated.fa` (excluding all_haplotigs)

All downstream steps call `find_canonical_fa` instead of their own globs.
When a new intermediate step produces a derived assembly, only this one function changes.

### Steps to update once helper exists

- `hic_remapping.py` (currently uses inline glob)
- `finalize_qc.py` (check if it globs for FASTA)
- `fastga.py`
- `rename_and_orient.py` (hap2 path)
- Any future steps that consume a curated assembly
