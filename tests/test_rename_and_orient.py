"""Tests for rename_and_orient step."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.optional.rename_and_orient import _OUTPUT_SPECS, run_rename_and_orient
from grit.utils.helpers import collect_outputs


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_run_rename_and_orient_submits_bsub(mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    curated_fa = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"

    mock_find_fa.return_value = curated_fa
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx)

    mock_bsub.assert_called_once()
    cmd = mock_bsub.call_args[0][0]
    assert "rename-and-orient" in cmd
    assert str(curated_fa) in cmd
    assert str(paf_file) in cmd
    assert "sDipInt39.hap1.primary.renamed" in cmd


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_run_rename_and_orient_print_only_mode(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """print_only resolves real PAF and FA paths, just doesn't execute the job."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = True

    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"

    run_rename_and_orient(mock_ctx)

    # print_only=True — bsub called but with print_only flag (prints, doesn't submit)
    mock_bsub.assert_called_once()
    assert mock_bsub.call_args[0][2] is True  # print_only argument


@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_run_rename_and_orient_raises_when_no_curated_fasta(mock_find_fa, mock_ctx):
    mock_ctx.workdir = Path("/fake/workdir")
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_find_fa.side_effect = FileNotFoundError("No curated FASTA for 'hap1' found")

    with pytest.raises(FileNotFoundError):
        run_rename_and_orient(mock_ctx)


@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_run_rename_and_orient_raises_when_no_paf(mock_find_fa, mock_glob, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    mock_glob.return_value = []

    with pytest.raises(FileNotFoundError, match="No FastGA PAF found"):
        run_rename_and_orient(mock_ctx)


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_run_rename_and_orient_hap2_waits_for_mapping_tsv(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """hap2 should not submit if hap1 mapping.tsv doesn't exist yet."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    # mapping.tsv does NOT exist — hap2 should be skipped
    run_rename_and_orient(mock_ctx, run_hap2=True)

    assert mock_bsub.call_count == 1  # only hap1 submitted


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_run_rename_and_orient_hap2_submits_when_mapping_tsv_exists(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """hap2 should submit when hap1 mapping.tsv is present."""
    hap1_run_dir = tmp_path / "workdir" / "rename_and_orient" / "2026-01-01T00_00_00"
    hap1_run_dir.mkdir(parents=True)
    mapping_tsv = hap1_run_dir / "sDipInt39.hap1.primary.renamed.mapping.tsv"
    mapping_tsv.touch()

    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx, run_hap2=True)

    assert mock_bsub.call_count == 2
    cmds = [call[0][0] for call in mock_bsub.call_args_list]
    assert any("--paf" in cmd for cmd in cmds)
    assert any("--mapping-table" in cmd for cmd in cmds)


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_run_rename_and_orient_uses_canonical_fa(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """Input FASTA comes from find_canonical_fa — whatever is currently canonical
    for this haplotype (pretext_to_asm, microchromosome_combine, blast_contaminants,
    or a recurate output) — not a hand-rolled lookup local to this step."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    canonical_fa = tmp_path / "sDipInt39.hap1.1.decontaminated.fa"
    canonical_fa.write_text(">seq\n")
    mock_find_fa.return_value = canonical_fa
    paf_file = tmp_path / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx)

    mock_find_fa.assert_called_once_with(mock_ctx, "hap1")
    cmd = mock_bsub.call_args[0][0]
    assert str(canonical_fa) in cmd


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_rerun_on_fresher_canonical_input_produces_new_tracked_output(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """A deliberate rerun (e.g. after a recurate round) must still call
    ctx.tracker.start and submit a job — the pre-tracker "already done"
    guard must not short-circuit the second submission."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    mock_tracker = MagicMock()
    mock_tracker.start.side_effect = [
        tmp_path / "workdir" / "rename_and_orient" / "run1",
        tmp_path / "workdir" / "rename_and_orient" / "run2",
    ]
    mock_ctx.tracker = mock_tracker

    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    first_canonical_fa = tmp_path / "workdir" / "sDipInt39.hap1.1.decontaminated.fa"
    second_canonical_fa = tmp_path / "workdir" / "sDipInt39.hap1.2.decontaminated.fa"
    mock_find_fa.side_effect = [first_canonical_fa, second_canonical_fa]

    run_rename_and_orient(mock_ctx)
    run_rename_and_orient(mock_ctx)

    assert mock_tracker.start.call_count == 2
    assert mock_bsub.call_count == 2
    cmds = [call[0][0] for call in mock_bsub.call_args_list]
    assert str(first_canonical_fa) in cmds[0]
    assert str(second_canonical_fa) in cmds[1]


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_tracked_output_resolves_after_successful_run(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """The bsub job writes its FASTA into --output-dir. Simulate that landing in
    the real run_dir (as the epilogue's collect_outputs() would see it) and
    confirm the tracker actually finds it — proving output-dir/run_dir no
    longer diverge."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(mock_ctx.workdir, registry=reg)

    canonical_fa = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    mock_find_fa.return_value = canonical_fa
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx)

    run_dir = mock_ctx.tracker.latest_run_dir("rename_and_orient")
    assert run_dir is not None

    # Simulate the external tool writing its output into --output-dir, which
    # is now run_dir itself rather than a shared flat directory.
    written_fa = run_dir / "sDipInt39.hap1.primary.renamed.fa"
    written_fa.write_text(">seq\n")

    outputs = collect_outputs(_OUTPUT_SPECS, run_dir, mock_ctx.tol_id)
    mock_ctx.tracker.finish("rename_and_orient", run_dir, "success", outputs=outputs)

    resolved = mock_ctx.tracker.get_output("rename_and_orient", "hap1_fa")
    assert resolved is not None
    assert Path(resolved).exists()
    assert Path(resolved) == written_fa


def _attach_tracker(ctx, tmp_path):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_dry_run_hap1_short_circuits_before_bsub(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """dry_run must skip the PAF lookup and never call _submit_bsub()."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_rename_and_orient(mock_ctx)

    mock_bsub.assert_not_called()
    mock_glob.assert_not_called()
    mock_find_fa.assert_not_called()

    output = mock_ctx.tracker.get_output("rename_and_orient", "hap1_fa")
    assert output is not None
    assert Path(output).exists()
    run_dir = mock_ctx.tracker.latest_run_dir("rename_and_orient")
    assert Path(output).parent == run_dir


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_dry_run_tracks_chr_list_output(mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path):
    """Regression: rename_and_orient's _OUTPUT_SPECS must include a chr_list
    key, or the tracker never records the chromosome-list file that the real
    tool writes, and find_canonical_chr_list can never select this step."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_rename_and_orient(mock_ctx, run_hap2=True)

    hap1_chr_list = mock_ctx.tracker.get_output("rename_and_orient", "hap1_chr_list")
    hap2_chr_list = mock_ctx.tracker.get_output("rename_and_orient_hap2", "hap2_chr_list")
    assert hap1_chr_list is not None
    assert hap2_chr_list is not None
    assert Path(hap1_chr_list).exists()
    assert Path(hap2_chr_list).exists()


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_tracked_chr_list_resolves_after_successful_run(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """Real (non-dry-run) run: simulate the external tool writing its
    chromosome-list CSV alongside the renamed FASTA in --output-dir, and
    confirm collect_outputs()/the tracker actually captures it."""
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.print_only = False

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(mock_ctx.workdir, registry=reg)

    canonical_fa = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    mock_find_fa.return_value = canonical_fa
    paf_file = tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf"
    mock_glob.return_value = [str(paf_file)]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx)

    run_dir = mock_ctx.tracker.latest_run_dir("rename_and_orient")
    assert run_dir is not None

    written_fa = run_dir / "sDipInt39.hap1.primary.renamed.fa"
    written_fa.write_text(">seq\n")
    written_chr_list = run_dir / "sDipInt39.hap1.primary.renamed.chromosome.list.csv"
    written_chr_list.write_text("chr,length\n1,100\n")

    outputs = collect_outputs(_OUTPUT_SPECS, run_dir, mock_ctx.tol_id)
    mock_ctx.tracker.finish("rename_and_orient", run_dir, "success", outputs=outputs)

    resolved = mock_ctx.tracker.get_output("rename_and_orient", "hap1_chr_list")
    assert resolved is not None
    assert Path(resolved) == written_chr_list


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_dry_run_hap2_writes_into_own_tracked_step(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    """run_hap2=True in dry_run must produce a second tracked output under
    rename_and_orient_hap2 without ever calling _submit_bsub()."""
    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_rename_and_orient(mock_ctx, run_hap2=True)

    mock_bsub.assert_not_called()

    hap1_output = mock_ctx.tracker.get_output("rename_and_orient", "hap1_fa")
    hap2_output = mock_ctx.tracker.get_output("rename_and_orient_hap2", "hap2_fa")
    assert hap1_output is not None
    assert hap2_output is not None
    assert Path(hap1_output).exists()
    assert Path(hap2_output).exists()


def test_dry_run_output_resolves_via_find_canonical_fa(mock_ctx, tmp_path):
    """The fake output written in dry-run mode must resolve through the real
    canonical-FASTA resolution pool, not just via tracker bookkeeping."""
    from grit.utils.helpers import find_canonical_fa

    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_rename_and_orient(mock_ctx)

    expected = Path(mock_ctx.tracker.get_output("rename_and_orient", "hap1_fa"))
    resolved = find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix)
    assert resolved == expected


def test_chained_dry_run_forward_chain_through_canonical_pool(mock_ctx, tmp_path):
    """Core scenario --dry-run exists to make testable without HPC: dry-run
    pretext_to_asm -> dry-run blast_contaminants -> canonical resolves to
    blast's output, not pretext_to_asm's -> dry-run rename_and_orient ->
    canonical resolves to rename's output."""
    from grit.steps.optional.blast_contaminants import run_blast_contaminants
    from grit.steps.post_curation.pretext_to_asm import run_pretext_to_asm
    from grit.utils.helpers import find_canonical_fa

    _attach_tracker(mock_ctx, tmp_path)
    mock_ctx.dry_run = True

    run_pretext_to_asm(mock_ctx)
    pretext_output = Path(mock_ctx.tracker.get_output("pretext_to_asm", "hap1_fa"))
    assert find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix) == pretext_output

    run_blast_contaminants(mock_ctx)
    blast_output = Path(
        mock_ctx.tracker.get_output("blast_contaminants", f"{mock_ctx.hap1_prefix}_fa")
    )
    assert blast_output != pretext_output
    assert find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix) == blast_output

    with patch("grit.steps.optional.rename_and_orient._submit_bsub") as mock_bsub:
        run_rename_and_orient(mock_ctx)
        mock_bsub.assert_not_called()

    rename_output = Path(mock_ctx.tracker.get_output("rename_and_orient", "hap1_fa"))
    assert rename_output != blast_output
    assert find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix) == rename_output
