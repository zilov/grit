"""Tests that ctx.bsub_ram overrides each bsub step's default LSF memory limit."""

from unittest.mock import patch

from grit.steps.optional.busco_curated import run_busco_curated
from grit.steps.optional.busco_synteny import run_busco_synteny
from grit.steps.optional.fastga import run_fastga
from grit.steps.optional.rename_and_orient import run_rename_and_orient
from grit.steps.pre_curation.sex_matcher import run_sex_matcher


@patch("grit.steps.optional.fastga._submit_bsub")
@patch("grit.steps.optional.fastga.find_canonical_fa")
def test_fastga_default_memory(mock_find_fa, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = True
    mock_find_fa.return_value = tmp_path / "sDipInt39.hap1.primary.curated.fa"
    mock_bsub.return_value = "12345"

    run_fastga(mock_ctx, reference_path=str(tmp_path / "ref.fna"))

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 24000" in bsub_opts


@patch("grit.steps.optional.fastga._submit_bsub")
@patch("grit.steps.optional.fastga.find_canonical_fa")
def test_fastga_bsub_ram_override(mock_find_fa, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = True
    mock_ctx.bsub_ram = 64000
    mock_find_fa.return_value = tmp_path / "sDipInt39.hap1.primary.curated.fa"
    mock_bsub.return_value = "12345"

    run_fastga(mock_ctx, reference_path=str(tmp_path / "ref.fna"))

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 64000" in bsub_opts


@patch("grit.steps.optional.busco_synteny._submit_bsub")
@patch("grit.steps.optional.busco_synteny.find_canonical_fa")
@patch("grit.steps.optional.busco_synteny.find_reheadered_reference")
def test_busco_synteny_default_memory(mock_find_ref, mock_find_fa, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.print_only = True
    mock_find_ref.return_value = tmp_path / "ref_reheader.fna"
    mock_find_fa.return_value = tmp_path / "sDipInt39.hap1.primary.curated.fa"
    mock_bsub.return_value = "12345"

    run_busco_synteny(mock_ctx, "insecta_odb10")

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 70000" in bsub_opts


@patch("grit.steps.optional.busco_synteny._submit_bsub")
@patch("grit.steps.optional.busco_synteny.find_canonical_fa")
@patch("grit.steps.optional.busco_synteny.find_reheadered_reference")
def test_busco_synteny_bsub_ram_override(
    mock_find_ref, mock_find_fa, mock_bsub, mock_ctx, tmp_path
):
    mock_ctx.print_only = True
    mock_ctx.bsub_ram = 90000
    mock_find_ref.return_value = tmp_path / "ref_reheader.fna"
    mock_find_fa.return_value = tmp_path / "sDipInt39.hap1.primary.curated.fa"
    mock_bsub.return_value = "12345"

    run_busco_synteny(mock_ctx, "insecta_odb10")

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 90000" in bsub_opts


@patch("grit.steps.optional.busco_curated._submit_bsub")
def test_busco_curated_default_memory_auto_scaled(mock_bsub, mock_ctx):
    """< 1GB example FASTA in print_only mode auto-scales to 50000."""
    mock_ctx.print_only = True
    mock_bsub.return_value = "12345"

    run_busco_curated(mock_ctx, "insecta_odb10")

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 150000" in bsub_opts  # print_only stub file_size_gb=2.5 → 150000


@patch("grit.steps.optional.busco_curated._submit_bsub")
def test_busco_curated_bsub_ram_override(mock_bsub, mock_ctx):
    mock_ctx.print_only = True
    mock_ctx.bsub_ram = 300000
    mock_bsub.return_value = "12345"

    run_busco_curated(mock_ctx, "insecta_odb10")

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 300000" in bsub_opts


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_rename_and_orient_default_memory(mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False
    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    mock_glob.return_value = [str(tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf")]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx)

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 60000" in bsub_opts


@patch("grit.steps.optional.rename_and_orient._submit_bsub")
@patch("grit.steps.optional.rename_and_orient.glob.glob")
@patch("grit.steps.optional.rename_and_orient.find_canonical_fa")
def test_rename_and_orient_bsub_ram_override(
    mock_find_fa, mock_glob, mock_bsub, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False
    mock_ctx.bsub_ram = 100000
    mock_find_fa.return_value = tmp_path / "workdir" / "sDipInt39.hap1.primary.curated.fa"
    mock_glob.return_value = [str(tmp_path / "workdir" / "fastga" / "sDipInt39_vs_ref.FastGA.paf")]
    mock_bsub.return_value = "12345"

    run_rename_and_orient(mock_ctx)

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 100000" in bsub_opts


@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_sex_matcher_default_memory(mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "icAedAegy1"  # must match an insect prefix
    mock_ctx.print_only = True
    mock_bsub.return_value = "12345"

    run_sex_matcher(mock_ctx)

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 80000" in bsub_opts


@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_sex_matcher_bsub_ram_override(mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.tol_id = "icAedAegy1"
    mock_ctx.print_only = True
    mock_ctx.bsub_ram = 120000
    mock_bsub.return_value = "12345"

    run_sex_matcher(mock_ctx)

    bsub_opts = mock_bsub.call_args[0][1]
    assert "-M 120000" in bsub_opts
