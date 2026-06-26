"""Tests for rename_and_orient step."""

from pathlib import Path
from unittest.mock import patch

import pytest

from grit.steps.optional.rename_and_orient import run_rename_and_orient


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_curated_fa")
def test_run_rename_and_orient_submits_bsub(mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    curated_fa = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"

    mock_find_fa.return_value = curated_fa
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx)

    mock_bsub.assert_called_once()
    cmd = mock_bsub.call_args[0][0]
    assert "rename-and-orient" in cmd
    assert str(curated_fa) in cmd
    assert str(paf_file) in cmd
    assert "sDipInt39.hap1.primary.renamed" in cmd


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
def test_run_rename_and_orient_print_only_mode(mock_glob, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = True

    mock_glob.return_value = []

    run_rename_and_orient(mock_ctx)

    # print_only=True — bsub called but with print_only flag (prints, doesn't submit)
    mock_bsub.assert_called_once()
    assert mock_bsub.call_args[0][2] is True  # print_only argument


@patch("grit.steps.optional.rename_and_orient.find_curated_fa")
def test_run_rename_and_orient_raises_when_no_curated_fasta(mock_find_fa, mock_ctx):
    mock_ctx.workdir = Path("/fake/workdir")
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_find_fa.side_effect = FileNotFoundError("No curated FASTA for 'hap1' found")

    with pytest.raises(FileNotFoundError):
        run_rename_and_orient(mock_ctx)


@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_curated_fa")
def test_run_rename_and_orient_raises_when_no_paf(mock_find_fa, mock_glob, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    mock_glob.return_value = []

    with pytest.raises(FileNotFoundError, match="No FastGA PAF found"):
        run_rename_and_orient(mock_ctx)


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_curated_fa")
def test_run_rename_and_orient_hap2_waits_for_mapping_tsv(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """hap2 should not submit if hap1 mapping.tsv doesn't exist yet."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    # mapping.tsv does NOT exist — hap2 should be skipped
    run_rename_and_orient(mock_ctx, run_hap2=True)

    assert mock_bsub.call_count == 1  # only hap1 submitted


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_curated_fa")
def test_run_rename_and_orient_hap2_submits_when_mapping_tsv_exists(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """hap2 should submit when hap1 mapping.tsv is present."""
    outdir = tmp_path / "workdir" / "rename_and_orient"
    outdir.mkdir(parents=True)
    mapping_tsv = outdir / "sDipInt39.hap1.primary.renamed.mapping.tsv"
    mapping_tsv.touch()

    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx, run_hap2=True)

    assert mock_bsub.call_count == 2
    cmds = [call[0][0] for call in mock_bsub.call_args_list]
    assert any("--paf" in cmd for cmd in cmds)
    assert any("--mapping-table" in cmd for cmd in cmds)
