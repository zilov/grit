"""Tests for run_fastga step."""

from unittest.mock import patch

from grit.steps.optional.fastga import _is_super, _read_top1_table, run_fastga, run_fastga_stats


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
    assert "top1_targets" in keys


def test_is_super():
    assert _is_super("SUPER_1")
    assert _is_super("SUPER_W_HAP1")
    assert not _is_super("scaffold_unloc_1")
    assert not _is_super("chr1")


def test_read_top1_table(tmp_path):
    top1_file = tmp_path / "x.top1_targets.tsv"
    top1_file.write_text(
        "super\ttop_longest_ref_chr\tlen\nSUPER_1\tchr1\t500\nSUPER_2\tchr3\t800\n"
    )

    rows = _read_top1_table(top1_file)

    assert rows == [("SUPER_1", "chr1", "500"), ("SUPER_2", "chr3", "800")]


@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_prints_table(mock_find_latest_dir, mock_ctx, tmp_path, capsys):
    run_dir = tmp_path / "fastga_run"
    run_dir.mkdir()
    top1_file = run_dir / "GCA_x_vs_y.top1_targets.tsv"
    top1_file.write_text("super\ttop_longest_ref_chr\tlen\nSUPER_1\tchr1\t500\n")
    mock_find_latest_dir.return_value = run_dir

    run_fastga_stats(mock_ctx)

    out = capsys.readouterr().out
    assert "SUPER_1" in out
    assert "chr1" in out
    assert "500" in out


@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_filters_to_super_scaffolds(
    mock_find_latest_dir, mock_ctx, tmp_path, capsys
):
    run_dir = tmp_path / "fastga_run"
    run_dir.mkdir()
    top1_file = run_dir / "GCA_x_vs_y.top1_targets.tsv"
    top1_file.write_text(
        "super\ttop_longest_ref_chr\tlen\nSUPER_1\tchr1\t500\nscaffold_unloc_1\tchr2\t200\n"
    )
    mock_find_latest_dir.return_value = run_dir

    run_fastga_stats(mock_ctx)

    out = capsys.readouterr().out
    assert "SUPER_1" in out
    assert "scaffold_unloc_1" not in out


@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_raises_when_no_top1_table(mock_find_latest_dir, mock_ctx, tmp_path):
    run_dir = tmp_path / "fastga_run"
    run_dir.mkdir()
    mock_find_latest_dir.return_value = run_dir

    try:
        run_fastga_stats(mock_ctx)
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass
