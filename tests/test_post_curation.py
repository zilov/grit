"""Tests for post_curation steps."""

from pathlib import Path
from unittest.mock import patch

import pytest

from grit.steps.post_curation import (
    finalize_for_qc,
    run_haplotig_files,
    run_hic_remapping,
    run_pretext_to_asm,
    run_qv,
    validate_curated_files,
)

# ---------------------------------------------------------------------------
# collect_outputs
# ---------------------------------------------------------------------------


def test_collect_outputs_basic(tmp_path):
    """collect_outputs globs for files and returns {key: path_str} dict."""
    from grit.utils.helpers import collect_outputs

    tol_id = "xbTest1"
    fa = tmp_path / f"{tol_id}.hap1.1.curated.fa"
    fa.write_text("")

    specs = [
        ("hap1_fa", "{tol_id}.{hap1}.*.curated.fa", ["all_haplotigs", "additional_haplotigs"]),
    ]
    result = collect_outputs(specs, tmp_path, tol_id, hap1="hap1", hap2="hap2")
    assert result == {"hap1_fa": str(fa)}


def test_collect_outputs_excludes(tmp_path):
    """collect_outputs skips files that contain an exclude keyword."""
    from grit.utils.helpers import collect_outputs

    tol_id = "xbTest1"
    haplo = tmp_path / f"{tol_id}.hap1.1.all_haplotigs.curated.fa"
    haplo.write_text("")

    specs = [
        ("hap1_fa", "{tol_id}.{hap1}.*.curated.fa", ["all_haplotigs", "additional_haplotigs"]),
    ]
    result = collect_outputs(specs, tmp_path, tol_id, hap1="hap1", hap2="hap2")
    assert result == {}


def test_collect_outputs_fallback(tmp_path):
    """collect_outputs falls back to later spec when earlier key not matched."""
    from grit.utils.helpers import collect_outputs

    tol_id = "xbTest1"
    primary = tmp_path / f"{tol_id}.1.primary.curated.fa"
    primary.write_text("")

    specs = [
        ("hap1_fa", "{tol_id}.{hap1}.*.curated.fa", ["all_haplotigs", "additional_haplotigs"]),
        ("hap1_fa", "{tol_id}.*.primary.curated.fa", ["hap1", "hap2", "all_haplotigs", "additional_haplotigs"]),
    ]
    result = collect_outputs(specs, tmp_path, tol_id, hap1="hap1", hap2="hap2")
    assert result == {"hap1_fa": str(primary)}


def test_collect_outputs_fallback_skipped_when_already_found(tmp_path):
    """collect_outputs skips later specs for a key already found."""
    from grit.utils.helpers import collect_outputs

    tol_id = "xbTest1"
    hap1_fa = tmp_path / f"{tol_id}.hap1.1.curated.fa"
    hap1_fa.write_text("")
    primary = tmp_path / f"{tol_id}.1.primary.curated.fa"
    primary.write_text("")

    specs = [
        ("hap1_fa", "{tol_id}.{hap1}.*.curated.fa", ["all_haplotigs", "additional_haplotigs"]),
        ("hap1_fa", "{tol_id}.*.primary.curated.fa", ["hap1", "hap2", "all_haplotigs", "additional_haplotigs"]),
    ]
    result = collect_outputs(specs, tmp_path, tol_id, hap1="hap1", hap2="hap2")
    assert result == {"hap1_fa": str(hap1_fa)}


# ---------------------------------------------------------------------------
# run_pretext_to_asm
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_builds_correct_command(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"

    # create original.fa so existence check passes
    (tmp_path / "original.fa").write_text("")

    agp = str(tmp_path / "sDipInt39.agp")
    mock_glob.return_value = [agp]
    mock_run.return_value = ""

    run_pretext_to_asm(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("pretext-to-asm" in c for c in calls)
    assert any("original.fa" in c for c in calls)
    assert any(agp in c for c in calls)


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob", return_value=[])
def test_run_pretext_to_asm_raises_when_no_agp(mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    (tmp_path / "original.fa").write_text("")

    with pytest.raises(FileNotFoundError, match="AGP file"):
        run_pretext_to_asm(mock_ctx)


def test_run_pretext_to_asm_raises_when_no_original_fa(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    # original.fa does NOT exist

    with pytest.raises(FileNotFoundError, match="original.fa"):
        run_pretext_to_asm(mock_ctx)


@patch("grit.steps.post_curation.pretext_to_asm._run")
def test_run_pretext_to_asm_print_only_skips_checks(mock_run, mock_ctx, tmp_path):
    """In print_only mode no filesystem checks should occur."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.print_only = True
    mock_run.return_value = ""

    # Should not raise even though files don't exist
    run_pretext_to_asm(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("pretext-to-asm" in c for c in calls)


# ---------------------------------------------------------------------------
# run_haplotig_files
# ---------------------------------------------------------------------------


def test_run_haplotig_files_creates_empty_for_hap1(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.assembly_type = "hap1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.release_version = 1

    run_haplotig_files(mock_ctx)

    expected = tmp_path / "sDipInt39.hap1.1.all_haplotigs.curated.fa"
    assert expected.exists()
    assert expected.stat().st_size == 0


def test_run_haplotig_files_creates_empty_for_primary(mock_ctx_primary, tmp_path):
    mock_ctx_primary.workdir = tmp_path
    mock_ctx_primary.tol_id = "ilHelSara1"
    mock_ctx_primary.assembly_type = "primary"
    mock_ctx_primary.release_version = 1

    run_haplotig_files(mock_ctx_primary)

    expected = tmp_path / "ilHelSara1.1.all_haplotigs.curated.fa"
    assert expected.exists()


def test_run_haplotig_files_nonempty_does_not_overwrite(mock_ctx, tmp_path):
    """A non-empty haplotig file must not be touched / zeroed out."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.assembly_type = "hap1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.release_version = 1

    existing = tmp_path / "sDipInt39.hap1.1.all_haplotigs.curated.fa"
    existing.write_text("ACGT" * 50)  # non-empty (>10 bytes)

    run_haplotig_files(mock_ctx)

    assert existing.read_text() == "ACGT" * 50  # unchanged


def test_run_haplotig_files_print_only(mock_ctx, tmp_path):
    """Print-only mode must not create any files."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.assembly_type = "hap1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.release_version = 1
    mock_ctx.print_only = True

    run_haplotig_files(mock_ctx)

    created = list(tmp_path.glob("*.fa"))
    assert created == []


# ---------------------------------------------------------------------------
# run_hic_remapping
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_submits_command(mock_find_fa, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""

    hap1_fa = tmp_path / "sDipInt39.1.hap1.primary.curated.fa"
    mock_find_fa.return_value = hap1_fa
    mock_run.return_value = ""

    run_hic_remapping(mock_ctx)

    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert "curationpretext.sh" in cmd
    assert str(hap1_fa) in cmd
    assert str(mock_ctx.hic_dir) in cmd


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_includes_teloseq(mock_find_fa, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = "--teloseq TTAGG"

    mock_find_fa.return_value = tmp_path / "sDipInt39.1.hap1.primary.curated.fa"
    mock_run.return_value = ""

    run_hic_remapping(mock_ctx)

    cmd = mock_run.call_args[0][0]
    assert "--teloseq TTAGG" in cmd


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_raises_when_no_fasta(mock_find_fa, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    mock_find_fa.side_effect = FileNotFoundError("No curated FASTA for 'hap1' found")

    with pytest.raises(FileNotFoundError):
        run_hic_remapping(mock_ctx)


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_hap2_submits_two_commands(mock_find_fa, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""

    hap1_fa = tmp_path / "sDipInt39.1.hap1.primary.curated.fa"
    hap2_fa = tmp_path / "sDipInt39.1.hap2.primary.curated.fa"
    mock_find_fa.side_effect = [hap1_fa, hap2_fa]
    mock_run.return_value = ""

    run_hic_remapping(mock_ctx, run_hap2=True)

    assert mock_run.call_count == 2
    cmds = [call[0][0] for call in mock_run.call_args_list]
    assert any(str(hap1_fa) in cmd for cmd in cmds)
    assert any(str(hap2_fa) in cmd for cmd in cmds)


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_assembly_override_bypasses_find_canonical(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """--assembly is used directly for hap1; find_canonical_fa must NOT be called."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""
    mock_run.return_value = ""

    custom_fa = Path("/custom/my_assembly.fa")
    run_hic_remapping(mock_ctx, assembly=custom_fa)

    mock_find_fa.assert_not_called()
    cmd = mock_run.call_args[0][0]
    assert str(custom_fa) in cmd


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_hic_dir_override(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """--hic-dir replaces ctx.hic_dir in the submitted command."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic_original")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""
    mock_find_fa.return_value = tmp_path / "sDipInt39.hap1.primary.curated.fa"
    mock_run.return_value = ""

    override_hic = Path("/custom/hic_dir")
    run_hic_remapping(mock_ctx, hic_dir=override_hic)

    cmd = mock_run.call_args[0][0]
    assert str(override_hic) in cmd
    assert "/lustre/hic_original" not in cmd


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_ont_dir_sets_read_type(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """--ont-dir overrides long_reads_dir and forces read_type=ont."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""
    mock_find_fa.return_value = tmp_path / "sDipInt39.hap1.primary.curated.fa"
    mock_run.return_value = ""

    ont_path = Path("/custom/ont_dir")
    run_hic_remapping(mock_ctx, ont_dir=ont_path)

    cmd = mock_run.call_args[0][0]
    assert str(ont_path) in cmd
    assert "--read_type ont" in cmd


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_hifi_dir_override(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """--hifi-dir replaces long_reads_dir; read_type stays hifi."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio_original")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""
    mock_find_fa.return_value = tmp_path / "sDipInt39.hap1.primary.curated.fa"
    mock_run.return_value = ""

    hifi_path = Path("/custom/hifi_dir")
    run_hic_remapping(mock_ctx, hifi_dir=hifi_path)

    cmd = mock_run.call_args[0][0]
    assert str(hifi_path) in cmd
    assert "/lustre/pacbio_original" not in cmd
    assert "--read_type hifi" in cmd


# ---------------------------------------------------------------------------
# run_qv
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.qv._submit_bsub")
def test_run_qv_submits_bsub(mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_bsub.return_value = "99999"

    run_qv(mock_ctx)

    assert mock_bsub.called
    inner_cmd = mock_bsub.call_args[0][0]
    assert "kmer_completeness.bash" in inner_cmd
    assert "sDipInt39" in inner_cmd
    assert "1" in inner_cmd


@patch("grit.steps.post_curation.qv._submit_bsub")
def test_run_qv_print_only(mock_bsub, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.print_only = True
    mock_bsub.return_value = ""

    run_qv(mock_ctx)

    # bsub should still be called (it respects print_only internally)
    assert mock_bsub.called


# ---------------------------------------------------------------------------
# validate_curated_files
# ---------------------------------------------------------------------------


def test_validate_curated_files_print_only(mock_ctx, tmp_path):
    """In print_only mode, function must not raise even with no files present."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated"
    mock_ctx.print_only = True

    validate_curated_files(mock_ctx)  # should not raise


def test_validate_curated_files_parses_log(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated"

    log = tmp_path / "sDipInt39.log"
    log.write_text("Curation made 3 break 2 join 1 cut in session\n")

    validate_curated_files(mock_ctx)  # should not raise


def test_validate_curated_files_warns_on_missing_log(mock_ctx, tmp_path, capsys):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated"
    # no log file created

    validate_curated_files(mock_ctx)  # should not raise


# ---------------------------------------------------------------------------
# finalize_for_qc
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.qv._submit_bsub")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_creates_curated_dir(
    mock_find_fa, mock_find_haplotigs, mock_find_csv, mock_glob, mock_run, mock_bsub, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")

    curated_fa = tmp_path / "sDipInt39.1.hap1.primary.curated.fa"
    chr_list = tmp_path / "sDipInt39.1.hap1.chromosome.list.csv"
    haplotig = tmp_path / "sDipInt39.1.haplotigs.fa"
    remapped = str(
        tmp_path / "sDipInt39_curationpretext/pretext_maps_processed/sDipInt39_normal.pretext"
    )

    mock_find_fa.return_value = curated_fa
    mock_find_csv.return_value = chr_list
    # hap1 haplotig found; hap2 raises → touch
    mock_find_haplotigs.side_effect = [haplotig, FileNotFoundError("no haplotigs for hap2")]
    # glob calls: nfs_first_level, hap1 remapped pretext
    mock_glob.side_effect = [[], [remapped]]
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("mkdir" in c for c in calls)
    assert any(str(curated_fa) in c for c in calls)
    assert any(str(chr_list) in c for c in calls)
    assert any(str(haplotig) in c for c in calls)
    # hap2 haplotigs not found — empty file created
    assert any("touch" in c and "hap2" in c and "all_haplotigs" in c for c in calls)


@patch("grit.steps.post_curation.finalize_qc._run")
def test_finalize_for_qc_print_only(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")
    mock_ctx.print_only = True
    mock_run.return_value = ""

    # Should not raise, just print commands
    finalize_for_qc(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("mkdir" in c for c in calls)


@patch("grit.steps.post_curation.qv._submit_bsub")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_assembly_override(
    mock_find_fa, mock_find_haplotigs, mock_find_csv, mock_glob, mock_run, mock_bsub, mock_ctx, tmp_path
):
    """--hap1-assembly bypasses find_canonical_fa for hap1."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.assembly_curated_dir = tmp_path / "curated"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")

    custom_fa = Path("/custom/sDipInt39.hap1.renamed.fa")
    mock_find_csv.return_value = tmp_path / "chr.list.csv"
    mock_find_haplotigs.side_effect = FileNotFoundError("no haplotigs")
    mock_glob.side_effect = [[], []]  # nfs, remapped
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx, hap1_assembly=custom_fa)

    mock_find_fa.assert_called_once_with(mock_ctx, "hap2")  # hap1 skipped
    calls = [str(c) for c in mock_run.call_args_list]
    assert any(str(custom_fa) in c for c in calls)


@patch("grit.steps.post_curation.qv._submit_bsub")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_hap2_map_copied_when_provided(
    mock_find_fa, mock_find_haplotigs, mock_find_csv, mock_glob, mock_run, mock_bsub, mock_ctx, tmp_path
):
    """--hap2-map triggers a second pretext map copy to NFS."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.assembly_curated_dir = tmp_path / "curated"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")

    hap1_pretext = Path("/hic/hap1_normal.pretext")
    hap2_pretext = Path("/hic/hap2_normal.pretext")

    mock_find_fa.side_effect = FileNotFoundError("no fa")
    mock_find_csv.side_effect = FileNotFoundError("no csv")
    mock_find_haplotigs.side_effect = FileNotFoundError("no haplotigs")
    mock_glob.side_effect = [[], [str(hap1_pretext)]]  # nfs, hap1 remapped
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx, hap1_map=hap1_pretext, hap2_map=hap2_pretext)

    calls = [str(c) for c in mock_run.call_args_list]
    hap1_dest = "sDipInt39.1.hap1.curated.pretext"
    hap2_dest = "sDipInt39.1.hap2.curated.pretext"
    assert any(hap1_dest in c for c in calls)
    assert any(hap2_dest in c for c in calls)


@patch("grit.steps.post_curation.qv._submit_bsub")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_primary_alternate_assembly_single_hap_output(
    mock_find_fa, mock_find_haplotigs, mock_find_csv, mock_glob, mock_run, mock_bsub, mock_ctx, tmp_path
):
    """primary/alternate assemblies: only hap1 files copied, no hap prefix in dest names."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "ilScoBasi3"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "primary"
    mock_ctx.hap2_prefix = "alternate"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "ilScoBasi3.1"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")

    hap1_fa = tmp_path / "ilScoBasi3.hap1.1.primary.curated.fa"
    chr_list = tmp_path / "ilScoBasi3.hap1.1.primary.chromosome.list.csv"
    haplotig = tmp_path / "ilScoBasi3.1.haplotigs.fa"

    mock_find_fa.return_value = hap1_fa
    mock_find_csv.return_value = chr_list
    mock_find_haplotigs.return_value = haplotig
    mock_glob.side_effect = [[], []]  # nfs, no remapped pretext
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    # Dest filenames: no hap prefix — {tol_id}.{version}.{type}
    assert any("ilScoBasi3.1.primary.curated.fa" in c for c in calls)
    assert any("ilScoBasi3.1.all_haplotigs.curated.fa" in c for c in calls)
    assert any("ilScoBasi3.1.primary.chromosome.list.csv" in c for c in calls)
    # hap2/alternate files must NOT be copied
    assert not any("hap2" in c for c in calls), "hap2 file copied for primary/alternate assembly"
    assert not any("alternate" in c for c in calls), "'alternate' must not appear anywhere"
    assert not any("primary.1.primary" in c for c in calls), "double-primary in dest name"
    # find_canonical helpers called once (only for hap1), not twice
    assert mock_find_fa.call_count == 1
    assert mock_find_haplotigs.call_count == 1
    assert mock_find_csv.call_count == 1
