"""Tests for run_fastga step."""

from unittest.mock import patch

from grit.steps.optional.fastga import _parse_top_longest_table, run_fastga, run_fastga_stats


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

    assert "FastGA_dot_dgenies_stats.sh" in inner_cmd
    assert "paf_top_targets_add_top_longest.py" in inner_cmd


def test_fastga_output_specs_include_top_targets_summary():
    from grit.steps.optional.fastga import _OUTPUT_SPECS

    keys = [key for key, _pattern, _excludes in _OUTPUT_SPECS]
    assert "top_targets_summary" in keys


def test_parse_top_longest_table(tmp_path):
    summary_file = tmp_path / "x.top_targets_summary.txt"
    summary_file.write_text(
        "##TOP_LONGEST_TABLE##\n"
        "super\ttop_longest_ref_chr\tlen\n"
        "scaffold_1\tchr1\t500\n"
        "scaffold_2\tchr3\t800\n"
        "##END_TOP_LONGEST_TABLE##\n"
        "\nrest of the report...\n"
    )

    rows = _parse_top_longest_table(summary_file)

    assert rows == [("scaffold_1", "chr1", "500"), ("scaffold_2", "chr3", "800")]


def test_parse_top_longest_table_missing_markers(tmp_path):
    summary_file = tmp_path / "x.top_targets_summary.txt"
    summary_file.write_text("no markers here\n")

    assert _parse_top_longest_table(summary_file) == []


@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_prints_table(mock_find_latest_dir, mock_ctx, tmp_path, capsys):
    run_dir = tmp_path / "fastga_run"
    run_dir.mkdir()
    summary_file = run_dir / "GCA_x_vs_y.top_targets_summary.txt"
    summary_file.write_text(
        "##TOP_LONGEST_TABLE##\n"
        "super\ttop_longest_ref_chr\tlen\n"
        "scaffold_1\tchr1\t500\n"
        "##END_TOP_LONGEST_TABLE##\n"
    )
    mock_find_latest_dir.return_value = run_dir

    run_fastga_stats(mock_ctx)

    out = capsys.readouterr().out
    assert "scaffold_1" in out
    assert "chr1" in out
    assert "500" in out


@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_raises_when_no_summary(mock_find_latest_dir, mock_ctx, tmp_path):
    run_dir = tmp_path / "fastga_run"
    run_dir.mkdir()
    mock_find_latest_dir.return_value = run_dir

    try:
        run_fastga_stats(mock_ctx)
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass
