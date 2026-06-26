"""Tests for rename_and_orient step."""

from pathlib import Path
from unittest.mock import patch

import pytest

from grit.steps.optional.rename_and_orient import run_rename_and_orient


@patch("grit.steps.optional.rename_and_orient.subprocess.run")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_curated_fa")
def test_run_rename_and_orient_finds_files_and_runs_command(
    mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    curated_fa = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"

    mock_find_fa.return_value = curated_fa
    mock_glob.return_value = [str(paf_file)]  # PAF glob

    run_rename_and_orient(mock_ctx)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "rename-and-orient" in cmd
    assert str(curated_fa) in cmd
    assert str(paf_file) in cmd
    assert "rename_and_orient" in cmd   # output dir
    assert "sDipInt39.hap1.primary.renamed" in cmd  # prefix


@patch("grit.steps.optional.rename_and_orient.subprocess.run")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
def test_run_rename_and_orient_print_only_mode(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = True

    mock_glob.return_value = []

    run_rename_and_orient(mock_ctx)

    mock_run.assert_not_called()


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
    mock_glob.return_value = []  # no PAF

    with pytest.raises(FileNotFoundError, match="No FastGA PAF found"):
        run_rename_and_orient(mock_ctx)
