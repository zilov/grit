"""Tests for the pretext-to-asm-recurate step."""

from pathlib import Path
from unittest.mock import patch

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.post_curation.pretext_to_asm_recurate import run_pretext_to_asm_recurate


def _tracker(tmp_path, ctx):
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)
    return ctx.tracker


def _write(path, content=">seq\nACGT\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


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

    def _fake_run(cmd, print_only, **kwargs):
        # simulate pretext-to-asm writing its own new haplotigs file into run_dir
        out_fa = Path(cmd.split("-o ")[1].split()[0])
        _write(out_fa.parent / "sDipInt39.additional_haplotigs.curated.fa", ">new\nCCCC\n")
        return ""

    mock_run.side_effect = _fake_run

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    merged_path = Path(tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs"))
    content = merged_path.read_text()
    assert ">old" in content
    assert ">new" in content


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
    mock_run.return_value = ""  # no new haplotigs file written

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

    def _fake_run(cmd, print_only, **kwargs):
        out_fa = Path(cmd.split("-o ")[1].split()[0])
        _write(out_fa.parent / "sDipInt39.additional_haplotigs.curated.fa", ">new\nCCCC\n")
        return ""

    mock_run.side_effect = _fake_run

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
    mock_run.return_value = ""

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
