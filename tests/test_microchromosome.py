"""Tests for the birds microchromosome second-shot + combine steps."""

from pathlib import Path
from unittest.mock import patch

import pytest

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.post_curation.microchromosome_combine import run_microchromosome_combine
from grit.steps.pre_curation.microchromosome_second_shot import (
    CURATED_SMALL_AGP_DIR,
    run_microchromosome_second_shot,
)


def _attach_tracker(ctx, tmp_path):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)


# ---------------------------------------------------------------------------
# run_microchromosome_second_shot
# ---------------------------------------------------------------------------


@patch("grit.steps.pre_curation.microchromosome_second_shot._run")
@patch("grit.steps.pre_curation.microchromosome_second_shot.find_canonical_chr_list")
@patch("grit.steps.pre_curation.microchromosome_second_shot.find_canonical_fa")
def test_run_microchromosome_second_shot_single_hap(
    mock_find_fa, mock_find_chr, mock_run, mock_ctx_primary, tmp_path
):
    """primary/alternate (single-hap) tickets never process a hap2."""
    mock_ctx_primary.workdir = tmp_path
    mock_ctx_primary.tol_id = "bColMon1"
    mock_ctx_primary.print_only = False

    mock_find_fa.return_value = tmp_path / "bColMon1.1.primary.curated.fa"
    mock_find_chr.return_value = tmp_path / "bColMon1.1.primary.chromosome.list.csv"

    run_microchromosome_second_shot(mock_ctx_primary)

    mock_run.assert_called_once()
    mock_find_fa.assert_called_once_with(mock_ctx_primary, "primary")
    cmd = mock_run.call_args[0][0]
    assert "microchr_second_shot_curation.py" in cmd
    assert "-hap1" in cmd
    assert "-hap2" not in cmd
    assert str(tmp_path / "microchromosome_second_shot" / "untracked") in cmd


@patch("grit.steps.pre_curation.microchromosome_second_shot._run")
@patch("grit.steps.pre_curation.microchromosome_second_shot.find_canonical_chr_list")
@patch("grit.steps.pre_curation.microchromosome_second_shot.find_canonical_fa")
def test_run_microchromosome_second_shot_hap1_and_hap2(
    mock_find_fa, mock_find_chr, mock_run, mock_ctx, tmp_path
):
    """hap1/hap2 tickets always process both haplotypes — no --hap2 flag needed,
    unlike rename-and-orient (the script takes both in a single invocation)."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    hap1_fa = tmp_path / "bColMon1.hap1.1.curated.fa"
    hap2_fa = tmp_path / "bColMon1.hap2.1.curated.fa"
    mock_find_fa.side_effect = lambda ctx, hap: hap1_fa if hap == "hap1" else hap2_fa
    mock_find_chr.side_effect = lambda ctx, hap: tmp_path / f"bColMon1.{hap}.chromosome.list.csv"

    run_microchromosome_second_shot(mock_ctx)

    cmd = mock_run.call_args[0][0]
    assert "-hap2" in cmd
    assert str(hap1_fa) in cmd
    assert str(hap2_fa) in cmd
    assert f"-rt {mock_ctx.read_type}" in cmd


@patch("grit.steps.pre_curation.microchromosome_second_shot.find_canonical_fa")
def test_run_microchromosome_second_shot_raises_when_no_curated_fasta(mock_find_fa, mock_ctx):
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False
    mock_find_fa.side_effect = FileNotFoundError("No curated FASTA for 'hap1' found")

    with pytest.raises(FileNotFoundError):
        run_microchromosome_second_shot(mock_ctx)


def _write_real_second_shot_layout(second_shot_dir: Path, tol_id: str = "bColMon1") -> None:
    """Recreate the layout a real microchr_second_shot_curation.py run writes."""
    out = second_shot_dir / tol_id
    (out / "hic" / "pretext_maps_processed").mkdir(parents=True, exist_ok=True)
    (out / f"{tol_id}.hap1.1.primary.curated.large.fa").write_text(">seq\n")
    (out / f"{tol_id}_hap1.large.chr_list.csv").write_text("")
    (out / f"{tol_id}_curated_small_merged.fa").write_text(">seq\n")
    (out / "hic" / "pretext_maps_processed" / f"{tol_id}.hap1.hr.pretext").write_text("")


def _write_real_second_shot_hap2(second_shot_dir: Path, tol_id: str = "bColMon1") -> None:
    out = second_shot_dir / tol_id
    (out / f"{tol_id}.hap2.1.primary.curated.large.fa").write_text(">seq\n")
    (out / f"{tol_id}_hap2.large.chr_list.csv").write_text("")


def _write_micro_pta_outputs(pta_dir: Path, tol_id: str = "bColMon1", hap: str = "hap1") -> None:
    """Recreate the curated small fasta/chr-list a micro pretext-to-asm run writes."""
    pta_dir.mkdir(parents=True, exist_ok=True)
    (pta_dir / f"{tol_id}_small.{hap}.1.curated.fa").write_text(">seq\n")
    (pta_dir / f"{tol_id}_small.{hap}.1.chromosome.list.csv").write_text("")


def test_second_shot_output_specs_match_real_run_layout(tmp_path):
    """Every spec must match the real {tol_id}/ subdir layout, not the inferred flat one."""
    from grit.steps.pre_curation.microchromosome_second_shot import _OUTPUT_SPECS
    from grit.utils.helpers import collect_outputs

    _write_real_second_shot_layout(tmp_path)

    outputs = collect_outputs(_OUTPUT_SPECS, tmp_path, "bColMon1")
    assert set(outputs) == {"hap1_large_fa", "hap1_large_chr", "merged_small_fa", "pretext_map"}
    assert outputs["hap1_large_fa"].endswith("bColMon1.hap1.1.primary.curated.large.fa")
    assert outputs["hap1_large_chr"].endswith("bColMon1_hap1.large.chr_list.csv")
    assert outputs["merged_small_fa"].endswith("bColMon1_curated_small_merged.fa")
    assert "/bColMon1/hic/pretext_maps_processed/" in outputs["pretext_map"]

    _write_real_second_shot_hap2(tmp_path)
    outputs = collect_outputs(_OUTPUT_SPECS, tmp_path, "bColMon1")
    assert outputs["hap2_large_fa"].endswith("bColMon1.hap2.1.primary.curated.large.fa")
    assert outputs["hap2_large_chr"].endswith("bColMon1_hap2.large.chr_list.csv")


def test_second_shot_creates_curated_small_agp_dir(mock_ctx, tmp_path):
    """The curator's upload dir for the curated small AGP is created by the pre step."""
    from grit.steps.pre_curation.microchromosome_second_shot import CURATED_SMALL_AGP_DIR

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.print_only = False

    with (
        patch("grit.steps.pre_curation.microchromosome_second_shot._run"),
        patch("grit.steps.pre_curation.microchromosome_second_shot.find_canonical_fa"),
        patch("grit.steps.pre_curation.microchromosome_second_shot.find_canonical_chr_list"),
    ):
        run_microchromosome_second_shot(mock_ctx)

    run_dir = tmp_path / "microchromosome_second_shot" / "untracked"
    assert (run_dir / CURATED_SMALL_AGP_DIR).is_dir()


@patch("grit.steps.pre_curation.microchromosome_second_shot._run")
def test_run_microchromosome_second_shot_dry_run_short_circuits(mock_run, mock_ctx, tmp_path):
    """dry_run must skip curated-FASTA lookup + second-shot script entirely."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_microchromosome_second_shot(mock_ctx)

    mock_run.assert_not_called()

    outputs = mock_ctx.tracker.history("microchromosome_second_shot")[-1]["outputs"]
    assert set(outputs) == {
        "hap1_large_fa",
        "hap2_large_fa",
        "hap1_large_chr",
        "hap2_large_chr",
        "merged_small_fa",
        "pretext_map",
    }
    for key in outputs:
        assert Path(outputs[key]).exists()


@patch("grit.steps.pre_curation.microchromosome_second_shot._run")
def test_run_microchromosome_second_shot_dry_run_single_hap_omits_hap2(
    mock_run, mock_ctx_primary, tmp_path
):
    """A single-hap (primary/alternate) dry run must not fabricate hap2 outputs."""
    _attach_tracker(mock_ctx_primary, tmp_path)
    mock_ctx_primary.dry_run = True

    run_microchromosome_second_shot(mock_ctx_primary)

    mock_run.assert_not_called()

    outputs = mock_ctx_primary.tracker.history("microchromosome_second_shot")[-1]["outputs"]
    assert "hap1_large_fa" in outputs
    assert "hap2_large_fa" not in outputs
    assert "hap2_large_chr" not in outputs

    run_dir = mock_ctx_primary.tracker.history("microchromosome_second_shot")[-1]["run_dir"]
    assert list(Path(run_dir).rglob("*hap2*")) == []


# ---------------------------------------------------------------------------
# run_microchromosome_combine
# ---------------------------------------------------------------------------


def test_run_microchromosome_combine_raises_when_no_merged_small_fa(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.print_only = False

    with pytest.raises(FileNotFoundError, match="No merged small FASTA found"):
        run_microchromosome_combine(mock_ctx)


@patch("grit.steps.post_curation.microchromosome_combine._run")
def test_run_microchromosome_combine_print_only_skips_checks(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = True

    # Should not raise even though no files exist on disk
    run_microchromosome_combine(mock_ctx)

    assert mock_run.call_count >= 1
    cmd = mock_run.call_args_list[0][0][0]
    assert "combine_curated_micros.py" in cmd


@patch("grit.steps.post_curation.microchromosome_combine._run")
@patch("grit.steps.post_curation.pretext_to_asm._run")
def test_run_microchromosome_combine_hap1_only(mock_pta_run, mock_combine_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    second_shot_dir = tmp_path / "microchromosome_second_shot" / "untracked"
    _write_real_second_shot_layout(second_shot_dir)
    agp = second_shot_dir / CURATED_SMALL_AGP_DIR / "bColMon1_small_curated.agp"
    agp.parent.mkdir(parents=True)
    agp.write_text("")
    _write_micro_pta_outputs(tmp_path / "pretext_to_asm_micro" / "untracked")

    run_microchromosome_combine(mock_ctx)

    # pretext-to-asm ran once, over the merged small FASTA + curated micro AGP
    mock_pta_run.assert_called_once()
    pta_cmd = mock_pta_run.call_args[0][0]
    assert "pretext-to-asm" in pta_cmd
    assert "bColMon1_curated_small_merged.fa" in pta_cmd
    assert str(agp) in pta_cmd

    # combine_curated_micros.py ran once, for hap1 only (no hap2 large fa present)
    mock_combine_run.assert_called_once()
    combine_cmd = mock_combine_run.call_args[0][0]
    assert "combine_curated_micros.py" in combine_cmd
    assert str(second_shot_dir / "bColMon1" / "bColMon1.hap1.1.primary.curated.large.fa") in (
        combine_cmd
    )
    assert str(second_shot_dir / "bColMon1" / "bColMon1_hap1.large.chr_list.csv") in combine_cmd


@patch("grit.steps.post_curation.microchromosome_combine._run")
@patch("grit.steps.post_curation.pretext_to_asm._run")
def test_run_microchromosome_combine_hap1_and_hap2(
    mock_pta_run, mock_combine_run, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    second_shot_dir = tmp_path / "microchromosome_second_shot" / "untracked"
    _write_real_second_shot_layout(second_shot_dir)
    _write_real_second_shot_hap2(second_shot_dir)
    agp_dir = second_shot_dir / CURATED_SMALL_AGP_DIR
    agp_dir.mkdir(parents=True)
    (agp_dir / "bColMon1_small_curated.agp").write_text("")
    pta_dir = tmp_path / "pretext_to_asm_micro" / "untracked"
    _write_micro_pta_outputs(pta_dir)
    _write_micro_pta_outputs(pta_dir, hap="hap2")

    run_microchromosome_combine(mock_ctx)

    assert mock_combine_run.call_count == 2
    cmds = [call[0][0] for call in mock_combine_run.call_args_list]
    out = second_shot_dir / "bColMon1"
    assert any(str(out / "bColMon1.hap1.1.primary.curated.large.fa") in c for c in cmds)
    assert any(str(out / "bColMon1.hap2.1.primary.curated.large.fa") in c for c in cmds)


def test_combine_output_specs_use_literal_hap_tokens():
    from grit.steps.post_curation.microchromosome_combine import _OUTPUT_SPECS

    keys = [key for key, _pattern, _excludes in _OUTPUT_SPECS]
    assert "hap1_fa" in keys
    assert "hap2_fa" in keys


# ---------------------------------------------------------------------------
# run_microchromosome_combine — dry-run
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.microchromosome_combine._run")
@patch("grit.steps.post_curation.microchromosome_combine.find_latest_dir")
def test_dry_run_short_circuits_before_any_real_work(mock_find_dir, mock_run, mock_ctx, tmp_path):
    """dry_run must skip the second-shot dir lookup + combine_curated_micros.py
    pipeline entirely — no _run() call and no dependency on find_latest_dir."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_microchromosome_combine(mock_ctx)

    mock_run.assert_not_called()
    mock_find_dir.assert_not_called()

    outputs = mock_ctx.tracker.history("microchromosome_combine")[-1]["outputs"]
    assert set(outputs) == {"hap1_fa", "hap2_fa", "hap1_chr_list", "hap2_chr_list"}
    for key in outputs:
        assert Path(outputs[key]).exists()


@patch("grit.steps.post_curation.microchromosome_combine._run")
@patch("grit.steps.post_curation.microchromosome_combine.find_latest_dir")
def test_dry_run_single_hap_tracks_only_hap1(mock_find_dir, mock_run, mock_ctx_primary, tmp_path):
    """A single-hap (primary/alternate) dry run must only ever track hap1's fake
    outputs — a primary/alternate assembly never has a genuine second haplotype
    to combine in the microchromosome-second-shot workflow."""
    _attach_tracker(mock_ctx_primary, tmp_path)
    mock_ctx_primary.dry_run = True

    run_microchromosome_combine(mock_ctx_primary)

    mock_run.assert_not_called()
    mock_find_dir.assert_not_called()

    last_run = mock_ctx_primary.tracker.history("microchromosome_combine")[-1]
    outputs = last_run["outputs"]
    assert set(outputs) == {"hap1_fa", "hap1_chr_list"}
    assert "hap2_fa" not in outputs
    assert "hap2_chr_list" not in outputs

    # Popping the tracker keys isn't enough — a leftover file would still be
    # findable by any glob-based (not tracker-based) hap2 detection downstream.
    run_dir = last_run["run_dir"]
    assert list(Path(run_dir).glob("*.hap2.*")) == []
    assert list(Path(run_dir).glob("*.alternate.*")) == []


def test_dry_run_output_resolves_via_find_canonical_fa(mock_ctx, tmp_path):
    """The fake output written in dry-run mode must resolve through the real
    canonical-FASTA resolution pool, not just via tracker bookkeeping."""
    from grit.utils.helpers import find_canonical_fa

    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_microchromosome_combine(mock_ctx)

    expected = Path(mock_ctx.tracker.get_output("microchromosome_combine", "hap1_fa"))
    resolved = find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix)
    assert resolved == expected


# ---------------------------------------------------------------------------
# curated small AGP pick
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.microchromosome_combine._run")
@patch("grit.steps.post_curation.pretext_to_asm._run")
def test_combine_ignores_agps_outside_the_curated_agp_dir(
    mock_pta_run, mock_combine_run, mock_ctx, tmp_path
):
    """A pretext-to-asm-generated AGP sitting in the run dir must never be picked."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    second_shot_dir = tmp_path / "microchromosome_second_shot" / "untracked"
    _write_real_second_shot_layout(second_shot_dir)
    (second_shot_dir / "bColMon1.1.primary.curated.agp").write_text("")
    agp = second_shot_dir / CURATED_SMALL_AGP_DIR / "bColMon1_small_curated.agp"
    agp.parent.mkdir(parents=True)
    agp.write_text("")
    _write_micro_pta_outputs(tmp_path / "pretext_to_asm_micro" / "untracked")

    run_microchromosome_combine(mock_ctx)

    pta_cmd = mock_pta_run.call_args[0][0]
    assert f"-p {agp}" in pta_cmd
    assert str(second_shot_dir / "bColMon1.1.primary.curated.agp") not in pta_cmd


def test_agp_pick_is_deterministic_and_fails_on_multiple_matches(mock_ctx, tmp_path):
    """More than one matching AGP must fail loudly rather than pick one arbitrarily."""
    from grit.steps.post_curation.pretext_to_asm import _OUTPUT_SPECS, _run_pretext_to_asm_core

    mock_ctx.workdir = tmp_path
    mock_ctx.print_only = False
    original_fa = tmp_path / "original.fa"
    original_fa.write_text(">seq\n")
    (tmp_path / "sDipInt39.a.agp").write_text("")
    (tmp_path / "sDipInt39.b.agp").write_text("")

    with pytest.raises(FileNotFoundError, match="2 AGP files match"):
        _run_pretext_to_asm_core(
            mock_ctx,
            "pretext_to_asm",
            original_fa,
            "missing",
            tmp_path,
            "sDipInt39.fa",
            _OUTPUT_SPECS,
        )


# ---------------------------------------------------------------------------
# missing required inputs
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.pretext_to_asm._run")
def test_combine_fails_loudly_when_large_fasta_missing(mock_pta_run, mock_ctx, tmp_path):
    """A missing large FASTA must fail, not hand a non-existent path to the script."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    second_shot_dir = tmp_path / "microchromosome_second_shot" / "untracked"
    out = second_shot_dir / "bColMon1"
    out.mkdir(parents=True)
    (out / "bColMon1_curated_small_merged.fa").write_text(">seq\n")
    agp = second_shot_dir / CURATED_SMALL_AGP_DIR / "bColMon1_small_curated.agp"
    agp.parent.mkdir(parents=True)
    agp.write_text("")
    _write_micro_pta_outputs(tmp_path / "pretext_to_asm_micro" / "untracked")

    with pytest.raises(FileNotFoundError, match="hap1 large FASTA"):
        run_microchromosome_combine(mock_ctx)


@patch("grit.steps.post_curation.pretext_to_asm._run")
def test_combine_fails_loudly_when_curated_small_fasta_missing(mock_pta_run, mock_ctx, tmp_path):
    """No usable micro pretext-to-asm output must fail before combine_curated_micros.py."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    second_shot_dir = tmp_path / "microchromosome_second_shot" / "untracked"
    _write_real_second_shot_layout(second_shot_dir)
    agp = second_shot_dir / CURATED_SMALL_AGP_DIR / "bColMon1_small_curated.agp"
    agp.parent.mkdir(parents=True)
    agp.write_text("")

    with pytest.raises(FileNotFoundError, match="curated hap1 small FASTA"):
        run_microchromosome_combine(mock_ctx)
