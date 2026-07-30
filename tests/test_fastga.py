"""Tests for run_fastga step."""

from unittest.mock import patch

from grit.steps.optional.fastga import run_fastga


@patch("grit.steps.optional.fastga._submit_bsub")
@patch("grit.steps.optional.fastga.find_reheadered_reference")
@patch("grit.steps.optional.fastga.find_canonical_fa")
def test_run_fastga_inner_cmd_runs_top_targets_summary(
    mock_find_fa, mock_find_ref, mock_bsub, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.print_only = False

    mock_find_fa.return_value = tmp_path / "sDipInt39.1.hap1.curated.fa"
    mock_find_ref.return_value = tmp_path / "reference" / "GCA_000001_reheader.fna"
    mock_bsub.return_value = "12345"

    run_fastga(mock_ctx)

    mock_bsub.assert_called_once()
    inner_cmd = mock_bsub.call_args[0][0]

    assert "FastGA_dot_dgenies.sh" in inner_cmd
    assert "paf_top_targets_add_top_longest.py" in inner_cmd
    assert "--top_longest" in inner_cmd
    assert ".top_targets_summary.txt" in inner_cmd
    # summary generation must come after the FastGA run that produces the PAF
    assert inner_cmd.index("FastGA_dot_dgenies.sh") < inner_cmd.index(
        "paf_top_targets_add_top_longest.py"
    )


def test_fastga_output_specs_include_top_targets_summary():
    from grit.steps.optional.fastga import _OUTPUT_SPECS

    keys = [key for key, _pattern, _excludes in _OUTPUT_SPECS]
    assert "top_targets_summary" in keys
