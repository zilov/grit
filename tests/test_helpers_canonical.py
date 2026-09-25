"""Tests for the canonical-output priority chain in grit/utils/helpers.py."""

import itertools
import os

import pytest

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.utils.helpers import (
    find_canonical_chr_list,
    find_canonical_fa,
    find_canonical_haplotigs,
    find_canonical_map,
    find_curated_fa,
)


def _make_tracker(tmp_path, ctx):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)
    return ctx.tracker


_MTIMES = itertools.count(1_000_000, 10)


def _write(path):
    """Write *path* with an mtime strictly later than every earlier ``_write``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(">seq\n")
    mtime = next(_MTIMES)
    os.utime(path, (mtime, mtime))
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


def test_untracking_microchromosome_combine_falls_back_to_pretext_to_asm(mock_ctx, tmp_path):
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

    tracker.untrack("microchromosome_combine")
    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


def test_untracking_rename_and_orient_falls_back_to_next_freshest(mock_ctx, tmp_path):
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

    tracker.untrack("rename_and_orient")
    assert find_canonical_fa(mock_ctx, "hap1") == bc_fa


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

    os.utime(pta_fa, (1000, 1000))
    os.utime(bc_fa, (2000, 2000))
    os.utime(rao_fa, (3000, 3000))
    os.utime(pta_fa2, (4000, 4000))

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa2


def test_blast_contaminants_rerun_after_rename_and_orient_wins(mock_ctx, tmp_path):
    """A fresh blast_contaminants re-run must beat a now-stale rename_and_orient output."""
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


def test_pool_tie_break_favors_first_listed_step(mock_ctx, tmp_path):
    """On an exact mtime tie between two pool members, the first-listed step
    (pretext_to_asm, earlier in the flat pool order) wins."""
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

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


def test_blast_contaminants_after_recurate_with_newer_mtime_wins(mock_ctx, tmp_path):
    """blast_contaminants run after pretext_to_asm_recurate, with a newer mtime,
    correctly becomes canonical — recuration is no longer an unconditional top tier."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    recurate_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-01T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", recurate_dir, "success", outputs={"hap1_fa": str(recurate_fa)}
    )

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    os.utime(recurate_fa, (1000, 1000))
    os.utime(bc_fa, (2000, 2000))

    assert find_canonical_fa(mock_ctx, "hap1") == bc_fa


def test_rename_and_orient_after_recurate_with_newer_mtime_wins(mock_ctx, tmp_path):
    """rename_and_orient run after pretext_to_asm_recurate, with a newer mtime,
    correctly becomes canonical."""
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
    os.utime(rao_fa, (2000, 2000))

    assert find_canonical_fa(mock_ctx, "hap1") == rao_fa


def test_pretext_to_asm_rerun_after_recurate_with_newer_mtime_wins(mock_ctx, tmp_path):
    """A fresh pretext_to_asm re-run correctly wins back over a stale recurate
    output, matching the recency-wins model applied to the rest of the pool."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    recurate_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-01T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", recurate_dir, "success", outputs={"hap1_fa": str(recurate_fa)}
    )

    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-02T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    os.utime(recurate_fa, (1000, 1000))
    os.utime(pta_fa, (2000, 2000))

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


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


def test_rename_and_orient_chr_list_beats_older_pretext_to_asm(mock_ctx, tmp_path):
    """Regression for the missing rename_and_orient chr_list output-spec key:
    a freshly-tracked rename_and_orient chromosome list must now displace an
    older pretext_to_asm one, instead of find_canonical_chr_list returning
    before it ever considers rename_and_orient (previously impossible since
    rename_and_orient never had a tracked chr_list output at all)."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_chr_list = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.chromosome.list.csv")
    tracker.finish(
        "pretext_to_asm", pta_dir, "success", outputs={"hap1_chr_list": str(pta_chr_list)}
    )

    rao_dir = tmp_path / "rename_and_orient" / "2026-01-02T00_00_00"
    rao_chr_list = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.chromosome.list.csv")
    tracker.finish(
        "rename_and_orient", rao_dir, "success", outputs={"hap1_chr_list": str(rao_chr_list)}
    )

    os.utime(pta_chr_list, (1000, 1000))
    os.utime(rao_chr_list, (2000, 2000))

    assert find_canonical_chr_list(mock_ctx, "hap1") == rao_chr_list


def test_pretext_to_asm_chr_list_rerun_after_rename_and_orient_wins(mock_ctx, tmp_path):
    """The reverse direction: a fresher pretext_to_asm/recurate chr_list must
    still be able to displace an older rename_and_orient one — proving the
    mtime pool genuinely competes both ways, not just that rename_and_orient
    always wins once tracked."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    rao_dir = tmp_path / "rename_and_orient" / "2026-01-01T00_00_00"
    rao_chr_list = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.chromosome.list.csv")
    tracker.finish(
        "rename_and_orient", rao_dir, "success", outputs={"hap1_chr_list": str(rao_chr_list)}
    )

    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-02T00_00_00"
    pta_chr_list = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.chromosome.list.csv")
    tracker.finish(
        "pretext_to_asm", pta_dir, "success", outputs={"hap1_chr_list": str(pta_chr_list)}
    )

    os.utime(rao_chr_list, (1000, 1000))
    os.utime(pta_chr_list, (2000, 2000))

    assert find_canonical_chr_list(mock_ctx, "hap1") == pta_chr_list


def test_chr_list_from_newer_run_dir_wins_when_output_key_was_not_recorded(mock_ctx, tmp_path):
    """A newer pretext_to_asm run whose chr_list never made it into the tracked
    outputs must still win over an older rename_and_orient one: the file is in
    that run's dir, so resolution re-globs the run dir instead of silently
    falling back to the stale step."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    rao_dir = tmp_path / "rename_and_orient" / "2026-01-01T00_00_00"
    rao_chr_list = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.chromosome.list.csv")
    tracker.finish(
        "rename_and_orient", rao_dir, "success", outputs={"hap1_chr_list": str(rao_chr_list)}
    )

    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-02T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    pta_chr_list = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.chromosome.list.csv")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    os.utime(rao_chr_list, (1000, 1000))
    os.utime(pta_chr_list, (2000, 2000))

    assert find_canonical_chr_list(mock_ctx, "hap1") == pta_chr_list


def test_chr_list_of_latest_run_beats_earlier_run_of_the_same_step(mock_ctx, tmp_path):
    """When the latest run of a step recorded no chr_list, an earlier run of
    that same step must not stand in for it — the latest run dir's own file is
    what the step currently offers."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    old_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    old_chr_list = _write(old_dir / f"{mock_ctx.tol_id}.hap1.1.chromosome.list.csv")
    tracker.finish(
        "pretext_to_asm", old_dir, "success", outputs={"hap1_chr_list": str(old_chr_list)}
    )

    new_dir = tmp_path / "pretext_to_asm" / "2026-01-03T00_00_00"
    new_fa = _write(new_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    new_chr_list = _write(new_dir / f"{mock_ctx.tol_id}.hap1.1.chromosome.list.csv")
    tracker.finish("pretext_to_asm", new_dir, "success", outputs={"hap1_fa": str(new_fa)})

    os.utime(old_chr_list, (1000, 1000))
    os.utime(new_chr_list, (2000, 2000))

    assert find_canonical_chr_list(mock_ctx, "hap1") == new_chr_list


# ---------------------------------------------------------------------------
# find_canonical_map — the canonical remapped Pretext map per haplotype
# ---------------------------------------------------------------------------


def _write_map(run_dir, tol_id, hap_token):
    """Write a hic-remapping run's normal.pretext (shipped) and hr.pretext (farm-only)."""
    processed = run_dir / "pretext_maps_processed"
    normal = _write(processed / f"{tol_id}.{hap_token}_normal.pretext")
    _write(processed / f"{tol_id}.{hap_token}_hr.pretext")
    return normal


def test_canonical_map_is_the_latest_hic_remapping_run(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    old_dir = tmp_path / "hic_remapping" / "2026-01-01T00_00_00"
    old_map = _write_map(old_dir, mock_ctx.tol_id, "hap1")
    tracker.finish(
        "hic_remapping", old_dir, "success", outputs={"hap1_normal_pretext": str(old_map)}
    )

    new_dir = tmp_path / "hic_remapping" / "2026-01-02T00_00_00"
    new_map = _write_map(new_dir, mock_ctx.tol_id, "hap1")
    tracker.finish(
        "hic_remapping", new_dir, "success", outputs={"hap1_normal_pretext": str(new_map)}
    )

    assert find_canonical_map(mock_ctx, "hap1") == new_map


def test_canonical_map_ignores_the_hr_map(mock_ctx, tmp_path):
    """hr.pretext is the curation input and stays on the farm; only normal.pretext ships."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    run_dir = tmp_path / "hic_remapping" / "2026-01-01T00_00_00"
    normal = _write_map(run_dir, mock_ctx.tol_id, "hap1")
    tracker.finish(
        "hic_remapping",
        run_dir,
        "success",
        outputs={
            "hap1_pretext": str(
                run_dir / "pretext_maps_processed" / f"{mock_ctx.tol_id}.hap1_hr.pretext"
            ),
            "hap1_normal_pretext": str(normal),
        },
    )

    assert find_canonical_map(mock_ctx, "hap1") == normal


def test_canonical_map_skips_an_untracked_run(mock_ctx, tmp_path):
    """The newest run dir on disk loses to the older one when it was untracked."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    kept_dir = tmp_path / "hic_remapping" / "2026-01-01T00_00_00"
    kept_map = _write_map(kept_dir, mock_ctx.tol_id, "hap1")
    tracker.finish(
        "hic_remapping", kept_dir, "success", outputs={"hap1_normal_pretext": str(kept_map)}
    )

    rejected_dir = tmp_path / "hic_remapping" / "2026-01-02T00_00_00"
    rejected_map = _write_map(rejected_dir, mock_ctx.tol_id, "hap1")
    tracker.finish(
        "hic_remapping",
        rejected_dir,
        "success",
        outputs={"hap1_normal_pretext": str(rejected_map)},
        untracked=True,
    )

    assert find_canonical_map(mock_ctx, "hap1") == kept_map


def test_canonical_map_falls_back_to_the_filesystem(mock_ctx, tmp_path):
    _make_tracker(tmp_path, mock_ctx)
    run_dir = tmp_path / "hic_remapping" / "2026-01-01T00_00_00"
    fs_map = _write_map(run_dir, mock_ctx.tol_id, "hap1")

    assert find_canonical_map(mock_ctx, "hap1") == fs_map


def test_canonical_map_hap2_comes_from_hic_remapping_hap2(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    hap1_dir = tmp_path / "hic_remapping" / "2026-01-01T00_00_00"
    hap1_map = _write_map(hap1_dir, mock_ctx.tol_id, "hap1")
    tracker.finish(
        "hic_remapping", hap1_dir, "success", outputs={"hap1_normal_pretext": str(hap1_map)}
    )

    hap2_dir = tmp_path / "hic_remapping_hap2" / "2026-01-02T00_00_00"
    hap2_map = _write_map(hap2_dir, mock_ctx.tol_id, "hap2")
    tracker.finish(
        "hic_remapping_hap2", hap2_dir, "success", outputs={"hap2_normal_pretext": str(hap2_map)}
    )

    assert find_canonical_map(mock_ctx, "hap1") == hap1_map
    assert find_canonical_map(mock_ctx, "hap2") == hap2_map


def test_canonical_map_has_no_hap2_for_a_single_hap_ticket(mock_ctx_primary, tmp_path):
    """A primary/alternate ticket has no genuine hap2 — never hand back hap1's map."""
    tracker = _make_tracker(tmp_path, mock_ctx_primary)
    run_dir = tmp_path / "hic_remapping" / "2026-01-01T00_00_00"
    hap1_map = _write_map(run_dir, mock_ctx_primary.tol_id, "hap1")
    tracker.finish(
        "hic_remapping", run_dir, "success", outputs={"hap1_normal_pretext": str(hap1_map)}
    )

    assert find_canonical_map(mock_ctx_primary, "primary") == hap1_map
    with pytest.raises(FileNotFoundError):
        find_canonical_map(mock_ctx_primary, "alternate")


def test_canonical_map_raises_when_no_map_exists(mock_ctx, tmp_path):
    _make_tracker(tmp_path, mock_ctx)
    with pytest.raises(FileNotFoundError):
        find_canonical_map(mock_ctx, "hap1")


# ---------------------------------------------------------------------------
# find_canonical_haplotigs — the haplotig FASTA per haplotype
# ---------------------------------------------------------------------------


def _pta_dir(tmp_path, ts="2026-01-01T00_00_00"):
    return tmp_path / "pretext_to_asm" / ts


def test_haplotigs_come_from_the_tracked_pretext_to_asm_output(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = _pta_dir(tmp_path)
    hap1 = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    hap2 = _write(pta_dir / f"{mock_ctx.tol_id}.hap2.1.all_haplotigs.curated.fa")
    tracker.finish(
        "pretext_to_asm",
        pta_dir,
        "success",
        outputs={"hap1_haplotigs": str(hap1), "hap2_haplotigs": str(hap2)},
    )

    assert find_canonical_haplotigs(mock_ctx, "hap1") == hap1
    assert find_canonical_haplotigs(mock_ctx, "hap2") == hap2


def test_haplotigs_of_a_newer_recurate_round_win(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = _pta_dir(tmp_path)
    pta_hap = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_haplotigs": str(pta_hap)})

    rec_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-02T00_00_00"
    rec_hap = _write(rec_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", rec_dir, "success", outputs={"hap1_haplotigs": str(rec_hap)}
    )

    assert find_canonical_haplotigs(mock_ctx, "hap1") == rec_hap


def test_haplotigs_of_a_pretext_to_asm_rerun_beat_an_older_recurate(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    rec_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-01T00_00_00"
    rec_hap = _write(rec_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", rec_dir, "success", outputs={"hap1_haplotigs": str(rec_hap)}
    )

    pta_dir = _pta_dir(tmp_path, "2026-01-02T00_00_00")
    pta_hap = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_haplotigs": str(pta_hap)})

    assert find_canonical_haplotigs(mock_ctx, "hap1") == pta_hap


def test_haplotigs_hap2_recurate_does_not_touch_hap1(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = _pta_dir(tmp_path)
    pta_hap1 = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    pta_hap2 = _write(pta_dir / f"{mock_ctx.tol_id}.hap2.1.all_haplotigs.curated.fa")
    tracker.finish(
        "pretext_to_asm",
        pta_dir,
        "success",
        outputs={"hap1_haplotigs": str(pta_hap1), "hap2_haplotigs": str(pta_hap2)},
    )

    rec_dir = tmp_path / "pretext_to_asm_recurate_hap2" / "2026-01-02T00_00_00"
    rec_hap2 = _write(rec_dir / f"{mock_ctx.tol_id}.hap2.1.all_haplotigs.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate_hap2",
        rec_dir,
        "success",
        outputs={"hap2_haplotigs": str(rec_hap2)},
    )

    assert find_canonical_haplotigs(mock_ctx, "hap1") == pta_hap1
    assert find_canonical_haplotigs(mock_ctx, "hap2") == rec_hap2


def test_haplotigs_of_an_untracked_recurate_do_not_count(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = _pta_dir(tmp_path)
    pta_hap = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_haplotigs": str(pta_hap)})

    rec_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-02T00_00_00"
    rec_hap = _write(rec_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate",
        rec_dir,
        "success",
        outputs={"hap1_haplotigs": str(rec_hap)},
        untracked=True,
    )

    assert find_canonical_haplotigs(mock_ctx, "hap1") == pta_hap


def test_haplotigs_unrecorded_in_the_latest_run_are_re_globbed(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = _pta_dir(tmp_path)
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    pta_hap = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    assert find_canonical_haplotigs(mock_ctx, "hap1") == pta_hap


def test_haplotigs_fall_back_to_a_hap_specific_file_on_disk(mock_ctx, tmp_path):
    _make_tracker(tmp_path, mock_ctx)
    pta_dir = _pta_dir(tmp_path)
    hap2 = _write(pta_dir / f"{mock_ctx.tol_id}.hap2.1.haplotigs.fa")

    assert find_canonical_haplotigs(mock_ctx, "hap2") == hap2


def test_haplotigs_fall_back_through_the_primary_to_hap1_alias(mock_ctx_primary, tmp_path):
    _make_tracker(tmp_path, mock_ctx_primary)
    pta_dir = _pta_dir(tmp_path)
    hap = _write(pta_dir / f"{mock_ctx_primary.tol_id}.hap1.1.all_haplotigs.curated.fa")

    assert find_canonical_haplotigs(mock_ctx_primary, "primary") == hap


def test_combined_haplotigs_go_to_hap1_only(mock_ctx, tmp_path):
    """The dual-hap combined file has no hap token; handing it to both haps would
    copy the same haplotigs twice."""
    _make_tracker(tmp_path, mock_ctx)
    combined = _write(_pta_dir(tmp_path) / f"{mock_ctx.tol_id}.1.haplotigs.fa")

    assert find_canonical_haplotigs(mock_ctx, "hap1") == combined
    with pytest.raises(FileNotFoundError):
        find_canonical_haplotigs(mock_ctx, "hap2")


def test_single_hap_additional_haplotigs_are_found(mock_ctx_primary, tmp_path):
    _make_tracker(tmp_path, mock_ctx_primary)
    extra = _write(
        _pta_dir(tmp_path) / f"{mock_ctx_primary.tol_id}.1.additional_haplotigs.curated.fa"
    )

    assert find_canonical_haplotigs(mock_ctx_primary, "primary") == extra


def test_haplotigs_raise_when_nothing_exists(mock_ctx, tmp_path):
    _make_tracker(tmp_path, mock_ctx)
    _pta_dir(tmp_path).mkdir(parents=True)

    with pytest.raises(FileNotFoundError):
        find_canonical_haplotigs(mock_ctx, "hap1")


# ---------------------------------------------------------------------------
# DOM-06 / report 06 trace T7: a primary/alternate ticket has no hap2
# ---------------------------------------------------------------------------


def _single_hap_pta_run(tmp_path, ctx, *, tracked=True):
    """A primary ticket's pretext-to-asm output: unprefixed fa, chr list, haplotigs."""
    tracker = _make_tracker(tmp_path, ctx)
    pta_dir = _pta_dir(tmp_path)
    fa = _write(pta_dir / f"{ctx.tol_id}.1.primary.curated.fa")
    chr_list = _write(pta_dir / f"{ctx.tol_id}.1.primary.chromosome.list.csv")
    haplotigs = _write(pta_dir / f"{ctx.tol_id}.1.all_haplotigs.curated.fa")
    if tracked:
        tracker.finish(
            "pretext_to_asm",
            pta_dir,
            "success",
            outputs={
                "hap1_fa": str(fa),
                "hap1_chr_list": str(chr_list),
                "hap1_haplotigs": str(haplotigs),
            },
        )
    return fa, chr_list, haplotigs


@pytest.mark.parametrize("tracked", [True, False], ids=["tracked", "filesystem"])
@pytest.mark.parametrize(
    "finder",
    [find_canonical_fa, find_canonical_chr_list, find_canonical_haplotigs, find_curated_fa],
    ids=lambda f: f.__name__,
)
def test_trace_t7_single_hap_ticket_has_no_alternate_files(
    mock_ctx_primary, tmp_path, finder, tracked
):
    """Resolving 'alternate' on a primary ticket must refuse, not return hap1's file."""
    _single_hap_pta_run(tmp_path, mock_ctx_primary, tracked=tracked)

    with pytest.raises(FileNotFoundError, match="single-haplotype"):
        finder(mock_ctx_primary, "alternate")


def test_single_hap_ticket_still_resolves_primary(mock_ctx_primary, tmp_path):
    fa, chr_list, haplotigs = _single_hap_pta_run(tmp_path, mock_ctx_primary)

    assert find_canonical_fa(mock_ctx_primary, "primary") == fa
    assert find_canonical_chr_list(mock_ctx_primary, "primary") == chr_list
    assert find_canonical_haplotigs(mock_ctx_primary, "primary") == haplotigs


# ---------------------------------------------------------------------------
# DOM-02 / report 06 trace T3: an in-flight run's files are not canonical
# ---------------------------------------------------------------------------


def _pta_success(tmp_path, ctx, ts="2026-01-01T00_00_00"):
    pta_dir = _pta_dir(tmp_path, ts)
    fa = _write(pta_dir / f"{ctx.tol_id}.hap1.1.curated.fa")
    chr_list = _write(pta_dir / f"{ctx.tol_id}.hap1.1.chromosome.list.csv")
    ctx.tracker.finish(
        "pretext_to_asm",
        pta_dir,
        "success",
        outputs={"hap1_fa": str(fa), "hap1_chr_list": str(chr_list)},
    )
    return fa, chr_list


def test_trace_t3_in_flight_rename_and_orient_is_not_canonical(mock_ctx, tmp_path):
    """rename-and-orient's bsub job is still writing: canonical stays pretext-to-asm's."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_fa, pta_chr = _pta_success(tmp_path, mock_ctx)

    rao_dir = tracker.start("rename_and_orient", mock_ctx.ticket_id, mock_ctx.tol_id)
    tracker.record_job("rename_and_orient", rao_dir, "12345")
    _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")  # half-written
    _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.chromosome.list.csv")

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa
    assert find_canonical_chr_list(mock_ctx, "hap1") == pta_chr


def test_in_flight_rerun_leaves_the_previous_run_of_the_step_canonical(mock_ctx, tmp_path):
    """A second rename-and-orient run in flight must not hide the first, finished one."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    _pta_success(tmp_path, mock_ctx)

    done_dir = tmp_path / "rename_and_orient" / "2026-01-02T00_00_00"
    done_fa = _write(done_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", done_dir, "success", outputs={"hap1_fa": str(done_fa)})

    running_dir = tracker.start("rename_and_orient", mock_ctx.ticket_id, mock_ctx.tol_id)
    _write(running_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")

    assert find_canonical_fa(mock_ctx, "hap1") == done_fa


def test_in_flight_recurate_haplotigs_are_not_canonical(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = _pta_dir(tmp_path)
    pta_hap = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_haplotigs": str(pta_hap)})

    rec_dir = tracker.start("pretext_to_asm_recurate", mock_ctx.ticket_id, mock_ctx.tol_id)
    _write(rec_dir / f"{mock_ctx.tol_id}.hap1.1.all_haplotigs.curated.fa")

    assert find_canonical_haplotigs(mock_ctx, "hap1") == pta_hap


def test_in_flight_hic_remapping_map_is_not_canonical(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    done_dir = tmp_path / "hic_remapping" / "2026-01-01T00_00_00"
    done_map = _write_map(done_dir, mock_ctx.tol_id, "hap1")
    tracker.finish(
        "hic_remapping", done_dir, "success", outputs={"hap1_normal_pretext": str(done_map)}
    )

    running_dir = tracker.start("hic_remapping", mock_ctx.ticket_id, mock_ctx.tol_id)
    _write_map(running_dir, mock_ctx.tol_id, "hap1")

    assert find_canonical_map(mock_ctx, "hap1") == done_map
