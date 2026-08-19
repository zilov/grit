"""Tests for the canonical-output priority chain in grit/utils/helpers.py."""

import pytest

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.utils.helpers import find_canonical_fa, find_curated_fa


def _make_tracker(tmp_path, ctx):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)
    return ctx.tracker


def _write(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(">seq\n")
    return path


def test_falls_back_to_pretext_to_asm_when_nothing_else_ran(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.start("pretext_to_asm", mock_ctx.ticket_id, mock_ctx.tol_id)
    tracker.finish(
        "pretext_to_asm",
        pta_dir,
        "success",
        outputs={"hap1_fa": str(pta_fa)},
    )

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


def test_blast_contaminants_beats_pretext_to_asm(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    assert find_canonical_fa(mock_ctx, "hap1") == bc_fa


def test_rename_and_orient_beats_blast_contaminants(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    rao_dir = tmp_path / "rename_and_orient" / "2026-01-03T00_00_00"
    rao_fa = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    assert find_canonical_fa(mock_ctx, "hap1") == rao_fa


def test_microchromosome_combine_beats_pretext_to_asm(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    combine_dir = tmp_path / "microchromosome_combine" / "2026-01-02T00_00_00"
    combine_fa = _write(combine_dir / f"{mock_ctx.tol_id}.hap1.fa")
    tracker.finish(
        "microchromosome_combine", combine_dir, "success", outputs={"hap1_fa": str(combine_fa)}
    )

    assert find_canonical_fa(mock_ctx, "hap1") == combine_fa


def test_blast_contaminants_beats_microchromosome_combine(mock_ctx, tmp_path):
    """blast_contaminants/rename_and_orient happen chronologically after the
    micro workflow — they must still win once they've run."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    combine_dir = tmp_path / "microchromosome_combine" / "2026-01-01T00_00_00"
    combine_fa = _write(combine_dir / f"{mock_ctx.tol_id}.hap1.fa")
    tracker.finish(
        "microchromosome_combine", combine_dir, "success", outputs={"hap1_fa": str(combine_fa)}
    )

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    assert find_canonical_fa(mock_ctx, "hap1") == bc_fa


def test_rename_and_orient_beats_microchromosome_combine(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    combine_dir = tmp_path / "microchromosome_combine" / "2026-01-01T00_00_00"
    combine_fa = _write(combine_dir / f"{mock_ctx.tol_id}.hap1.fa")
    tracker.finish(
        "microchromosome_combine", combine_dir, "success", outputs={"hap1_fa": str(combine_fa)}
    )

    rao_dir = tmp_path / "rename_and_orient" / "2026-01-02T00_00_00"
    rao_fa = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    assert find_canonical_fa(mock_ctx, "hap1") == rao_fa


def test_untracking_blast_contaminants_falls_back_to_pretext_to_asm(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})
    assert find_canonical_fa(mock_ctx, "hap1") == bc_fa

    tracker.untrack("blast_contaminants")
    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


def test_find_curated_fa_does_not_fall_back_to_unprefixed_for_dual_hap(mock_ctx, tmp_path):
    """hap1/hap2 YAML but the curator never split haplotypes, so pretext-to-asm
    produced only an unprefixed (primary-style) fa. Must raise, not silently
    resolve both hap1 and hap2 to the same unprefixed file."""
    mock_ctx.workdir = tmp_path
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    _write(pta_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")

    with pytest.raises(FileNotFoundError):
        find_curated_fa(mock_ctx, "hap1")
    with pytest.raises(FileNotFoundError):
        find_curated_fa(mock_ctx, "hap2")


def test_find_curated_fa_unprefixed_fallback_still_works_for_single_hap(mock_ctx_primary, tmp_path):
    """primary/alternate YAML with only an unprefixed curated fa on disk must still
    resolve via the single-hap fallback."""
    mock_ctx_primary.workdir = tmp_path
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    unprefixed_fa = _write(pta_dir / f"{mock_ctx_primary.tol_id}.1.primary.curated.fa")

    assert find_curated_fa(mock_ctx_primary, "primary") == unprefixed_fa


def test_pretext_to_asm_rerun_after_rename_and_orient_wins(mock_ctx, tmp_path):
    """A fresh pretext_to_asm re-run must beat a now-stale rename_and_orient output."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    rao_dir = tmp_path / "rename_and_orient" / "2026-01-03T00_00_00"
    rao_fa = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    # curator fixes the AGP and re-runs pretext_to_asm — its new output is
    # chronologically the newest file, even though it's earlier in the fixed list
    pta_dir2 = tmp_path / "pretext_to_asm" / "2026-01-04T00_00_00"
    pta_fa2 = _write(pta_dir2 / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir2, "success", outputs={"hap1_fa": str(pta_fa2)})

    import os

    os.utime(pta_fa, (1000, 1000))
    os.utime(bc_fa, (2000, 2000))
    os.utime(rao_fa, (3000, 3000))
    os.utime(pta_fa2, (4000, 4000))

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa2


def test_blast_contaminants_rerun_after_rename_and_orient_wins(mock_ctx, tmp_path):
    """A fresh blast_contaminants re-run must beat a now-stale rename_and_orient output."""
    import os

    tracker = _make_tracker(tmp_path, mock_ctx)
    rao_dir = tmp_path / "rename_and_orient" / "2026-01-01T00_00_00"
    rao_fa = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    os.utime(rao_fa, (1000, 1000))
    os.utime(bc_fa, (2000, 2000))

    assert find_canonical_fa(mock_ctx, "hap1") == bc_fa


def test_microchromosome_combine_rerun_after_blast_contaminants_wins(mock_ctx, tmp_path):
    """A fresh microchromosome_combine re-run must beat a now-stale blast_contaminants
    output — recency wins within and across tiers, tier order is only a tie-break."""
    import os

    tracker = _make_tracker(tmp_path, mock_ctx)
    bc_dir = tmp_path / "blast_contaminants" / "2026-01-01T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    combine_dir = tmp_path / "microchromosome_combine" / "2026-01-02T00_00_00"
    combine_fa = _write(combine_dir / f"{mock_ctx.tol_id}.hap1.fa")
    tracker.finish(
        "microchromosome_combine", combine_dir, "success", outputs={"hap1_fa": str(combine_fa)}
    )

    os.utime(bc_fa, (1000, 1000))
    os.utime(combine_fa, (2000, 2000))

    assert find_canonical_fa(mock_ctx, "hap1") == combine_fa


def test_result_tier_wins_mtime_tie_with_baseline_tier(mock_ctx, tmp_path):
    """On an exact mtime tie between result tier and baseline tier, result tier wins."""
    import os

    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    # Set both to identical mtime
    os.utime(pta_fa, (5000, 5000))
    os.utime(bc_fa, (5000, 5000))

    assert find_canonical_fa(mock_ctx, "hap1") == bc_fa


def test_recurate_wins_unconditionally_over_newer_rename_and_orient(mock_ctx, tmp_path):
    """Recuration is a fixed top tier — it wins even if rename_and_orient is
    re-run afterward with a newer mtime (unlike the mtime-tiered chain below it)."""
    import os

    tracker = _make_tracker(tmp_path, mock_ctx)
    recurate_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-01T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", recurate_dir, "success", outputs={"hap1_fa": str(recurate_fa)}
    )

    rao_dir = tmp_path / "rename_and_orient" / "2026-01-02T00_00_00"
    rao_fa = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    os.utime(recurate_fa, (1000, 1000))
    os.utime(rao_fa, (2000, 2000))  # newer, but must still lose to recurate

    assert find_canonical_fa(mock_ctx, "hap1") == recurate_fa


def test_recurate_absent_falls_through_to_existing_chain(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


def test_recurate_is_per_hap_independent(mock_ctx, tmp_path):
    """hap1 recurated, hap2 did not — hap2 must still resolve via the normal chain."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    recurate_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-01T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", recurate_dir, "success", outputs={"hap1_fa": str(recurate_fa)}
    )

    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_hap2_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap2.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap2_fa": str(pta_hap2_fa)})

    assert find_canonical_fa(mock_ctx, "hap1") == recurate_fa
    assert find_canonical_fa(mock_ctx, "hap2") == pta_hap2_fa


def test_untracking_recurate_falls_back_to_pre_recuration_chain(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    recurate_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-02T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", recurate_dir, "success", outputs={"hap1_fa": str(recurate_fa)}
    )
    assert find_canonical_fa(mock_ctx, "hap1") == recurate_fa

    tracker.untrack("pretext_to_asm_recurate")
    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


def test_recurate_hap2_step_name_used_for_hap2(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    recurate_dir = tmp_path / "pretext_to_asm_recurate_hap2" / "2026-01-01T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate_hap2",
        recurate_dir,
        "success",
        outputs={"hap2_fa": str(recurate_fa)},
    )

    assert find_canonical_fa(mock_ctx, "hap2") == recurate_fa
