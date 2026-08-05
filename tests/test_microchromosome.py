"""Tests for the birds microchromosome second-shot + combine steps."""

from unittest.mock import patch

import pytest

from grit.steps.post_curation.microchromosome_combine import run_microchromosome_combine
from grit.steps.pre_curation.microchromosome_second_shot import run_microchromosome_second_shot

# ---------------------------------------------------------------------------
# run_microchromosome_second_shot
# ---------------------------------------------------------------------------


@patch("grit.steps.pre_curation.microchromosome_second_shot._run")
def test_run_microchromosome_second_shot_hap1_only(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    run_microchromosome_second_shot(mock_ctx)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "microchr_second_shot_curation.py" in cmd
    assert "-hap1" in cmd
    assert "-hap2" not in cmd
    assert str(tmp_path / "microchromosome_second_shot" / "untracked") in cmd


@patch("grit.steps.pre_curation.microchromosome_second_shot._run")
def test_run_microchromosome_second_shot_hap1_and_hap2(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "bColMon1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    (tmp_path / "bColMon1.hap1.primary.curated.fa").write_text(">seq\n")
    (tmp_path / "bColMon1.hap1.primary.chromosome.list.csv").write_text("")
    (tmp_path / "bColMon1.hap2.primary.curated.fa").write_text(">seq\n")
    (tmp_path / "bColMon1.hap2.primary.chromosome.list.csv").write_text("")

    run_microchromosome_second_shot(mock_ctx)

    cmd = mock_run.call_args[0][0]
    assert "-hap2" in cmd
    assert "bColMon1.hap2.primary.curated.fa" in cmd
    assert "bColMon1.hap1.primary.curated.fa" in cmd


def test_second_shot_output_specs_include_merged_small_fa():
    from grit.steps.pre_curation.microchromosome_second_shot import _OUTPUT_SPECS

    keys = [key for key, _pattern, _excludes in _OUTPUT_SPECS]
    assert "merged_small_fa" in keys
    assert "hap1_large_fa" in keys


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
    second_shot_dir.mkdir(parents=True)
    (second_shot_dir / "bColMon1_curated_small_merged.fa").write_text(">seq\n")
    (second_shot_dir / "bColMon1.hap1.large.fa").write_text(">seq\n")
    (second_shot_dir / "bColMon1.hap1.large.chr_list.csv").write_text("")
    (second_shot_dir / "bColMon1.agp").write_text("")

    run_microchromosome_combine(mock_ctx)

    # pretext-to-asm ran once, over the merged small FASTA + micro AGP
    mock_pta_run.assert_called_once()
    pta_cmd = mock_pta_run.call_args[0][0]
    assert "pretext-to-asm" in pta_cmd
    assert "bColMon1_curated_small_merged.fa" in pta_cmd
    assert str(second_shot_dir / "bColMon1.agp") in pta_cmd

    # combine_curated_micros.py ran once, for hap1 only (no hap2 large fa present)
    mock_combine_run.assert_called_once()
    combine_cmd = mock_combine_run.call_args[0][0]
    assert "combine_curated_micros.py" in combine_cmd
    assert str(second_shot_dir / "bColMon1.hap1.large.fa") in combine_cmd


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
    second_shot_dir.mkdir(parents=True)
    (second_shot_dir / "bColMon1_curated_small_merged.fa").write_text(">seq\n")
    (second_shot_dir / "bColMon1.hap1.large.fa").write_text(">seq\n")
    (second_shot_dir / "bColMon1.hap1.large.chr_list.csv").write_text("")
    (second_shot_dir / "bColMon1.hap2.large.fa").write_text(">seq\n")
    (second_shot_dir / "bColMon1.hap2.large.chr_list.csv").write_text("")
    (second_shot_dir / "bColMon1.agp").write_text("")

    run_microchromosome_combine(mock_ctx)

    assert mock_combine_run.call_count == 2
    cmds = [call[0][0] for call in mock_combine_run.call_args_list]
    assert any(str(second_shot_dir / "bColMon1.hap1.large.fa") in c for c in cmds)
    assert any(str(second_shot_dir / "bColMon1.hap2.large.fa") in c for c in cmds)


def test_combine_output_specs_use_literal_hap_tokens():
    from grit.steps.post_curation.microchromosome_combine import _OUTPUT_SPECS

    keys = [key for key, _pattern, _excludes in _OUTPUT_SPECS]
    assert "hap1_fa" in keys
    assert "hap2_fa" in keys
