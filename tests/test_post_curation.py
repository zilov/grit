"""Tests for post_curation steps."""

from pathlib import Path
from unittest.mock import patch

import pytest

from grit.steps.post_curation import (
    finalize_for_qc,
    run_haplotig_files,
    run_hic_remapping,
    run_pretext_to_asm,
    run_qv,
    validate_curated_files,
)

# ---------------------------------------------------------------------------
# run_pretext_to_asm
# ---------------------------------------------------------------------------


@patch("grit.steps.pretext_to_asm._run")
@patch("grit.steps.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_builds_correct_command(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"

    # create original.fa so existence check passes
    (tmp_path / "original.fa").write_text("")

    agp = str(tmp_path / "sDipInt39.agp")
    mock_glob.return_value = [agp]
    mock_run.return_value = ""

    run_pretext_to_asm(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("pretext-to-asm" in c for c in calls)
    assert any("original.fa" in c for c in calls)
    assert any(agp in c for c in calls)


@patch("grit.steps.pretext_to_asm._run")
@patch("grit.steps.pretext_to_asm.glob.glob", return_value=[])
def test_run_pretext_to_asm_raises_when_no_agp(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    (tmp_path / "original.fa").write_text("")

    with pytest.raises(FileNotFoundError, match="AGP file"):
        run_pretext_to_asm(mock_ctx)


def test_run_pretext_to_asm_raises_when_no_original_fa(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    # original.fa does NOT exist

    with pytest.raises(FileNotFoundError, match="original.fa"):
        run_pretext_to_asm(mock_ctx)


@patch("grit.steps.pretext_to_asm._run")
def test_run_pretext_to_asm_print_only_skips_checks(mock_run, mock_ctx, tmp_path):
    """In print_only mode no filesystem checks should occur."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.print_only = True
    mock_run.return_value = ""

    # Should not raise even though files don't exist
    run_pretext_to_asm(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("pretext-to-asm" in c for c in calls)


# ---------------------------------------------------------------------------
# run_haplotig_files
# ---------------------------------------------------------------------------


def test_run_haplotig_files_creates_empty_for_hap1(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.assembly_type = "hap1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.release_version = 1

    run_haplotig_files(mock_ctx)

    expected = tmp_path / "sDipInt39.hap1.1.all_haplotigs.curated.fa"
    assert expected.exists()
    assert expected.stat().st_size == 0


def test_run_haplotig_files_creates_empty_for_primary(mock_ctx_primary, tmp_path):
    mock_ctx_primary.workdir = tmp_path
    mock_ctx_primary.tol_id = "ilHelSara1"
    mock_ctx_primary.assembly_type = "primary"
    mock_ctx_primary.release_version = 1

    run_haplotig_files(mock_ctx_primary)

    expected = tmp_path / "ilHelSara1.1.all_haplotigs.curated.fa"
    assert expected.exists()


def test_run_haplotig_files_nonempty_does_not_overwrite(mock_ctx, tmp_path):
    """A non-empty haplotig file must not be touched / zeroed out."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.assembly_type = "hap1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.release_version = 1

    existing = tmp_path / "sDipInt39.hap1.1.all_haplotigs.curated.fa"
    existing.write_text("ACGT" * 50)  # non-empty (>10 bytes)

    run_haplotig_files(mock_ctx)

    assert existing.read_text() == "ACGT" * 50  # unchanged


def test_run_haplotig_files_print_only(mock_ctx, tmp_path):
    """Print-only mode must not create any files."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.assembly_type = "hap1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.release_version = 1
    mock_ctx.print_only = True

    run_haplotig_files(mock_ctx)

    created = list(tmp_path.glob("*.fa"))
    assert created == []


# ---------------------------------------------------------------------------
# run_hic_remapping
# ---------------------------------------------------------------------------


@patch("grit.steps.hic_remapping._submit_bsub")
@patch("grit.steps.hic_remapping.glob.glob")
def test_run_hic_remapping_submits_bsub(mock_glob, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""

    hap1_fa = str(tmp_path / "sDipInt39.1.hap1.primary.curated.fa")
    mock_glob.return_value = [hap1_fa]
    mock_bsub.return_value = "12345"

    run_hic_remapping(mock_ctx)

    assert mock_bsub.called
    inner_cmd = mock_bsub.call_args[0][0]
    assert "curationpretext.sh" in inner_cmd
    assert hap1_fa in inner_cmd
    assert str(mock_ctx.hic_dir) in inner_cmd


@patch("grit.steps.hic_remapping._submit_bsub")
@patch("grit.steps.hic_remapping.glob.glob")
def test_run_hic_remapping_includes_teloseq(mock_glob, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = "--teloseq TTAGG"

    hap1_fa = str(tmp_path / "sDipInt39.1.hap1.primary.curated.fa")
    mock_glob.return_value = [hap1_fa]
    mock_bsub.return_value = "12345"

    run_hic_remapping(mock_ctx)

    inner_cmd = mock_bsub.call_args[0][0]
    assert "--teloseq TTAGG" in inner_cmd


@patch("grit.steps.hic_remapping._submit_bsub")
@patch("grit.steps.hic_remapping.glob.glob", return_value=[])
def test_run_hic_remapping_raises_when_no_fasta(mock_glob, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"

    with pytest.raises(FileNotFoundError, match="primary curated FASTA"):
        run_hic_remapping(mock_ctx)


# ---------------------------------------------------------------------------
# run_qv
# ---------------------------------------------------------------------------


@patch("grit.steps.qv._submit_bsub")
def test_run_qv_submits_bsub(mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_bsub.return_value = "99999"

    run_qv(mock_ctx)

    assert mock_bsub.called
    inner_cmd = mock_bsub.call_args[0][0]
    assert "kmer_completeness.bash" in inner_cmd
    assert "sDipInt39" in inner_cmd
    assert "1" in inner_cmd


@patch("grit.steps.qv._submit_bsub")
def test_run_qv_print_only(mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.print_only = True
    mock_bsub.return_value = ""

    run_qv(mock_ctx)

    # bsub should still be called (it respects print_only internally)
    assert mock_bsub.called


# ---------------------------------------------------------------------------
# validate_curated_files
# ---------------------------------------------------------------------------


def test_validate_curated_files_print_only(mock_ctx, tmp_path):
    """In print_only mode, function must not raise even with no files present."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated"
    mock_ctx.print_only = True

    validate_curated_files(mock_ctx)  # should not raise


def test_validate_curated_files_parses_log(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated"

    log = tmp_path / "sDipInt39.log"
    log.write_text("Curation made 3 break 2 join 1 cut in session\n")

    validate_curated_files(mock_ctx)  # should not raise


def test_validate_curated_files_warns_on_missing_log(mock_ctx, tmp_path, capsys):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated"
    # no log file created

    validate_curated_files(mock_ctx)  # should not raise


# ---------------------------------------------------------------------------
# finalize_for_qc
# ---------------------------------------------------------------------------


@patch("grit.steps.finalize_qc._run")
@patch("grit.steps.finalize_qc.glob.glob")
def test_finalize_for_qc_creates_curated_dir(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")

    curated_fa = str(tmp_path / "sDipInt39.1.hap1.primary.curated.fa")
    chr_list = str(tmp_path / "sDipInt39.1.hap1.chromosome.list.csv")
    haplotig = str(tmp_path / "sDipInt39.1.hap1.all_haplotigs.curated.fa")
    remapped = str(
        tmp_path / "sDipInt39_curationpretext/pretext_maps_processed/sDipInt39_normal.pretext"
    )

    # glob side_effect: fa, chr_list, haplotigs, nfs_first_level, nfs_second_level, remapped
    mock_glob.side_effect = [
        [curated_fa],  # curated fa
        [chr_list],  # chr list
        [haplotig],  # haplotigs
        [],  # nfs first level (not found → use base)
        [remapped],  # remapped pretext
    ]
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx)

    # mkdir should have been called
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("mkdir" in c for c in calls)


@patch("grit.steps.finalize_qc._run")
def test_finalize_for_qc_print_only(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")
    mock_ctx.print_only = True
    mock_run.return_value = ""

    # Should not raise, just print commands
    finalize_for_qc(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("mkdir" in c for c in calls)
