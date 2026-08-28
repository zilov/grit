"""Tests for run_fastga step."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.optional.fastga import _is_super, _read_top1_table, run_fastga, run_fastga_stats

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _attach_tracker(ctx, tmp_path):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)


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
    assert "paf_top_targets_by_coverage.py" in inner_cmd


def test_fastga_output_specs_include_top_targets_summary():
    from grit.steps.optional.fastga import _OUTPUT_SPECS

    keys = [spec[0] for spec in _OUTPUT_SPECS]
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
        "curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\n"
        "SUPER_1\tchr1\t500\t50.00\n"
        "SUPER_2\tchr3\t800\t80.00\n"
    )

    rows = _read_top1_table(top1_file)

    assert rows == [
        ("SUPER_1", "chr1", "500", "50.00"),
        ("SUPER_2", "chr3", "800", "80.00"),
    ]


@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_prints_table(mock_find_latest_dir, mock_ctx, tmp_path, capsys):
    run_dir = tmp_path / "fastga_run"
    run_dir.mkdir()
    top1_file = run_dir / "GCA_x_vs_y.top1_targets.tsv"
    top1_file.write_text(
        "curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\nSUPER_1\tchr1\t500\t50.00\n"
    )
    mock_find_latest_dir.return_value = run_dir

    run_fastga_stats(mock_ctx)

    out = capsys.readouterr().out
    assert "SUPER_1" in out
    assert "chr1" in out
    assert "500" in out
    assert "50.00" in out


@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_filters_to_super_scaffolds(
    mock_find_latest_dir, mock_ctx, tmp_path, capsys
):
    run_dir = tmp_path / "fastga_run"
    run_dir.mkdir()
    top1_file = run_dir / "GCA_x_vs_y.top1_targets.tsv"
    top1_file.write_text(
        "curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\n"
        "SUPER_1\tchr1\t500\t50.00\n"
        "scaffold_unloc_1\tchr2\t200\t20.00\n"
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


@patch("grit.steps.optional.fastga._submit_bsub")
@patch("grit.steps.optional.fastga.find_reheadered_reference")
@patch("grit.steps.optional.fastga.find_canonical_fa")
def test_run_fastga_dry_run_short_circuits(
    mock_find_fa, mock_find_ref, mock_bsub, mock_ctx, tmp_path
):
    """dry_run must skip reference/FASTA lookup + bsub submission entirely."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_fastga(mock_ctx)

    mock_bsub.assert_not_called()
    mock_find_fa.assert_not_called()
    mock_find_ref.assert_not_called()

    paf_path = mock_ctx.tracker.get_output("fastga", "paf")
    assert paf_path is not None
    assert Path(paf_path).exists()


def test_run_fastga_dry_run_top1_targets_content_is_parseable(mock_ctx, tmp_path):
    """The dry-run fake top1_targets.tsv content must be parseable by the real
    _read_top1_table function used downstream by fastga-stats."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_fastga(mock_ctx)

    top1_path = Path(mock_ctx.tracker.get_output("fastga", "top1_targets"))
    rows = _read_top1_table(top1_path)

    assert rows == [("SUPER_1", "chr1", "1000000", "100.00")]
    assert all(_is_super(row[0]) for row in rows)


def test_cli_fastga_stats_dry_run_chains_after_fastga_dry_run(tmp_path, monkeypatch):
    """`grit --dry-run fastga-stats` must no longer raise UsageError, and — chained
    after a real `grit --dry-run fastga` run against the same isolated workdir —
    must print the fake SUPER_1 row that fastga's dry-run branch wrote."""
    from grit.core.click_cli import cli

    monkeypatch.setattr("grit.core.registry.dry_run_root", lambda: tmp_path)

    config_path = str(_FIXTURES_DIR / "test_config.yaml")
    yaml_path = str(_FIXTURES_DIR / "uoEpiScra1_hap1_hap2.yaml")
    common_args = ["--config", config_path, "--yaml", yaml_path, "--dry-run"]

    runner = CliRunner()

    result_fastga = runner.invoke(cli, [*common_args, "fastga"])
    assert result_fastga.exit_code == 0, result_fastga.output

    result_stats = runner.invoke(cli, [*common_args, "fastga-stats"])
    assert result_stats.exit_code == 0, result_stats.output
    assert "SUPER_1" in result_stats.output
    assert "chr1" in result_stats.output
