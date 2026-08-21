"""Tests for the redesigned blast_contaminants step (writes a distinct output file,
never mutates the original pretext_to_asm curated FASTA)."""

import re
from pathlib import Path
from unittest.mock import patch

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
    (tmp_path / f"{tol_id}.{hap_prefix}.1.curated.fa").with_suffix(".cleaned.fa").write_text(
        ">seq\n"
    )


_EXTRACT_RE = re.compile(r"^perl -nE '.*' (\S+) >> (\S+)$")
_HEADER_RE = re.compile(r"^echo 'header' > (\S+)$")


def _fake_run_writes_blast_me(cmd, print_only=False):
    """Emulate the header/extract shell commands' effect on disk so the
    post-extraction SCAFFOLD-header check has real file content to read."""
    header_match = _HEADER_RE.match(cmd)
    if header_match:
        Path(header_match.group(1)).write_text("header\n")
        return ""

    extract_match = _EXTRACT_RE.match(cmd)
    if extract_match:
        fasta_path, blast_me_path = extract_match.groups()
        scaffold_re = re.compile(r"([HAP_\d]*SCAFFOLD_\d+)", re.IGNORECASE)
        matches = [m.group(1) for m in scaffold_re.finditer(Path(fasta_path).read_text())]
        with open(blast_me_path, "a") as f:
            for m in matches:
                f.write(f"true,{m}\n")
        return ""

    return ""


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_writes_blast_me)
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


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_writes_blast_me)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_single_hap_processes_only_primary(mock_find_fa, mock_run, mock_ctx_primary, tmp_path):
    _attach_tracker(mock_ctx_primary, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx_primary.tol_id, mock_ctx_primary.hap1_prefix)

    run_blast_contaminants(mock_ctx_primary)

    outputs = mock_ctx_primary.tracker.history("blast_contaminants")[-1]["outputs"]
    assert set(outputs) == {f"{mock_ctx_primary.hap1_prefix}_fa"}


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_writes_blast_me)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_never_moves_original_curated_fasta(mock_find_fa, mock_run, mock_ctx, tmp_path):
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap1_prefix)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap2_prefix)

    run_blast_contaminants(mock_ctx)

    mv_calls = [str(c) for c in mock_run.call_args_list if "mv " in str(c)]
    assert mv_calls
    assert all(".cleaned.fa" in c for c in mv_calls)


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_writes_blast_me)
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


@patch("grit.steps.optional.blast_contaminants._run", side_effect=_fake_run_writes_blast_me)
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_warns_and_continues_on_non_scaffold_headers(
    mock_find_fa, mock_run, mock_ctx, tmp_path, caplog
):
    """Chaining onto a rename_and_orient output (headers like 'chr1', not
    SCAFFOLD_N) must not crash — it should warn and still complete."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_find_fa.side_effect = _fake_find_canonical_fa(tmp_path, header=">chr1")
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap1_prefix)
    _write_cleaned_fasta(tmp_path, mock_ctx.tol_id, mock_ctx.hap2_prefix)

    with caplog.at_level("WARNING"):
        run_blast_contaminants(mock_ctx)

    assert "don't look like" in caplog.text or "SCAFFOLD" in caplog.text
    outputs = mock_ctx.tracker.history("blast_contaminants")[-1]["outputs"]
    assert set(outputs) == {f"{mock_ctx.hap1_prefix}_fa", f"{mock_ctx.hap2_prefix}_fa"}


@patch("grit.steps.optional.blast_contaminants._run")
@patch("grit.steps.optional.blast_contaminants.find_canonical_fa")
def test_dry_run_short_circuits_before_any_real_work(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """dry_run must skip the lineage/blast.me/decon_blastBTK pipeline entirely —
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
