"""Tests for run_sex_matcher's handling of stale 'started' history entries."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from grit.steps.pre_curation.sex_matcher import run_sex_matcher


def _base_ctx(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.workdir.mkdir()
    mock_ctx.tol_id = "ilHelSara1"
    mock_ctx.print_only = False
    return mock_ctx


@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_started_entry_with_existing_output_resolves_to_success(mock_bsub, mock_ctx, tmp_path):
    ctx = _base_ctx(mock_ctx, tmp_path)
    (ctx.workdir / "Best_match.txt").write_text("done")

    tracker = MagicMock()
    tracker.history.return_value = [
        {"status": "started", "run_dir": str(ctx.workdir / "sex_matcher" / "run1"), "job_id": "1"}
    ]
    ctx.tracker = tracker

    run_sex_matcher(ctx)

    tracker.finish.assert_called_once_with(
        "sex_matcher", ctx.workdir / "sex_matcher" / "run1", "success"
    )
    mock_bsub.assert_not_called()


@patch("grit.steps.pre_curation.sex_matcher._check_bjobs")
@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_started_entry_with_live_job_skips_resubmit(
    mock_bsub, mock_check_bjobs, mock_ctx, tmp_path
):
    ctx = _base_ctx(mock_ctx, tmp_path)

    tracker = MagicMock()
    tracker.history.return_value = [
        {"status": "started", "run_dir": str(ctx.workdir / "sex_matcher" / "run1"), "job_id": "42"}
    ]
    ctx.tracker = tracker
    mock_check_bjobs.return_value = {"42": "RUN"}

    run_sex_matcher(ctx)

    tracker.finish.assert_not_called()
    mock_bsub.assert_not_called()


@patch("grit.steps.pre_curation.sex_matcher._check_bjobs")
@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_started_entry_with_dead_job_and_no_output_resubmits(
    mock_bsub, mock_check_bjobs, mock_ctx, tmp_path
):
    ctx = _base_ctx(mock_ctx, tmp_path)

    (ctx.workdir / "original.fa").write_text("fa")
    run2 = ctx.workdir / "sex_matcher" / "run2"
    run2.mkdir(parents=True)

    tracker = MagicMock()
    tracker.history.return_value = [
        {"status": "started", "run_dir": str(ctx.workdir / "sex_matcher" / "run1"), "job_id": "42"}
    ]
    ctx.tracker = tracker
    ctx.tracker.start.return_value = run2
    mock_check_bjobs.return_value = {"42": "gone"}
    mock_bsub.return_value = "99"

    run_sex_matcher(ctx)

    tracker.finish.assert_called_once_with(
        "sex_matcher", ctx.workdir / "sex_matcher" / "run1", "failed"
    )
    mock_bsub.assert_called_once()


@patch("grit.steps.pre_curation.sex_matcher._check_bjobs")
@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_dry_run_short_circuits_before_idempotency_and_tolid_checks(
    mock_bsub, mock_check_bjobs, mock_ctx, tmp_path
):
    """dry_run must sit before the tol_id-prefix validation and before any
    tracker-history/bjobs idempotency check — a bogus tol_id and a stale
    'started' history entry must not stop the dry-run branch."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    ctx = mock_ctx
    ctx.workdir = tmp_path
    ctx.tol_id = "notAnInsectPrefix1"  # would fail the real tol_id check
    ctx.print_only = False
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, ctx.workdir)
    ctx.tracker = RunTracker(tmp_path, registry=registry)
    ctx.dry_run = True

    run_sex_matcher(ctx)

    mock_bsub.assert_not_called()
    mock_check_bjobs.assert_not_called()

    history = ctx.tracker.history("sex_matcher")
    assert history[-1]["status"] == "success"
    placeholder = Path(history[-1]["run_dir"]) / "Best_match_1"
    assert placeholder.exists()
