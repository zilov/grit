"""Tests for the pretext-to-asm-recurate step."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from grit.core.click_cli import cli
from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.post_curation.pretext_to_asm_recurate import run_pretext_to_asm_recurate
from grit.utils.helpers import inputs_newer_than_curated_fa


def _tracker(tmp_path, ctx):
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)
    return ctx.tracker


def _write(path, content=">seq\nACGT\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _fake_pta_run(curated_name="sDipInt39.1.primary.curated.fa", haplotigs_name=None):
    """_run side effect simulating pretext-to-asm writing its outputs into run_dir."""

    def _side_effect(cmd, print_only, **kwargs):
        run_dir = Path(cmd.split("-o ")[1].split()[0]).parent
        if curated_name:
            _write(run_dir / curated_name, ">chr1\nACGT\n")
        if haplotigs_name:
            _write(run_dir / haplotigs_name, ">new\nCCCC\n")
        return ""

    return _side_effect


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_agp_glob_picks_hap1_file_and_ignores_hap2(
    mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    """The AGP glob must be hap-qualified so it doesn't pick up the other hap's file."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    hap1_agp = str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")
    mock_glob.return_value = [hap1_agp]
    mock_run.return_value = ""

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    glob_pattern = mock_glob.call_args[0][0]
    assert "hap1" in glob_pattern
    assert str(tmp_path / "recurate") in glob_pattern


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_input_fasta_comes_from_find_canonical_fa(
    mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    canonical_fa = _write(tmp_path / "blast_contaminants" / "hap1.fa")
    mock_find_fa.return_value = canonical_fa
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.return_value = ""

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    mock_find_fa.assert_called_once_with(mock_ctx, "hap1")
    calls = [str(c) for c in mock_run.call_args_list]
    assert any(str(canonical_fa) in c for c in calls)


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_haplotig_merge_both_nonempty_concatenates(
    mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    prior_dir = tmp_path / "pretext_to_asm" / "run1"
    prior_haplotigs = _write(
        prior_dir / "sDipInt39.hap1.1.all_haplotigs.curated.fa", ">old\nAAAA\n"
    )
    tracker.finish(
        "pretext_to_asm", prior_dir, "success", outputs={"hap1_haplotigs": str(prior_haplotigs)}
    )

    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]

    mock_run.side_effect = _fake_pta_run(haplotigs_name="sDipInt39.additional_haplotigs.curated.fa")

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    merged_path = Path(tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs"))
    content = merged_path.read_text()
    assert ">old" in content
    assert ">new" in content
    # follows the haplotig_files.py naming convention so finalize_qc's
    # "all_haplotigs" sniffing and manifests' {tol_id}*.curated.fa glob both match
    assert merged_path.name == "sDipInt39.hap1.1.all_haplotigs.curated.fa"


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_haplotig_merge_prior_only_carries_forward(
    mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    """Prior haplotigs non-empty, new run produces none — prior must be carried forward."""
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    prior_dir = tmp_path / "pretext_to_asm" / "run1"
    prior_haplotigs = _write(
        prior_dir / "sDipInt39.hap1.1.all_haplotigs.curated.fa", ">old\nAAAA\n"
    )
    tracker.finish(
        "pretext_to_asm", prior_dir, "success", outputs={"hap1_haplotigs": str(prior_haplotigs)}
    )

    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.side_effect = _fake_pta_run()  # curated fa only, no new haplotigs

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    merged_path = Path(tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs"))
    assert ">old" in merged_path.read_text()


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_haplotigs")
def test_haplotig_merge_new_only_uses_new(
    mock_find_haplotigs, mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    """No prior haplotigs at all, new run produces some — use the new file as-is."""
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_haplotigs.side_effect = FileNotFoundError("none yet")
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]

    mock_run.side_effect = _fake_pta_run(haplotigs_name="sDipInt39.additional_haplotigs.curated.fa")

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    merged_path = Path(tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs"))
    assert ">new" in merged_path.read_text()


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_haplotigs")
def test_haplotig_merge_neither_tracks_nothing(
    mock_find_haplotigs, mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    """No prior and no new haplotigs — nothing tracked under the haplotigs key."""
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_haplotigs.side_effect = FileNotFoundError("none")
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.side_effect = _fake_pta_run()

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    assert tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs") is None


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_prints_ordering_tip(mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path, capsys):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.return_value = ""

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    out = capsys.readouterr().out
    assert "canonical priority" in out


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_creates_recurate_dir_and_prints_expected_agp_path(
    mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path, capsys
):
    """The recurate/ upload dir must exist and its naming convention be advertised."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.side_effect = _fake_pta_run()

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    assert (tmp_path / "recurate").is_dir()
    out = capsys.readouterr().out.replace("\n", "")
    assert "sDipInt39.hap1.recurate.agp" in out


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_hap_qualified_curated_fa_is_tracked(mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path):
    """pretext-to-asm's hap-qualified naming shape must resolve, not just .primary."""
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.side_effect = _fake_pta_run(curated_name="sDipInt39.hap1.1.curated.fa")

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    tracked = tracker.get_output("pretext_to_asm_recurate", "hap1_fa")
    assert tracked is not None
    assert Path(tracked).name == "sDipInt39.hap1.1.curated.fa"


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_missing_curated_fa_output_raises_instead_of_silent_success(
    mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    """No recognised curated FASTA → raise, never report success with stale canonical data."""
    _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.side_effect = _fake_pta_run(curated_name="sDipInt39.unexpected_shape.fasta")

    with pytest.raises(FileNotFoundError, match="no curated FASTA"):
        run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")


# ---------------------------------------------------------------------------
# Re-run freshness check must be hap-scoped
# ---------------------------------------------------------------------------


def test_freshness_check_ignores_other_haps_newer_agp(tmp_path):
    """
    A newer hap2 recurate AGP in the same recurate/ dir must not make hap1's own
    curated FASTA look stale — otherwise hap1 gets a spurious, non-idempotent re-run.
    """
    recurate_dir = tmp_path / "recurate"
    hap1_agp = _write(recurate_dir / "sDipInt39.hap1.recurate.agp", "agp\n")
    prev_dir = tmp_path / "pretext_to_asm_recurate" / "run1"
    hap1_curated = _write(prev_dir / "sDipInt39.hap1.1.curated.fa")
    hap2_agp = _write(recurate_dir / "sDipInt39.hap2.recurate.agp", "agp\n")

    # hap1 AGP older than hap1 output; hap2 AGP newer than everything
    os.utime(hap1_agp, (1000, 1000))
    os.utime(hap1_curated, (2000, 2000))
    os.utime(hap2_agp, (3000, 3000))

    # hap-scoped: hap1 is up to date
    assert (
        inputs_newer_than_curated_fa(
            recurate_dir, "sDipInt39", prev_dir, agp_glob="sDipInt39*hap1*.agp*"
        )
        is False
    )
    # unscoped (old behaviour): the unrelated hap2 AGP wrongly triggers a re-run
    assert inputs_newer_than_curated_fa(recurate_dir, "sDipInt39", prev_dir) is True
    # hap2's own check does see its newer AGP
    assert (
        inputs_newer_than_curated_fa(
            recurate_dir, "sDipInt39", prev_dir, agp_glob="sDipInt39*hap2*.agp*"
        )
        is True
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_help():
    result = CliRunner().invoke(cli, ["pretext-to-asm-recurate", "--help"])
    assert result.exit_code == 0
    assert "--hap2" in result.output
