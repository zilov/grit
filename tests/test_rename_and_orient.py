"""Tests for rename_and_orient step."""

from pathlib import Path
from unittest.mock import patch

import pytest

from grit.steps.optional.rename_and_orient import run_rename_and_orient

# ---------------------------------------------------------------------------
# run_rename_and_orient
# ---------------------------------------------------------------------------


@patch("grit.steps.optional.rename_and_orient.subprocess.run")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
def test_run_rename_and_orient_finds_files_and_runs_command(
    mock_glob, mock_run, mock_ctx, tmp_path
):
    """Test that run_rename_and_orient finds curated FASTA and PAF, then runs the rename script."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.print_only = False

    # Create mock files
    curated_fa = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"

    mock_glob.side_effect = [
        [str(curated_fa)],  # curated FASTA
        [str(paf_file)],  # PAF file
    ]

    run_rename_and_orient(mock_ctx)

    # Check that subprocess.run was called with the correct command
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "python3" in cmd
    assert "rename_and_orient.py" in cmd
    assert str(curated_fa) in cmd
    assert str(paf_file) in cmd
    assert "rename_and_orient" in cmd  # output dir
    assert "sDipInt39.hap1.primary.renamed" in cmd  # prefix


@patch("grit.steps.optional.rename_and_orient.subprocess.run")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
def test_run_rename_and_orient_print_only_mode(mock_glob, mock_run, mock_ctx, tmp_path):
    """Test that in print_only mode, command is printed but not executed."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.print_only = True

    mock_glob.side_effect = [
        [],  # no real files, but print_only uses example paths
        [],
    ]

    run_rename_and_orient(mock_ctx)

    # In print_only mode, subprocess.run should not be called
    mock_run.assert_not_called()


@patch("grit.steps.optional.rename_and_orient.glob.glob", return_value=[])
def test_run_rename_and_orient_raises_when_no_curated_fasta(mock_glob, mock_ctx):
    """Test that FileNotFoundError is raised when no curated FASTA is found."""
    mock_ctx.workdir = Path("/fake/workdir")
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"

    with pytest.raises(FileNotFoundError, match="No curated hap1 FASTA found"):
        run_rename_and_orient(mock_ctx)


@patch("grit.steps.optional.rename_and_orient.glob.glob")
def test_run_rename_and_orient_raises_when_no_paf(mock_glob, mock_ctx, tmp_path):
    """Test that FileNotFoundError is raised when no FastGA PAF is found."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"

    curated_fa = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    mock_glob.side_effect = [
        [str(curated_fa)],  # curated FASTA found
        [],  # no PAF
    ]

    with pytest.raises(FileNotFoundError, match="No FastGA PAF found"):
        run_rename_and_orient(mock_ctx)
