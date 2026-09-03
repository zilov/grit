"""Tests for the redesigned blast_contaminants step (writes a distinct output file,
never mutates the original pretext_to_asm curated FASTA)."""

import re
from pathlib import Path
from unittest.mock import patch

import pytest

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.optional.blast_contaminants import run_blast_contaminants


def _attach_tracker(ctx, tmp_path):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)


def _fake_find_canonical_fa(tmp_path, header=">SCAFFOLD_1"):
    def _fake(ctx, hap_prefix):
        p = tmp_path / f"{ctx.tol_id}.{hap_prefix}.1.curated.fa"
        p.write_text(f"{header}\n")
        return p

    return _fake


def _write_cleaned_fasta(tmp_path, tol_id, hap_prefix):
    curated = tmp_path / f"{tol_id}.{hap_prefix}.1.curated.fa"
    curated.with_name(curated.name + "_cleaned").write_text(">seq\n")


_MKDIR_RE = re.compile(r"^mkdir -p (\S+)$")
_BED_RE = re.compile(r"^grep -v \S+ \S+ \| perl -anE '.*' >> (\S+)$")


def _fake_run_finds_contaminants(cmd, print_only=False):
    """Emulate mkdir -p and the bed-generation shell command writing a non-empty
    contaminated.bed, as if decon_fasta's taxonomy.txt contained at least one
    non-target-phylum hit."""
    mkdir_match = _MKDIR_RE.match(cmd)
    if mkdir_match:
        Path(mkdir_match.group(1)).mkdir(parents=True, exist_ok=True)
        return ""
    bed_match = _BED_RE.match(cmd)
    if bed_match:
        Path(bed_match.group(1)).write_text("SCAFFOLD_1\t0\t10000\tREMOVE\n")
        return ""
    return ""


def _fake_run_no_contaminants(cmd, print_only=False):
    """Emulate mkdir -p and the bed-generation shell command producing an empty
    contaminated.bed, as if every hit in decon_fasta's taxonomy.txt matched the
    target phylum."""
    mkdir_match = _MKDIR_RE.match(cmd)
    if mkdir_match:
        Path(mkdir_match.group(1)).mkdir(parents=True, exist_ok=True)
        return ""
    bed_match = _BED_RE.match(cmd)
    if bed_match:
        Path(bed_match.group(1)).touch()
        return ""
    return ""


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_finds_contaminants)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_processes_both_haplotypes(mock_find_fa, mock_run, mock_ctx, tmp_path):
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap1_prefix)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap2_prefix)

    run_blast_contaminants(mock_ctx)

    outputs = mock_ctx.tracker.history("blast_contaminants")[-1]["outputs"]
    assert set(outputs) == {f"{mock_ctx.hap1_prefix}_fa", f"{mock_ctx.hap2_prefix}_fa"}
    for hap in (mock_ctx.hap1_prefix, mock_ctx.hap2_prefix):
        expected_suffix = f"{mock_ctx.tol_id}.{hap}.{mock_ctx.release_version}.decontaminated.fa"
        assert outputs[f"{hap}_fa"].endswith(expected_suffix)


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_finds_contaminants)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_single_hap_processes_only_primary(mock_find_fa, mock_run, mock_ctx_primary, tmp_path):
    _attach_tracker(mock_ctx_primary, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx_primary.tol_id, mock_ctx_primary.hap1_prefix)

    run_blast_contaminants(mock_ctx_primary)

    outputs = mock_ctx_primary.tracker.history("blast_contaminants")[-1]["outputs"]
    assert set(outputs) == {f"{mock_ctx_primary.hap1_prefix}_fa"}


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_finds_contaminants)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_never_moves_original_curated_fasta(mock_find_fa, mock_run, mock_ctx, tmp_path):
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap1_prefix)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap2_prefix)

    run_blast_contaminants(mock_ctx)

    mv_calls = [str(c) for c in mock_run.call_args_list if "mv " in str(c)]
    assert mv_calls
    assert all("_cleaned" in c for c in mv_calls)


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_finds_contaminants)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_output_survives_untrack_fallback(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """Untracking blast_contaminants must not lose the original curated FASTA —
    find_canonical_fa should fall back to it since it was never touched."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path)
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


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_no_contaminants)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_no_contaminants_leaves_canonical_untouched(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """When every taxonomy.txt hit matches the target phylum, no decontaminated
    FASTA is written and the haplotype's canonical output is left alone."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap1_prefix)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap2_prefix)

    run_blast_contaminants(mock_ctx)

    mv_calls = [str(c) for c in mock_run.call_args_list if "mv " in str(c)]
    assert not mv_calls
    outputs = mock_ctx.tracker.history("blast_contaminants")[-1].get("outputs")
    assert not outputs


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_finds_contaminants)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_missing_cleaned_fasta_raises_instead_of_silently_tracking(
    mock_find_fa, mock_run, mock_ctx, tmp_path
):
    """If remove_contamination_bed doesn't produce the expected *_cleaned FASTA
    (e.g. a tool failure), the step must fail loudly instead of tracking a
    'success' output that points at a file that was never created."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path)
    # Deliberately skip _write_cleaned_fasta — no *_cleaned file will exist.

    with pytest.raises(RuntimeError, match="did not produce"):
        run_blast_contaminants(mock_ctx)

    last_run = mock_ctx.tracker.history("blast_contaminants")[-1]
    assert last_run["status"] == "failed"


@patch("grit.steps.optional.blast_contaminants._run")
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_dry_run_short_circuits_before_any_real_work(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """dry_run must skip the lineage/decon_fasta pipeline entirely —
    no _run() call and no dependency on find_canonical_fa."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_blast_contaminants(mock_ctx)

    mock_run.assert_not_called()
    mock_find_fa.assert_not_called()

    outputs = mock_ctx.tracker.history("blast_contaminants")[-1]["outputs"]
    assert set(outputs) == {f"{mock_ctx.hap1_prefix}_fa", f"{mock_ctx.hap2_prefix}_fa"}
    for hap in (mock_ctx.hap1_prefix, mock_ctx.hap2_prefix):
        path = mock_ctx.tracker.get_output("blast_contaminants", f"{hap}_fa")
        assert path is not None
        assert Path(path).exists()


@patch("grit.steps.optional.blast_contaminants._run")
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_dry_run_single_hap_tracks_only_hap1(mock_find_fa, mock_run, mock_ctx_primary, tmp_path):
    """A single-hap (primary/alternate) dry run must only ever track hap1's fake
    output — never a hap2/alternate output that the real workflow could never
    produce for this assembly."""
    _attach_tracker(mock_ctx_primary, tmp_path)
    mock_ctx_primary.dry_run = True

    run_blast_contaminants(mock_ctx_primary)

    mock_run.assert_not_called()
    mock_find_fa.assert_not_called()

    last_run = mock_ctx_primary.tracker.history("blast_contaminants")[-1]
    outputs = last_run["outputs"]
    assert set(outputs) == {"hap1_fa"}

    # Popping the tracker key isn't enough — a leftover file would still be
    # findable by any glob-based (not tracker-based) hap2 detection downstream.
    run_dir = last_run["run_dir"]
    assert list(Path(run_dir).glob("*.hap2.*")) == []
    assert list(Path(run_dir).glob("*.alternate.*")) == []
    assert "hap2_fa" not in outputs
    assert mock_ctx_primary.tracker.get_output("blast_contaminants", "alternate_fa") is None
    assert mock_ctx_primary.tracker.get_output("blast_contaminants", "hap2_fa") is None


@patch("grit.steps.optional.blast_contaminants._run")
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_dry_run_single_hap_leaves_no_alternate_hap_dir(
    mock_find_fa, mock_run, mock_ctx_primary, tmp_path
):
    """blast-contaminants groups its outputs into one directory per haplotype, and
    the real single-hap path never creates the second one — so the dry run must not
    leave an empty alternate/ behind after deleting its fake file."""
    _attach_tracker(mock_ctx_primary, tmp_path)
    mock_ctx_primary.dry_run = True

    run_blast_contaminants(mock_ctx_primary)

    run_dir = Path(mock_ctx_primary.tracker.history("blast_contaminants")[-1]["run_dir"])
    assert [d.name for d in run_dir.iterdir() if d.is_dir()] == [mock_ctx_primary.hap1_prefix]


def test_dry_run_output_resolves_via_find_canonical_fa(mock_ctx, tmp_path):
    """The fake output written in dry-run mode must resolve through the real
    canonical-FASTA resolution pool, not just via tracker bookkeeping."""
    from grit.utils.helpers import find_canonical_fa

    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_blast_contaminants(mock_ctx)

    expected = Path(mock_ctx.tracker.get_output("blast_contaminants", f"{mock_ctx.hap1_prefix}_fa"))
    resolved = find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix)
    assert resolved == expected
