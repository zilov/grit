"""Tests for pre_curation steps."""

from pathlib import Path
from unittest.mock import patch

import pytest

from grit.steps.pre_curation import (
    _pick_highest_version,
    _sort_by_mtime,
    copy_pretext_maps,
    print_curation_summary,
    setup_curation,
)
from grit.steps.pre_curation.setup import (
    _peek_first_fasta_header,
    _resolve_hap2_fasta,
    _validate_scaffold_headers,
)

# ---------------------------------------------------------------------------
# _sort_by_mtime
# ---------------------------------------------------------------------------


def test_sort_by_mtime_returns_newest_first(tmp_path):
    f1 = tmp_path / "old.fa"
    f2 = tmp_path / "new.fa"
    f1.write_text("old")
    f2.write_text("new")
    import time

    time.sleep(0.01)
    f2.touch()  # make f2 newer

    result = _sort_by_mtime([str(f1), str(f2)])
    assert result[0] == str(f2)


# ---------------------------------------------------------------------------
# _pick_highest_version
# ---------------------------------------------------------------------------


def test_pick_highest_version_single():
    files = ["/nfs/pretext/sDipInt39_1_hr.pretext"]
    assert _pick_highest_version(files) == files[0]


def test_pick_highest_version_prefers_rc():
    files = [
        "/nfs/pretext/sDipInt39_1_hr.pretext",
        "/nfs/pretext/sDipInt39_RC_2_hr.pretext",
    ]
    result = _pick_highest_version(files)
    assert "RC" in Path(result).name


def test_pick_highest_version_picks_highest_index():
    files = [
        "/nfs/pretext/sDipInt39_1_2_hr.pretext",
        "/nfs/pretext/sDipInt39_1_5_hr.pretext",
        "/nfs/pretext/sDipInt39_1_3_hr.pretext",
    ]
    result = _pick_highest_version(files)
    assert "_5_" in Path(result).name


# ---------------------------------------------------------------------------
# setup_curation
# ---------------------------------------------------------------------------


@patch("grit.steps.pre_curation.setup._validate_scaffold_headers")
@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob")
def test_setup_curation_initial_hap1hap2(
    mock_glob, mock_run, mock_validate_headers, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.assembly_draft_dir = Path("/lustre/draft")
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    hap1 = "/lustre/draft/sDipInt39.1/sDipInt39.1.hap1.decontaminated.fa.gz"
    hap2 = "/lustre/draft/sDipInt39.1/sDipInt39.1.hap2.decontaminated.fa.gz"

    # glob returns hap1 on first call, hap2 on second
    mock_glob.side_effect = [[hap1], [hap2]]

    # _run succeeds silently; also need tmp workdir to exist for mtime sort
    # patch _sort_by_mtime since files don't exist on disk
    with patch("grit.steps.pre_curation.setup._sort_by_mtime", side_effect=lambda x: x):
        setup_curation(mock_ctx)

    # mkdir and zcat should have been called
    calls = [str(c) for c in mock_run.call_args_list]
    assert any("mkdir" in c for c in calls)
    assert any("zcat" in c and "hap1" in c and "hap2" in c for c in calls)


@patch("grit.steps.pre_curation.setup._validate_scaffold_headers")
@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob")
def test_setup_curation_initial_single_hap(
    mock_glob, mock_run, mock_validate_headers, mock_ctx, tmp_path
):
    """When hap2 is not found, only hap1 should appear in the zcat command."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.assembly_draft_dir = Path("/lustre/draft")
    mock_ctx.tol_id = "ilHelSara1"
    mock_ctx.hap1_prefix = "primary"
    mock_ctx.hap2_prefix = "alternate"

    hap1 = "/lustre/draft/ilHelSara1.1/ilHelSara1.1.primary.decontaminated.fa.gz"

    mock_glob.side_effect = [[hap1], [], []]  # no hap2, no haplotigs fallback either

    with patch("grit.steps.pre_curation.setup._sort_by_mtime", side_effect=lambda x: x):
        setup_curation(mock_ctx)

    zcat_calls = [str(c) for c in mock_run.call_args_list if "zcat" in str(c)]
    assert len(zcat_calls) == 1
    # hap2 placeholder should be empty string (no path injected)
    assert "primary" in zcat_calls[0]


@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob", return_value=[])
def test_setup_curation_raises_when_no_hap1(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.assembly_draft_dir = Path("/lustre/draft")
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    with pytest.raises(FileNotFoundError, match="decontaminated hap1"):
        setup_curation(mock_ctx)


# ---------------------------------------------------------------------------
# _resolve_hap2_fasta — haplotigs fallback
# ---------------------------------------------------------------------------


@patch("grit.steps.pre_curation.setup._sort_by_mtime", side_effect=lambda x: x)
@patch("grit.steps.pre_curation.setup.glob.glob")
def test_resolve_hap2_fasta_falls_back_to_haplotigs(mock_glob, mock_sort, mock_ctx):
    """When the hap2_prefix ('alternate') glob is empty, fall back to '*haplotigs*'."""
    mock_ctx.assembly_draft_dir = Path("/lustre/draft")
    mock_ctx.tol_id = "ilBrySene2"
    mock_ctx.hap2_prefix = "alternate"

    haplotigs_file = "/lustre/draft/ilBrySene2.20260615.haplotigs.decontaminated.fa.gz"
    mock_glob.side_effect = [[], [haplotigs_file]]

    result = _resolve_hap2_fasta(mock_ctx)

    assert result == haplotigs_file
    assert "haplotigs" in mock_glob.call_args_list[1].args[0]


@patch("grit.steps.pre_curation.setup.glob.glob", return_value=[])
def test_resolve_hap2_fasta_returns_empty_when_nothing_found(mock_glob, mock_ctx):
    mock_ctx.assembly_draft_dir = Path("/lustre/draft")
    mock_ctx.tol_id = "ilHelSara1"
    mock_ctx.hap2_prefix = "alternate"

    assert _resolve_hap2_fasta(mock_ctx) == ""


# ---------------------------------------------------------------------------
# setup_curation — print-only mirrors the real haplotigs fallback
# ---------------------------------------------------------------------------


@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob")
def test_setup_curation_print_only_reflects_haplotigs_fallback(mock_glob, mock_run, mock_ctx):
    """print-only must show the file that would actually be picked, not just the pattern."""
    mock_ctx.print_only = True
    mock_ctx.assembly_draft_dir = Path("/lustre/draft")
    mock_ctx.tol_id = "ilBrySene2"
    mock_ctx.hap1_prefix = "primary"
    mock_ctx.hap2_prefix = "alternate"

    hap1 = "/lustre/draft/ilBrySene2.primary.decontaminated.fa.gz"
    haplotigs_file = "/lustre/draft/ilBrySene2.haplotigs.decontaminated.fa.gz"
    # hap1: found on first try. hap2: alternate pattern empty, haplotigs fallback matches.
    mock_glob.side_effect = [[hap1], [], [haplotigs_file]]

    with patch("grit.steps.pre_curation.setup._sort_by_mtime", side_effect=lambda x: x):
        setup_curation(mock_ctx)

    zcat_calls = [str(c) for c in mock_run.call_args_list if "zcat" in str(c)]
    assert len(zcat_calls) == 1
    assert haplotigs_file in zcat_calls[0]


# ---------------------------------------------------------------------------
# _peek_first_fasta_header / _validate_scaffold_headers
# ---------------------------------------------------------------------------


def test_peek_first_fasta_header_plain(tmp_path):
    fasta = tmp_path / "test.fa"
    fasta.write_text(">SCAFFOLD_1 some description\nACGT\n>SCAFFOLD_2\nACGT\n")
    assert _peek_first_fasta_header(str(fasta)) == ">SCAFFOLD_1 some description"


def test_peek_first_fasta_header_gzipped(tmp_path):
    import gzip

    fasta = tmp_path / "test.fa.gz"
    with gzip.open(fasta, "wt") as fh:
        fh.write(">HAPM_SCAFFOLD_3\nACGT\n")
    assert _peek_first_fasta_header(str(fasta)) == ">HAPM_SCAFFOLD_3"


def test_validate_scaffold_headers_accepts_scaffold(tmp_path):
    fasta = tmp_path / "test.fa"
    fasta.write_text(">SCAFFOLD_1\nACGT\n")
    _validate_scaffold_headers(str(fasta))  # should not raise


def test_validate_scaffold_headers_accepts_hapm_scaffold(tmp_path):
    fasta = tmp_path / "test.fa"
    fasta.write_text(">HAPM_SCAFFOLD_7\nACGT\n")
    _validate_scaffold_headers(str(fasta))  # should not raise


def test_validate_scaffold_headers_rejects_raw_contig_header(tmp_path):
    fasta = tmp_path / "test.fa"
    fasta.write_text(">atg000001l\nACGT\n")
    with pytest.raises(ValueError, match="atg000001l"):
        _validate_scaffold_headers(str(fasta))


@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob")
def test_setup_curation_raises_on_bad_headers(mock_glob, mock_run, mock_ctx, tmp_path):
    """setup_curation must fail loudly instead of concatenating unrenamed contigs."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.assembly_draft_dir = Path("/lustre/draft")
    mock_ctx.tol_id = "ilBrySene2"
    mock_ctx.hap1_prefix = "primary"
    mock_ctx.hap2_prefix = "alternate"

    bad_hap1 = tmp_path / "ilBrySene2.primary.decontaminated.fa"
    bad_hap1.write_text(">atg000001l\nACGT\n")
    mock_glob.side_effect = [[str(bad_hap1)]]

    with patch("grit.steps.pre_curation.setup._sort_by_mtime", side_effect=lambda x: x):
        with pytest.raises(ValueError, match="atg000001l"):
            setup_curation(mock_ctx)

    zcat_calls = [str(c) for c in mock_run.call_args_list if "zcat" in str(c)]
    assert not zcat_calls


# ---------------------------------------------------------------------------
# copy_pretext_maps
# ---------------------------------------------------------------------------


@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob")
def test_copy_pretext_maps_copies_and_prints_scp(mock_glob, mock_run, mock_ctx, capsys, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.pretext_maps_nfs = Path("/nfs/pretext_maps")
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.farm_host = "farm22"

    hr = "/nfs/pretext_maps/sDipInt39_1_1_hr.pretext"
    normal = "/nfs/pretext_maps/sDipInt39_1_1_normal.pretext"
    mock_glob.side_effect = [[hr], [normal], []]  # no ultra

    copy_pretext_maps(mock_ctx)

    cp_calls = [str(c) for c in mock_run.call_args_list if "cp" in str(c)]
    assert len(cp_calls) == 2
    assert any("hr.pretext" in c for c in cp_calls)
    assert any("normal.pretext" in c for c in cp_calls)


@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob", return_value=[])
def test_copy_pretext_maps_raises_when_no_hr(mock_glob, mock_run, mock_ctx):
    mock_ctx.pretext_maps_nfs = Path("/nfs/pretext_maps")
    mock_ctx.tol_id = "sDipInt39"

    with pytest.raises(FileNotFoundError, match="hi-res pretext"):
        copy_pretext_maps(mock_ctx)


@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob")
def test_copy_pretext_maps_raises_when_no_normal(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.pretext_maps_nfs = Path("/nfs/pretext_maps")
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.farm_host = "farm22"

    hr = "/nfs/pretext_maps/sDipInt39_1_1_hr.pretext"
    mock_glob.side_effect = [[hr], [], []]  # no normal, no ultra

    with pytest.raises(FileNotFoundError, match="normal pretext"):
        copy_pretext_maps(mock_ctx)


@patch("grit.steps.pre_curation.setup._run")
@patch("grit.steps.pre_curation.setup.glob.glob")
def test_copy_pretext_maps_picks_highest_when_multiple(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.pretext_maps_nfs = Path("/nfs/pretext_maps")
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.farm_host = "farm22"

    hr_files = [
        "/nfs/pretext_maps/sDipInt39_1_2_hr.pretext",
        "/nfs/pretext_maps/sDipInt39_1_5_hr.pretext",
    ]
    normal_files = ["/nfs/pretext_maps/sDipInt39_1_1_normal.pretext"]
    mock_glob.side_effect = [hr_files, normal_files, []]  # no ultra

    copy_pretext_maps(mock_ctx)

    cp_calls = " ".join(str(c) for c in mock_run.call_args_list)
    assert "_5_" in cp_calls  # highest version picked


# ---------------------------------------------------------------------------
# print_curation_summary
# ---------------------------------------------------------------------------


def test_print_curation_summary_runs_without_error(mock_ctx):
    """Smoke test — should not raise."""
    print_curation_summary(mock_ctx)


def test_print_curation_summary_primary(mock_ctx_primary):
    """Should handle primary/alternate assembly type without error."""
    print_curation_summary(mock_ctx_primary)


def test_print_curation_summary_includes_karyotype(mock_ctx):
    """If YAML contains karyotype, it should be printed without raising."""
    mock_ctx.yaml_data["karyotype"] = "2n=52"
    print_curation_summary(mock_ctx)


def test_print_curation_summary_includes_sex(mock_ctx):
    mock_ctx.yaml_data["expected_sex"] = "female"
    print_curation_summary(mock_ctx)


def test_print_curation_summary_with_teloseq(mock_ctx):
    mock_ctx.teloseq = "--teloseq TTAGG"
    print_curation_summary(mock_ctx)
