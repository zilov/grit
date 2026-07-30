"""Tests for grit/core/status.py."""

from unittest.mock import patch

from grit.core.status import _print_less_tips, _print_scp_tips


@patch("grit.core.status.print_tip")
def test_print_scp_tips_prints_for_successful_step_with_outputs(mock_print_tip):
    step_latest = {
        "busco_synteny": {
            "status": "success",
            "outputs": {"png": "/lustre/foo/Rf_vs_Qu.png"},
        },
    }

    _print_scp_tips(step_latest, "farm22", "sDipInt39")

    mock_print_tip.assert_called_once()
    tip = mock_print_tip.call_args[0][0]
    assert "scp farm22:/lustre/foo/Rf_vs_Qu.png" in tip


@patch("grit.core.status.print_tip")
def test_print_scp_tips_skips_step_without_outputs(mock_print_tip):
    step_latest = {"fastga": {"status": "success", "outputs": {}}}

    _print_scp_tips(step_latest, "farm22", "sDipInt39")

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_scp_tips_skips_failed_step(mock_print_tip):
    step_latest = {
        "fastga_synteny": {
            "status": "failed",
            "outputs": {"png": "/lustre/foo/plot.png"},
        },
    }

    _print_scp_tips(step_latest, "farm22", "sDipInt39")

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_scp_tips_skips_step_not_in_history(mock_print_tip):
    _print_scp_tips({}, "farm22", "sDipInt39")

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_less_tips_prints_for_successful_fastga(mock_print_tip):
    step_latest = {
        "fastga": {
            "status": "success",
            "outputs": {
                "paf": "/lustre/foo/Rf_vs_Qu.FastGA.paf",
                "top_targets_summary": "/lustre/foo/Rf_vs_Qu.top_targets_summary.txt",
            },
        },
    }

    _print_less_tips(step_latest)

    mock_print_tip.assert_called_once()
    tip = mock_print_tip.call_args[0][0]
    assert "less /lustre/foo/Rf_vs_Qu.top_targets_summary.txt" in tip


@patch("grit.core.status.print_tip")
def test_print_less_tips_skips_step_missing_summary_output(mock_print_tip):
    step_latest = {"fastga": {"status": "success", "outputs": {"paf": "/lustre/foo/x.paf"}}}

    _print_less_tips(step_latest)

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_less_tips_skips_failed_step(mock_print_tip):
    step_latest = {
        "fastga": {
            "status": "failed",
            "outputs": {"top_targets_summary": "/lustre/foo/x.top_targets_summary.txt"},
        },
    }

    _print_less_tips(step_latest)

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_less_tips_skips_step_not_in_history(mock_print_tip):
    _print_less_tips({})

    mock_print_tip.assert_not_called()
