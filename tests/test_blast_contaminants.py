"""Tests for the redesigned blast_contaminants step (writes a distinct output file,
never mutates the original pretext_to_asm curated FASTA)."""

from unittest.mock import patch

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.optional.blast_contaminants import run_blast_contaminants


def _attach_tracker(ctx, tmp_path):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)


def _fake_find_curated_fa(tmp_path):
    def _fake(ctx, hap_prefix):
        p = tmp_path / f"{ctx.tol_id}.{hap_prefix}.1.curated.fa"
        p.write_text(">seq\n")
        return p

    return _fake


def _write_cleaned_fasta(tmp_path, tol_id, hap_prefix):
    (tmp_path / f"{tol_id}.{hap_prefix}.1.curated.fa").with_suffix(".cleaned.fa").write_text(
        ">seq\n"
    )


@patch("grit.steps.optional.blast_contaminants._run", return_value="")
@patch("grit.steps.optional.blast_contaminants.find_curated_fa")
def test_processes_both_haplotypes(mock_find_fa, mock_run, mock_ctx, tmp_path):
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_curated_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap1_prefix)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap2_prefix)

    run_blast_contaminants(mock_ctx)

    outputs = mock_ctx.tracker.history("blast_contaminants")[-1]["outputs"]
    assert set(outputs) == {f"{mock_ctx.hap1_prefix}_fa", f"{mock_ctx.hap2_prefix}_fa"}
    for hap in (mock_ctx.hap1_prefix, mock_ctx.hap2_prefix):
        expected_suffix = f"{mock_ctx.tol_id}.{hap}.{mock_ctx.release_version}.decontaminated.fa"
        assert outputs[f"{hap}_fa"].endswith(expected_suffix)


@patch("grit.steps.optional.blast_contaminants._run", return_value="")
@patch("grit.steps.optional.blast_contaminants.find_curated_fa")
def test_single_hap_processes_only_primary(mock_find_fa, mock_run, mock_ctx_primary, tmp_path):
    _attach_tracker(mock_ctx_primary, tmp_path)
    mock_find_fa.side_effect = _fake_find_curated_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx_primary.tol_id, mock_ctx_primary.hap1_prefix)

    run_blast_contaminants(mock_ctx_primary)

    outputs = mock_ctx_primary.tracker.history("blast_contaminants")[-1]["outputs"]
    assert set(outputs) == {f"{mock_ctx_primary.hap1_prefix}_fa"}


@patch("grit.steps.optional.blast_contaminants._run", return_value="")
@patch("grit.steps.optional.blast_contaminants.find_curated_fa")
def test_never_moves_original_curated_fasta(mock_find_fa, mock_run, mock_ctx, tmp_path):
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_curated_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap1_prefix)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap2_prefix)

    run_blast_contaminants(mock_ctx)

    mv_calls = [str(c) for c in mock_run.call_args_list if "mv " in str(c)]
    assert mv_calls
    assert all(".cleaned.fa" in c for c in mv_calls)


@patch("grit.steps.optional.blast_contaminants._run", return_value="")
@patch("grit.steps.optional.blast_contaminants.find_curated_fa")
def test_output_survives_untrack_fallback(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """Untracking blast_contaminants must not lose the original curated FASTA —
    find_canonical_fa should fall back to it since it was never touched."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_curated_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap1_prefix)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap2_prefix)

    run_blast_contaminants(mock_ctx)
    assert (
        mock_ctx.tracker.get_output("blast_contaminants", f"{mock_ctx.hap1_prefix}_fa") is not None
    )

    mock_ctx.tracker.untrack("blast_contaminants")
    assert mock_ctx.tracker.get_output("blast_contaminants", f"{mock_ctx.hap1_prefix}_fa") is None

    # The original pretext_to_asm curated FASTA is untouched on disk regardless.
    original = tmp_path / f"{mock_ctx.tol_id}.{mock_ctx.hap1_prefix}.1.curated.fa"
    assert original.exists()
