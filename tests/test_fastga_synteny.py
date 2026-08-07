"""Tests for fastga_synteny step."""

from unittest.mock import patch

import pytest

from grit.steps.optional.fastga_synteny import DEFAULT_MIN_ALIGN_LEN, run_fastga_synteny


@patch("grit.steps.optional.fastga_synteny._submit_bsub")
@patch("grit.steps.optional.fastga_synteny.glob.glob")
@patch("grit.steps.optional.fastga_synteny.find_latest_dir")
def test_run_fastga_synteny_submits_bsub(mock_find_dir, mock_glob, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.print_only = False

    fastga_dir = tmp_path / "workdir" / "fastga" / "2026-01-01T00_00_00"
    paf_file = fastga_dir / "sDipInt39_vs_ref.FastGA.paf"
    mock_find_dir.return_value = fastga_dir
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_fastga_synteny(mock_ctx)

    mock_bsub.assert_called_once()
    cmd = mock_bsub.call_args[0][0]
    assert "fastga_synteny_format_and_plot.py" in cmd
    assert str(paf_file) in cmd
    assert f"-min-len {DEFAULT_MIN_ALIGN_LEN}" in cmd
    assert "uv run --script" in cmd


@patch("grit.steps.optional.fastga_synteny._submit_bsub")
@patch("grit.steps.optional.fastga_synteny.glob.glob")
@patch("grit.steps.optional.fastga_synteny.find_latest_dir")
def test_run_fastga_synteny_custom_min_align_len(
    mock_find_dir, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.print_only = False

    fastga_dir = tmp_path / "workdir" / "fastga" / "2026-01-01T00_00_00"
    paf_file = fastga_dir / "sDipInt39_vs_ref.FastGA.paf"
    mock_find_dir.return_value = fastga_dir
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_fastga_synteny(mock_ctx, min_align_len=25_000)

    cmd = mock_bsub.call_args[0][0]
    assert "-min-len 25000" in cmd


@patch("grit.steps.optional.fastga_synteny._submit_bsub")
@patch("grit.steps.optional.fastga_synteny.glob.glob")
@patch("grit.steps.optional.fastga_synteny.find_latest_dir")
def test_run_fastga_synteny_print_only_mode(
    mock_find_dir, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.print_only = True

    fastga_dir = tmp_path / "workdir" / "fastga" / "2026-01-01T00_00_00"
    paf_file = fastga_dir / "sDipInt39_vs_ref.FastGA.paf"
    mock_find_dir.return_value = fastga_dir
    mock_glob.return_value = [str(paf_file)]

    run_fastga_synteny(mock_ctx)

    mock_bsub.assert_called_once()
    assert mock_bsub.call_args[0][2] is True  # print_only argument


@patch("grit.steps.optional.fastga_synteny.glob.glob")
@patch("grit.steps.optional.fastga_synteny.find_latest_dir")
def test_run_fastga_synteny_raises_when_no_paf(mock_find_dir, mock_glob, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.print_only = False

    mock_find_dir.return_value = tmp_path / "workdir" / "fastga" / "2026-01-01T00_00_00"
    mock_glob.return_value = []

    with pytest.raises(FileNotFoundError, match="No FastGA PAF found"):
        run_fastga_synteny(mock_ctx)
