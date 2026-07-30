"""Tests for find_reference step."""

from unittest.mock import patch

import pytest

from grit.steps.pre_curation.find_reference import find_closest_reference


@patch("grit.steps.pre_curation.find_reference.reheader_reference")
@patch("grit.steps.pre_curation.find_reference._run")
def test_local_symlinks_and_reheaders(mock_run, mock_reheader, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    local_ref = tmp_path / "my_reference.fa"
    local_ref.write_text(">chr1\nACGT\n")

    find_closest_reference(mock_ctx, local_path=str(local_ref))

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ln -s" in cmd
    assert str(local_ref) in cmd
    assert "cp " not in cmd

    mock_reheader.assert_called_once()
    reheader_args, reheader_kwargs = mock_reheader.call_args
    assert reheader_kwargs.get("remove_raw") is True
    link_path = reheader_args[1]
    assert link_path.name == "my_reference.fa"


@patch("grit.steps.pre_curation.find_reference._run")
def test_local_missing_file_raises(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    with pytest.raises(FileNotFoundError):
        find_closest_reference(mock_ctx, local_path=str(tmp_path / "does_not_exist.fa"))

    mock_run.assert_not_called()


@patch("grit.steps.pre_curation.find_reference.reheader_reference")
@patch("grit.steps.pre_curation.find_reference._run")
def test_local_ignores_number_with_warning(mock_run, mock_reheader, mock_ctx, tmp_path, caplog):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    local_ref = tmp_path / "ref.fa"
    local_ref.write_text(">chr1\nACGT\n")

    with caplog.at_level("WARNING"):
        find_closest_reference(mock_ctx, number=3, local_path=str(local_ref))

    assert "--number" in caplog.text
    mock_run.assert_called_once()  # only the ln -s call, no download loop


@patch("grit.steps.pre_curation.find_reference._reheader_downloaded_references")
@patch("grit.steps.pre_curation.find_reference._run")
def test_download_path_unaffected_when_no_local_path(mock_run, mock_reheader_downloaded, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    find_closest_reference(mock_ctx)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "get_nearest_comparator.rb" in cmd
    mock_reheader_downloaded.assert_called_once()
