"""Tests for run_fastga / run_fastga_stats steps."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.optional.fastga import (
    _is_super,
    _print_top1_table,
    _read_top1_table,
    run_fastga,
    run_fastga_stats,
)

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _attach_tracker(ctx, tmp_path):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)


# ---------------------------------------------------------------------------
# run_fastga
# ---------------------------------------------------------------------------


@patch("grit.steps.optional.fastga._submit_bsub")
@patch("grit.steps.optional.fastga.find_reheadered_reference")
@patch("grit.steps.optional.fastga.find_canonical_fa")
def test_run_fastga_inner_cmd_no_longer_runs_top_targets_script(
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
    assert "paf_top_targets_by_coverage.py" not in inner_cmd


def test_fastga_output_specs_no_longer_include_top_targets():
    from grit.steps.optional.fastga import _OUTPUT_SPECS

    keys = [spec[0] for spec in _OUTPUT_SPECS]
    assert "idx" in keys
    assert "paf" in keys
    assert "top_targets_summary" not in keys
    assert "top1_targets" not in keys


def test_fastga_stats_output_specs_include_top_targets():
    from grit.steps.optional.fastga import _OUTPUT_SPECS_STATS

    keys = [spec[0] for spec in _OUTPUT_SPECS_STATS]
    assert "top1_targets" in keys
    assert "top_targets_summary" in keys


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


# ---------------------------------------------------------------------------
# _print_top1_table
# ---------------------------------------------------------------------------


def test_print_top1_table_prints_table(tmp_path, capsys):
    top1_file = tmp_path / "GCA_x_vs_y.top1_targets.tsv"
    top1_file.write_text(
        "curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\nSUPER_1\tchr1\t500\t50.00\n"
    )

    _print_top1_table(top1_file)

    out = capsys.readouterr().out
    assert "SUPER_1" in out
    assert "chr1" in out
    assert "500" in out
    assert "50.00" in out


def test_print_top1_table_filters_to_super_scaffolds(tmp_path, capsys):
    top1_file = tmp_path / "GCA_x_vs_y.top1_targets.tsv"
    top1_file.write_text(
        "curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\n"
        "SUPER_1\tchr1\t500\t50.00\n"
        "scaffold_unloc_1\tchr2\t200\t20.00\n"
    )

    _print_top1_table(top1_file)

    out = capsys.readouterr().out
    assert "SUPER_1" in out
    assert "scaffold_unloc_1" not in out


def test_print_top1_table_warns_when_no_super_rows(tmp_path, caplog):
    top1_file = tmp_path / "GCA_x_vs_y.top1_targets.tsv"
    top1_file.write_text(
        "curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\n"
        "scaffold_unloc_1\tchr2\t200\t20.00\n"
    )

    _print_top1_table(top1_file)

    assert "No SUPER_* rows found" in caplog.text


# ---------------------------------------------------------------------------
# run_fastga_stats
# ---------------------------------------------------------------------------


@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_raises_when_no_paf_found(mock_find_latest_dir, mock_ctx, tmp_path):
    run_dir = tmp_path / "fastga_run"
    run_dir.mkdir()
    mock_find_latest_dir.return_value = run_dir

    try:
        run_fastga_stats(mock_ctx)
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError:
        pass


@patch("grit.steps.optional.fastga._run")
@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_runs_coverage_script_against_latest_paf(
    mock_find_latest_dir, mock_run, mock_ctx, tmp_path, capsys
):
    fastga_dir = tmp_path / "fastga_run"
    fastga_dir.mkdir()
    (fastga_dir / "GCA_x_vs_y_FastGA.paf").write_text("fake paf\n")
    mock_find_latest_dir.return_value = fastga_dir
    mock_ctx.tracker = None
    mock_ctx.workdir = tmp_path
    mock_ctx.print_only = False

    def _fake_run(cmd, print_only):
        top1_path = Path(cmd.split("--top1-out ")[1].split(" ")[0])
        top1_path.write_text(
            "curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\n"
            "SUPER_1\tchr1\t500\t50.00\n"
        )
        return ""

    mock_run.side_effect = _fake_run

    run_fastga_stats(mock_ctx)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "paf_top_targets_by_coverage.py" in cmd
    assert "GCA_x_vs_y_FastGA.paf" in cmd
    assert mock_run.call_args[0][1] is False

    out = capsys.readouterr().out
    assert "SUPER_1" in out


@patch("grit.steps.optional.fastga._run")
@patch("grit.steps.optional.fastga.find_latest_dir")
def test_run_fastga_stats_print_only_skips_execution_and_table(
    mock_find_latest_dir, mock_run, mock_ctx, tmp_path, capsys
):
    fastga_dir = tmp_path / "fastga_run"
    fastga_dir.mkdir()
    (fastga_dir / "GCA_x_vs_y_FastGA.paf").write_text("fake paf\n")
    mock_find_latest_dir.return_value = fastga_dir
    mock_ctx.tracker = None
    mock_ctx.workdir = tmp_path
    mock_ctx.print_only = True
    mock_run.return_value = ""

    run_fastga_stats(mock_ctx)

    mock_run.assert_called_once()
    assert mock_run.call_args[0][1] is True
    assert not (tmp_path / "fastga_stats").exists()
    assert capsys.readouterr().out.count("SUPER_1") == 0


def test_run_fastga_stats_dry_run_top1_targets_content_is_parseable(mock_ctx, tmp_path, capsys):
    """The dry-run fake top1_targets.tsv content must be parseable by the real
    _read_top1_table function, and the table must print, without touching
    the fastga step or running any subprocess."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_fastga_stats(mock_ctx)

    top1_path = Path(mock_ctx.tracker.get_output("fastga_stats", "top1_targets"))
    rows = _read_top1_table(top1_path)

    assert rows == [("SUPER_1", "chr1", "1000000", "100.00")]
    assert all(_is_super(row[0]) for row in rows)
    assert "SUPER_1" in capsys.readouterr().out


def test_cli_fastga_stats_dry_run_chains_after_fastga_dry_run(tmp_path, monkeypatch):
    """`grit --dry-run fastga-stats` must no longer raise UsageError, and — after
    a real `grit --dry-run fastga` run against the same isolated workdir —
    must print the fake SUPER_1 row from its own fastga_stats dry-run branch."""
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
