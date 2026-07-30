"""Tests for find_reference step."""

from unittest.mock import MagicMock, patch

import pytest

from grit.steps.pre_curation.find_reference import find_closest_reference


@patch("grit.steps.pre_curation.find_reference._run")
def test_local_plain_fasta_reheadered_straight_into_run_dir(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    local_ref = tmp_path / "somewhere_else" / "my_reference.fa"
    local_ref.parent.mkdir(parents=True)
    local_ref.write_text(">chr1\nACGT\n")

    find_closest_reference(mock_ctx, local_path=str(local_ref))

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ln -s" not in cmd
    assert "cp " not in cmd
    assert "gunzip" not in cmd
    assert f"reheader {local_ref}" in cmd
    run_dir = mock_ctx.workdir / "find_reference" / "untracked"
    assert str(run_dir / "my_reference_reheader.fna") in cmd
    # original file untouched
    assert local_ref.exists()


@patch("grit.steps.pre_curation.find_reference._run")
def test_local_gzipped_fasta_decompressed_into_run_dir(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    local_ref = tmp_path / "somewhere_else" / "my_reference.fa.gz"
    local_ref.parent.mkdir(parents=True)
    local_ref.write_bytes(b"fake-gz-content")

    find_closest_reference(mock_ctx, local_path=str(local_ref))

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ln -s" not in cmd
    assert "cp " not in cmd

    run_dir = mock_ctx.workdir / "find_reference" / "untracked"
    decompressed = run_dir / "my_reference.fa"
    ref_reheader = run_dir / "my_reference_reheader.fna"
    assert f"gunzip -c {local_ref} > {decompressed}" in cmd
    assert f"reheader {decompressed} > {ref_reheader}" in cmd
    assert f"rm {decompressed}" in cmd
    # original file untouched
    assert local_ref.exists()


@patch("grit.steps.pre_curation.find_reference._run")
def test_local_missing_file_raises(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    with pytest.raises(FileNotFoundError):
        find_closest_reference(mock_ctx, local_path=str(tmp_path / "does_not_exist.fa"))

    mock_run.assert_not_called()


@patch("grit.steps.pre_curation.find_reference._run")
def test_local_ignores_number_with_warning(mock_run, mock_ctx, tmp_path, caplog):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    local_ref = tmp_path / "ref.fa"
    local_ref.write_text(">chr1\nACGT\n")

    with caplog.at_level("WARNING"):
        find_closest_reference(mock_ctx, number=3, local_path=str(local_ref))

    assert "--number" in caplog.text
    mock_run.assert_called_once()  # only the local prep call, no download loop


@patch("grit.steps.pre_curation.find_reference._reheader_downloaded_references")
@patch("grit.steps.pre_curation.find_reference._run")
def test_download_path_unaffected_when_no_local_path(
    mock_run, mock_reheader_downloaded, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    find_closest_reference(mock_ctx)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "get_nearest_comparator.rb" in cmd
    mock_reheader_downloaded.assert_called_once()


@patch("grit.steps.pre_curation.find_reference._run")
def test_local_already_inside_run_dir_still_works(mock_run, mock_ctx, tmp_path):
    """
    A local reference that already happens to live inside the step's own
    run_dir must still be prepped correctly (no self-referential symlink
    trap now that prep never symlinks/copies the source at all).
    """
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    run_dir = mock_ctx.workdir / "find_reference" / "untracked"
    run_dir.mkdir(parents=True)
    local_ref = run_dir / "already_here.fa"
    local_ref.write_text(">chr1\nACGT\n")

    find_closest_reference(mock_ctx, local_path=str(local_ref))

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ln -s" not in cmd
    assert f"reheader {local_ref}" in cmd
    assert str(run_dir / "already_here_reheader.fna") in cmd
    assert local_ref.exists()  # original untouched


@patch("grit.steps.pre_curation.find_reference._run")
def test_local_missing_file_with_tracker_marks_failed(mock_run, mock_ctx, tmp_path):
    """Regression test: tracker should mark run as 'failed' when --local file doesn't exist."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    # Set up a mock tracker
    mock_tracker = MagicMock()
    mock_run_dir = tmp_path / "find_reference" / "run"
    mock_tracker.start.return_value = mock_run_dir
    mock_ctx.tracker = mock_tracker

    with pytest.raises(FileNotFoundError):
        find_closest_reference(mock_ctx, local_path=str(tmp_path / "does_not_exist.fa"))

    # Verify tracker.start was called
    mock_tracker.start.assert_called_once()

    # Verify tracker.finish was called with "failed" status
    mock_tracker.finish.assert_called_once_with("find_reference", mock_run_dir, "failed")

    # Verify _run was not called (file check failed before attempting any prep)
    mock_run.assert_not_called()
