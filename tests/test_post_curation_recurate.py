"""Tests for the post-curation-recurate composite step."""

from unittest.mock import patch

from click.testing import CliRunner

from grit.core.click_cli import cli
from grit.steps.post_curation.post_curation_recurate import run_post_curation_recurate


@patch("grit.steps.post_curation.post_curation_recurate.run_hic_remapping")
@patch("grit.steps.post_curation.post_curation_recurate.run_pretext_to_asm_recurate")
def test_default_runs_hap1_chain(mock_recurate, mock_hic, mock_ctx):
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    run_post_curation_recurate(mock_ctx)

    mock_recurate.assert_called_once_with(mock_ctx, "hap1", "pretext_to_asm_recurate")
    mock_hic.assert_called_once_with(mock_ctx, run_hap1=True, run_hap2=False)


@patch("grit.steps.post_curation.post_curation_recurate.run_hic_remapping")
@patch("grit.steps.post_curation.post_curation_recurate.run_pretext_to_asm_recurate")
def test_hap2_flag_runs_hap2_chain_exclusively(mock_recurate, mock_hic, mock_ctx):
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    run_post_curation_recurate(mock_ctx, run_hap2=True)

    mock_recurate.assert_called_once_with(mock_ctx, "hap2", "pretext_to_asm_recurate_hap2")
    mock_hic.assert_called_once_with(mock_ctx, run_hap1=False, run_hap2=True)


def test_cli_help():
    result = CliRunner().invoke(cli, ["post-curation-recurate", "--help"])
    assert result.exit_code == 0
    assert "--hap2" in result.output
