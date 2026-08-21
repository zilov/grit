"""Tests for post_curation steps."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

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
        (
            "hap1_fa",
            "{tol_id}.*.primary.curated.fa",
            ["hap1", "hap2", "all_haplotigs", "additional_haplotigs"],
        ),
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
        (
            "hap1_fa",
            "{tol_id}.*.primary.curated.fa",
            ["hap1", "hap2", "all_haplotigs", "additional_haplotigs"],
        ),
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


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_dry_run_writes_fake_fasta_with_scaffold_headers(
    mock_glob, mock_run, mock_ctx, tmp_path
):
    """Dry-run must skip real AGP/subprocess work and write a fake curated FASTA
    with SCAFFOLD_ headers, tracked under the real _OUTPUT_SPECS keys."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.dry_run = True
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(tmp_path, registry=registry)

    run_pretext_to_asm(mock_ctx)

    mock_run.assert_not_called()
    mock_glob.assert_not_called()

    hap1_fa_path = mock_ctx.tracker.get_output("pretext_to_asm", "hap1_fa")
    assert hap1_fa_path is not None
    hap1_fa = Path(hap1_fa_path)
    assert hap1_fa.exists()
    content = hap1_fa.read_text()
    assert "SCAFFOLD_1" in content
    assert "SCAFFOLD_2" in content

    hap2_fa_path = mock_ctx.tracker.get_output("pretext_to_asm", "hap2_fa")
    assert hap2_fa_path is not None
    assert "HAP_SCAFFOLD_1" in Path(hap2_fa_path).read_text()


def test_run_pretext_to_asm_dry_run_single_hap_omits_hap2_outputs(mock_ctx_primary, tmp_path):
    """A primary/alternate (single-hap) ticket's dry-run must not fabricate hap2
    outputs — same class of bug already fixed once in blast_contaminants."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx_primary.workdir = tmp_path
    mock_ctx_primary.dry_run = True
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(
        mock_ctx_primary.ticket_id,
        mock_ctx_primary.tol_id,
        mock_ctx_primary.species,
        mock_ctx_primary.workdir,
    )
    mock_ctx_primary.tracker = RunTracker(tmp_path, registry=registry)

    run_pretext_to_asm(mock_ctx_primary)

    tracked_outputs = mock_ctx_primary.tracker.history("pretext_to_asm")[-1]["outputs"]
    assert "hap1_fa" in tracked_outputs
    assert "hap2_fa" not in tracked_outputs
    assert "hap2_haplotigs" not in tracked_outputs
    assert "hap2_chr_list" not in tracked_outputs


def test_run_pretext_to_asm_dry_run_output_resolves_via_find_canonical_fa(mock_ctx, tmp_path):
    """The fake FASTA written in dry-run mode must resolve through the real
    canonical-FASTA resolution pool, not just via tracker bookkeeping."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.utils.helpers import find_canonical_fa

    mock_ctx.workdir = tmp_path
    mock_ctx.dry_run = True
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(tmp_path, registry=registry)

    run_pretext_to_asm(mock_ctx)

    expected = Path(mock_ctx.tracker.get_output("pretext_to_asm", "hap1_fa"))
    resolved = find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix)
    assert resolved == expected


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_core_custom_agp_glob(mock_glob, mock_run, mock_ctx, tmp_path):
    """A custom agp_glob overrides the default {tol_id}*.agp* pattern."""
    from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    original_fa = tmp_path / "original.fa"
    original_fa.write_text("")
    agp = str(tmp_path / "sDipInt39.hap1.recurate.agp")
    mock_glob.return_value = [agp]
    mock_run.return_value = ""

    _run_pretext_to_asm_core(
        mock_ctx,
        "pretext_to_asm_recurate",
        original_fa,
        "missing",
        tmp_path,
        "sDipInt39.fa",
        [],
        agp_glob="sDipInt39*hap1*.agp*",
    )

    glob_pattern = mock_glob.call_args[0][0]
    assert glob_pattern == str(tmp_path / "sDipInt39*hap1*.agp*")


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_core_default_agp_glob_unchanged(
    mock_glob, mock_run, mock_ctx, tmp_path
):
    """Omitting agp_glob keeps today's {tol_id}*.agp* pattern (no regression)."""
    from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    original_fa = tmp_path / "original.fa"
    original_fa.write_text("")
    agp = str(tmp_path / "sDipInt39.agp")
    mock_glob.return_value = [agp]
    mock_run.return_value = ""

    _run_pretext_to_asm_core(
        mock_ctx, "pretext_to_asm", original_fa, "missing", tmp_path, "sDipInt39.fa", []
    )

    glob_pattern = mock_glob.call_args[0][0]
    assert glob_pattern == str(tmp_path / "sDipInt39*.agp*")


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_core_output_transform_runs_before_collect_outputs(
    mock_glob, mock_run, mock_ctx, tmp_path
):
    """output_transform can write a file that collect_outputs then picks up,
    all within the single finish() call collect_outputs feeds into."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    original_fa = tmp_path / "original.fa"
    original_fa.write_text("")
    agp = str(tmp_path / "sDipInt39.agp")
    mock_glob.return_value = [agp]
    mock_run.return_value = ""

    def _write_extra_file(run_dir):
        (run_dir / "hap1.extra_output.fa").write_text(">seq\nACGT\n")

    output_specs = [("hap1_extra", "hap1.extra_output.fa", [])]
    run_dir = _run_pretext_to_asm_core(
        mock_ctx,
        "pretext_to_asm",
        original_fa,
        "missing",
        tmp_path,
        "sDipInt39.fa",
        output_specs,
        output_transform=_write_extra_file,
    )

    assert mock_ctx.tracker.get_output("pretext_to_asm", "hap1_extra") == str(
        run_dir / "hap1.extra_output.fa"
    )


# ---------------------------------------------------------------------------
# run_haplotig_files
# ---------------------------------------------------------------------------


def test_run_haplotig_files_creates_empty_for_hap1(mock_ctx, tmp_path):
    """Dual-hap naming is driven by what pretext-to-asm actually produced on disk."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.assembly_type = "hap1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.release_version = 1

    (tmp_path / "sDipInt39.hap1.1.primary.curated.fa").write_text(">seq\n")

    run_haplotig_files(mock_ctx)

    expected = tmp_path / "sDipInt39.hap1.1.all_haplotigs.curated.fa"
    assert expected.exists()
    assert expected.stat().st_size == 0


def test_run_haplotig_files_creates_empty_for_primary(mock_ctx_primary, tmp_path):
    mock_ctx_primary.workdir = tmp_path
    mock_ctx_primary.tol_id = "ilHelSara1"
    mock_ctx_primary.assembly_type = "primary"
    mock_ctx_primary.release_version = 1

    (tmp_path / "ilHelSara1.1.primary.curated.fa").write_text(">seq\n")

    run_haplotig_files(mock_ctx_primary)

    expected = tmp_path / "ilHelSara1.1.all_haplotigs.curated.fa"
    assert expected.exists()


def test_run_haplotig_files_uses_disk_naming_over_yaml_when_mismatched(mock_ctx, tmp_path):
    """yaml declares primary/alternate but pretext-to-asm produced hap1/hap2 output —
    haplotig files must be named to match what's actually on disk, per-haplotype,
    not the single unprefixed name the YAML would suggest."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "ilScoBasi3"
    mock_ctx.assembly_type = "primary"
    mock_ctx.hap1_prefix = "primary"
    mock_ctx.hap2_prefix = "alternate"
    mock_ctx.release_version = 1

    (tmp_path / "ilScoBasi3.hap1.1.primary.curated.fa").write_text(">seq\n")
    (tmp_path / "ilScoBasi3.hap2.1.primary.curated.fa").write_text(">seq\n")

    run_haplotig_files(mock_ctx)

    assert (tmp_path / "ilScoBasi3.hap1.1.all_haplotigs.curated.fa").exists()
    assert (tmp_path / "ilScoBasi3.hap2.1.all_haplotigs.curated.fa").exists()
    assert not (tmp_path / "ilScoBasi3.1.all_haplotigs.curated.fa").exists()


def test_run_haplotig_files_nonempty_does_not_overwrite(mock_ctx, tmp_path):
    """A non-empty haplotig file must not be touched / zeroed out."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.assembly_type = "hap1"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.release_version = 1

    (tmp_path / "sDipInt39.hap1.1.primary.curated.fa").write_text(">seq\n")
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
def test_run_hic_remapping_includes_email_when_set(mock_find_fa, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""
    mock_ctx.email = "curator@sanger.ac.uk"

    mock_find_fa.return_value = tmp_path / "sDipInt39.1.hap1.primary.curated.fa"
    mock_run.return_value = ""

    run_hic_remapping(mock_ctx)

    cmd = mock_run.call_args[0][0]
    assert "--email curator@sanger.ac.uk" in cmd


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_omits_email_when_unset(mock_find_fa, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""
    mock_ctx.email = ""

    mock_find_fa.return_value = tmp_path / "sDipInt39.1.hap1.primary.curated.fa"
    mock_run.return_value = ""

    run_hic_remapping(mock_ctx)

    cmd = mock_run.call_args[0][0]
    assert "--email" not in cmd


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
def test_run_hic_remapping_hap2_exclusive_skips_hap1(mock_find_fa, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.hic_dir = Path("/lustre/hic")
    mock_ctx.long_reads_dir = Path("/lustre/pacbio")
    mock_ctx.read_type = "hifi"
    mock_ctx.teloseq = ""

    hap2_fa = tmp_path / "sDipInt39.1.hap2.primary.curated.fa"
    mock_find_fa.return_value = hap2_fa
    mock_run.return_value = ""

    run_hic_remapping(mock_ctx, run_hap1=False, run_hap2=True)

    assert mock_run.call_count == 1
    assert str(hap2_fa) in mock_run.call_args_list[0][0][0]


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_assembly_override_bypasses_find_canonical(
    mock_find_fa, mock_run, mock_ctx, tmp_path
):
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


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_dry_run_hap1_only(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """dry_run with default run_hap1=True/run_hap2=False must skip curationpretext.sh
    entirely and track a fake hap1 pretext map only."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.dry_run = True
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(tmp_path, registry=registry)

    run_hic_remapping(mock_ctx)

    mock_run.assert_not_called()
    mock_find_fa.assert_not_called()

    hap1_pretext = mock_ctx.tracker.get_output("hic_remapping", "hap1_pretext")
    assert hap1_pretext is not None
    assert Path(hap1_pretext).exists()

    assert mock_ctx.tracker.history("hic_remapping_hap2") == []


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_dry_run_hap2(mock_find_fa, mock_run, mock_ctx, tmp_path):
    """dry_run with run_hap2=True must additionally track a fake hap2 pretext map,
    tracked separately under hic_remapping_hap2."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.dry_run = True
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(tmp_path, registry=registry)

    run_hic_remapping(mock_ctx, run_hap2=True)

    mock_run.assert_not_called()
    mock_find_fa.assert_not_called()

    hap1_pretext = mock_ctx.tracker.get_output("hic_remapping", "hap1_pretext")
    hap2_pretext = mock_ctx.tracker.get_output("hic_remapping_hap2", "hap2_pretext")
    assert hap1_pretext is not None and Path(hap1_pretext).exists()
    assert hap2_pretext is not None and Path(hap2_pretext).exists()


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.hic_remapping.find_canonical_fa")
def test_run_hic_remapping_dry_run_hap2_exclusive_skips_hap1(
    mock_find_fa, mock_run, mock_ctx, tmp_path
):
    """dry_run with run_hap1=False, run_hap2=True must fake hap2 only."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.dry_run = True
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(tmp_path, registry=registry)

    run_hic_remapping(mock_ctx, run_hap1=False, run_hap2=True)

    mock_run.assert_not_called()
    mock_find_fa.assert_not_called()

    assert mock_ctx.tracker.history("hic_remapping") == []
    hap2_pretext = mock_ctx.tracker.get_output("hic_remapping_hap2", "hap2_pretext")
    assert hap2_pretext is not None
    assert Path(hap2_pretext).exists()


# ---------------------------------------------------------------------------
# run_qv
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.qv._run")
def test_run_qv_runs_inline(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1

    run_qv(mock_ctx)

    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert "kmer_completeness.bash" in cmd
    assert "sDipInt39" in cmd
    assert "1" in cmd
    assert "module load grit" in cmd


@patch("grit.steps.post_curation.qv._run")
def test_run_qv_print_only(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.print_only = True

    run_qv(mock_ctx)

    assert mock_run.called
    assert mock_run.call_args[0][1] is True  # print_only passed through


@patch("grit.steps.post_curation.qv._run")
def test_run_qv_registers_outputs_when_files_present(mock_run, mock_ctx, tmp_path):
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    merquryk = mock_ctx.assembly_curated_dir / "merquryk"
    merquryk.mkdir(parents=True)
    qv_file = merquryk / "sDipInt39.qv"
    qv_file.write_text("qv\t60.0\n")
    comp_file = merquryk / "sDipInt39.completeness.stats"
    comp_file.write_text("completeness\t99.9\n")

    run_qv(mock_ctx)

    assert mock_ctx.tracker.get_output("qv", "qv") == str(qv_file)
    assert mock_ctx.tracker.get_output("qv", "completeness_stats") == str(comp_file)


@patch("grit.steps.post_curation.qv._run")
def test_run_qv_outputs_empty_when_files_missing(mock_run, mock_ctx, tmp_path):
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    run_qv(mock_ctx)

    assert mock_ctx.tracker.get_output("qv", "qv") is None
    assert mock_ctx.tracker.get_output("qv", "completeness_stats") is None


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


def test_validate_curated_files_reads_tracker_qv_output(mock_ctx, tmp_path, capsys):
    """When qv registered outputs, validate-files must read those exact paths,
    not glob curated_dir/merquryk (which may contain stale/unrelated files)."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated"

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    tracked_qv = tmp_path / "elsewhere" / "sDipInt39.qv"
    tracked_qv.parent.mkdir()
    tracked_qv.write_text("tracked qv content\n")
    mock_ctx.tracker.finish(
        "qv", tmp_path / "qv" / "run1", "success", outputs={"qv": str(tracked_qv)}
    )

    validate_curated_files(mock_ctx)  # should not raise

    out = capsys.readouterr().out
    assert "tracked qv content" in out


# ---------------------------------------------------------------------------
# finalize_for_qc
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_creates_curated_dir(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_bsub,
    mock_ctx,
    tmp_path,
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
    # glob calls: yaml/pta mismatch check (has_hap1=True, has_hap2 check still runs but
    # is irrelevant once has_hap1 is True), nfs_first_level, hap1 remapped pretext
    mock_glob.side_effect = [[f"{mock_ctx.tol_id}.hap1.1.curated.fa"], [], [], [remapped]]
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("mkdir" in c for c in calls)
    assert any(str(curated_fa) in c for c in calls)
    assert any(str(chr_list) in c for c in calls)
    assert any(str(haplotig) in c for c in calls)
    # hap2 haplotigs not found — empty file created
    assert any("touch" in c and "hap2" in c and "all_haplotigs" in c for c in calls)


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_registers_curated_dir_output(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_qv_run,
    mock_ctx,
    tmp_path,
):
    """finalize_qc.finish() must record the *actually used* dest_dir, so overrides
    (via the curated_dir= kwarg) are discoverable via tracker.get_output, not just
    the default ctx.assembly_curated_dir."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.steps.post_curation.finalize_qc import finalize_for_qc

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    mock_find_fa.return_value = tmp_path / "sDipInt39.1.hap1.primary.curated.fa"
    mock_find_csv.return_value = tmp_path / "sDipInt39.1.hap1.chromosome.list.csv"
    mock_find_haplotigs.side_effect = [
        tmp_path / "sDipInt39.1.haplotigs.fa",
        FileNotFoundError("no haplotigs for hap2"),
    ]
    # yaml/pta mismatch check (has_hap1=True), nfs, remapped
    mock_glob.side_effect = [[f"{mock_ctx.tol_id}.hap1.1.curated.fa"], [], [], []]
    mock_run.return_value = ""

    override_dir = tmp_path / "custom_curated_dest"
    finalize_for_qc(mock_ctx, curated_dir=override_dir)

    assert mock_ctx.tracker.get_output("finalize_qc", "curated_dir") == str(override_dir)


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


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_assembly_override(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_bsub,
    mock_ctx,
    tmp_path,
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
    # yaml/pta mismatch check (has_hap1=True), nfs, remapped
    mock_glob.side_effect = [[f"{mock_ctx.tol_id}.hap1.1.curated.fa"], [], [], []]
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx, hap1_assembly=custom_fa)

    mock_find_fa.assert_called_once_with(mock_ctx, "hap2")  # hap1 skipped
    calls = [str(c) for c in mock_run.call_args_list]
    assert any(str(custom_fa) in c for c in calls)


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_hap2_map_copied_when_provided(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_bsub,
    mock_ctx,
    tmp_path,
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
    # yaml/pta mismatch check (has_hap1=True), nfs
    # (hap1_map/hap2_map are both provided as overrides, so _copy_map never globs)
    mock_glob.side_effect = [[f"{mock_ctx.tol_id}.hap1.1.curated.fa"], [], []]
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx, hap1_map=hap1_pretext, hap2_map=hap2_pretext)

    calls = [str(c) for c in mock_run.call_args_list]
    hap1_dest = "sDipInt39.1.hap1.curated.pretext"
    hap2_dest = "sDipInt39.1.hap2.curated.pretext"
    assert any(hap1_dest in c for c in calls)
    assert any(hap2_dest in c for c in calls)


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_primary_alternate_assembly_single_hap_output(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_bsub,
    mock_ctx,
    tmp_path,
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
    # yaml/pta mismatch check: no hap1/hap2-tokened curated fa on disk (has_hap1=False,
    # has_hap2=False) → matches YAML; then nfs, no remapped pretext
    mock_glob.side_effect = [[], [], [], []]
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


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_primary_alternate_uses_additional_haplotigs_when_not_combined(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_bsub,
    mock_ctx_primary,
    tmp_path,
):
    """post_process_rc/GritJiraIssue expects "additional_haplotigs.curated.fa" (not
    "all_haplotigs.curated.fa") for primary/alternate assemblies whose YAML does not
    set combine_for_curation — mismatching this makes post-processing fail outright
    with a missing-file error."""
    mock_ctx_primary.workdir = tmp_path
    mock_ctx_primary.tol_id = "ilBrySene2"
    mock_ctx_primary.release_version = 1
    assert mock_ctx_primary.combine_for_curation is False
    mock_ctx_primary.assembly_curated_dir = tmp_path / "curated" / "ilBrySene2.1"
    mock_ctx_primary.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")

    hap1_fa = tmp_path / "ilBrySene2.1.primary.curated.fa"
    chr_list = tmp_path / "ilBrySene2.1.primary.chromosome.list.csv"

    mock_find_fa.return_value = hap1_fa
    mock_find_csv.return_value = chr_list
    mock_find_haplotigs.side_effect = FileNotFoundError("no haplotigs")
    mock_glob.side_effect = [[], [], [], []]  # yaml/pta mismatch check x2, nfs, no remapped
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx_primary)

    calls = [str(c) for c in mock_run.call_args_list]
    assert any("ilBrySene2.1.additional_haplotigs.curated.fa" in c for c in calls)
    assert not any("all_haplotigs" in c for c in calls)


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_haplotig_dest_name_mirrors_disk_over_combine_for_curation_flag(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_bsub,
    mock_ctx_primary,
    tmp_path,
):
    """Even when the YAML sets combine_for_curation=True, if pretext-to-asm's real
    output on disk is named "additional_haplotigs", the dest name must mirror
    that — the YAML flag is only a fallback for when nothing is found at all."""
    mock_ctx_primary.workdir = tmp_path
    mock_ctx_primary.tol_id = "ilBrySene2"
    mock_ctx_primary.release_version = 1
    mock_ctx_primary.combine_for_curation = True
    mock_ctx_primary.assembly_curated_dir = tmp_path / "curated" / "ilBrySene2.1"
    mock_ctx_primary.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")

    hap1_fa = tmp_path / "ilBrySene2.1.primary.curated.fa"
    real_haplotigs = tmp_path / "ilBrySene2.1.additional_haplotigs.curated.fa"

    mock_find_fa.return_value = hap1_fa
    mock_find_csv.return_value = tmp_path / "chr.list.csv"
    mock_find_haplotigs.return_value = real_haplotigs
    mock_glob.side_effect = [[], [], [], []]  # yaml/pta mismatch check x2, nfs, no remapped
    mock_run.return_value = ""

    finalize_for_qc(mock_ctx_primary)

    calls = [str(c) for c in mock_run.call_args_list]
    expected_dest = "ilBrySene2.1.additional_haplotigs.curated.fa"
    assert any(str(real_haplotigs) in c and expected_dest in c for c in calls)
    assert not any("all_haplotigs" in c for c in calls)


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_raises_on_yaml_pta_mismatch(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_bsub,
    mock_ctx,
    tmp_path,
):
    """yaml declares primary/alternate but pretext-to-asm output has hap1+hap2 files."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "ilScoBasi3"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "primary"
    mock_ctx.hap2_prefix = "alternate"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "ilScoBasi3.1"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")
    mock_ctx.yaml_path = Path("/lustre/scratch122/tol/data/x/idOxyTril1.yaml")

    hap1_fa = tmp_path / "ilScoBasi3.hap1.1.primary.curated.fa"

    mock_glob.side_effect = [
        [str(hap1_fa)],  # yaml/pta mismatch check: hap1 curated fa present
        ["ilScoBasi3.hap2.1.primary.curated.fa"],  # yaml/pta mismatch check: hap2 too
    ]

    with pytest.raises(ValueError, match="assembly types don't match") as exc_info:
        finalize_for_qc(mock_ctx)

    assert str(mock_ctx.yaml_path) in str(exc_info.value)
    mock_find_fa.assert_not_called()
    mock_find_haplotigs.assert_not_called()
    mock_find_csv.assert_not_called()
    mock_run.assert_not_called()


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
@patch("grit.steps.post_curation.finalize_qc.glob.glob")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_chr_list")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")
@patch("grit.steps.post_curation.finalize_qc.find_canonical_fa")
def test_finalize_for_qc_raises_on_reverse_yaml_pta_mismatch(
    mock_find_fa,
    mock_find_haplotigs,
    mock_find_csv,
    mock_glob,
    mock_run,
    mock_bsub,
    mock_ctx,
    tmp_path,
):
    """yaml declares hap1/hap2 but pretext-to-asm only produced an unprefixed
    (primary/alternate-style) curated fa — the curator never split haplotypes."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "ilScoBasi3"
    mock_ctx.release_version = 1
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "ilScoBasi3.1"
    mock_ctx.curated_pretext_maps_nfs = Path("/nfs/curated_pretext_maps")
    mock_ctx.yaml_path = Path("/lustre/scratch122/tol/data/x/ilScoBasi3.yaml")

    unprefixed_fa = tmp_path / "ilScoBasi3.1.primary.curated.fa"

    mock_glob.side_effect = [
        [],  # yaml/pta mismatch check: no hap1-tokened curated fa
        [],  # yaml/pta mismatch check: no hap2-tokened curated fa
        [str(unprefixed_fa)],  # yaml/pta mismatch check: unprefixed fa present instead
    ]

    with pytest.raises(ValueError, match="assembly types don't match") as exc_info:
        finalize_for_qc(mock_ctx)

    assert str(mock_ctx.yaml_path) in str(exc_info.value)
    mock_find_fa.assert_not_called()
    mock_find_haplotigs.assert_not_called()
    mock_find_csv.assert_not_called()
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# run_qv — dry-run
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.qv._run")
def test_run_qv_dry_run(mock_run, mock_ctx, tmp_path):
    """dry_run must not shell out, but must write stub merquryk files that
    _find_qv_outputs(ctx) resolves and registers on the tracker."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.dry_run = True
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    run_qv(mock_ctx)

    mock_run.assert_not_called()

    qv_file = mock_ctx.tracker.get_output("qv", "qv")
    completeness_file = mock_ctx.tracker.get_output("qv", "completeness_stats")
    assert qv_file is not None and Path(qv_file).exists()
    assert completeness_file is not None and Path(completeness_file).exists()


# ---------------------------------------------------------------------------
# finalize_for_qc — dry-run
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
def test_finalize_for_qc_dry_run_dual_hap(mock_run, mock_qv_run, mock_ctx, tmp_path):
    """dry_run for a hap1/hap2 assembly must skip the real pta-mismatch check and
    real _run calls entirely, write placeholder files for both haplotypes, and
    exercise qv's own dry-run branch (not the real kmer_completeness.bash call)
    since no merquryk dir exists yet."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.dry_run = True
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_ctx.assembly_curated_dir = tmp_path / "curated" / "sDipInt39.1"

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    finalize_for_qc(mock_ctx)

    # neither finalize_qc's real copy commands nor qv's real subprocess ran
    mock_run.assert_not_called()
    mock_qv_run.assert_not_called()

    dest_dir = mock_ctx.assembly_curated_dir
    assert (dest_dir / "sDipInt39.hap1.1.primary.curated.fa").exists()
    assert (dest_dir / "sDipInt39.hap2.1.primary.curated.fa").exists()

    # qv's dry-run branch ran as part of finalize_qc's dry-run branch
    qv_file = mock_ctx.tracker.get_output("qv", "qv")
    assert qv_file is not None and Path(qv_file).exists()

    assert mock_ctx.tracker.get_output("finalize_qc", "curated_dir") == str(dest_dir)


@patch("grit.steps.post_curation.qv._run")
@patch("grit.steps.post_curation.finalize_qc._run")
def test_finalize_for_qc_dry_run_single_hap(mock_run, mock_qv_run, mock_ctx_primary, tmp_path):
    """dry_run for a primary/alternate assembly must write a placeholder for hap1
    only (mirroring is_single_hap(ctx) gating) and still cascade into qv's
    dry-run branch."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx_primary.workdir = tmp_path
    mock_ctx_primary.tol_id = "ilHelSara1"
    mock_ctx_primary.release_version = 1
    mock_ctx_primary.dry_run = True
    mock_ctx_primary.assembly_curated_dir = tmp_path / "curated" / "ilHelSara1.1"

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(
        mock_ctx_primary.ticket_id, mock_ctx_primary.tol_id, mock_ctx_primary.species, tmp_path
    )
    mock_ctx_primary.tracker = RunTracker(tmp_path, registry=reg)

    finalize_for_qc(mock_ctx_primary)

    mock_run.assert_not_called()
    mock_qv_run.assert_not_called()

    dest_dir = mock_ctx_primary.assembly_curated_dir
    assert (dest_dir / "ilHelSara1.1.primary.curated.fa").exists()
    # no hap2 file for a single-hap assembly
    assert not any(dest_dir.glob("ilHelSara1.*.hap2.*"))

    qv_file = mock_ctx_primary.tracker.get_output("qv", "qv")
    assert qv_file is not None and Path(qv_file).exists()

    assert mock_ctx_primary.tracker.get_output("finalize_qc", "curated_dir") == str(dest_dir)


# ---------------------------------------------------------------------------
# run_busco_synteny — dry-run
# ---------------------------------------------------------------------------


@patch("grit.steps.optional.busco_synteny._submit_bsub")
@patch("grit.steps.optional.busco_synteny.find_reheadered_reference")
@patch("grit.steps.optional.busco_synteny.find_canonical_fa")
def test_run_busco_synteny_dry_run_short_circuits(
    mock_find_fa, mock_find_ref, mock_bsub, mock_ctx, tmp_path
):
    """dry_run must skip reference/FASTA lookup + bsub submission entirely."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.steps.optional.busco_synteny import run_busco_synteny

    mock_ctx.workdir = tmp_path
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(tmp_path, registry=registry)
    mock_ctx.dry_run = True

    run_busco_synteny(mock_ctx, lineage="insecta_odb10")

    mock_bsub.assert_not_called()
    mock_find_fa.assert_not_called()
    mock_find_ref.assert_not_called()

    png_path = mock_ctx.tracker.get_output("busco_synteny", "png")
    assert png_path is not None
    assert Path(png_path).exists()


# ---------------------------------------------------------------------------
# run_busco_curated — dry-run
# ---------------------------------------------------------------------------


@patch("grit.steps.optional.busco_curated._submit_bsub")
@patch("grit.steps.optional.busco_curated.find_latest_dir")
def test_run_busco_curated_dry_run_short_circuits(
    mock_find_latest_dir, mock_bsub, mock_ctx, tmp_path
):
    """dry_run must skip curated-FASTA lookup + bsub submission entirely and
    write the placeholder output dir as a sibling of the tracked run_dir."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.steps.optional.busco_curated import run_busco_curated

    mock_ctx.workdir = tmp_path
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(tmp_path, registry=registry)
    mock_ctx.dry_run = True

    run_busco_curated(mock_ctx, lineage="insecta_odb10")

    mock_bsub.assert_not_called()
    mock_find_latest_dir.assert_not_called()

    output_dir = tmp_path / f"{mock_ctx.tol_id}_busco_singularity"
    assert output_dir.is_dir()
    assert any(output_dir.iterdir())


# ---------------------------------------------------------------------------
# run_post_curation — dry-run end to end
# ---------------------------------------------------------------------------


@patch("grit.steps.post_curation.hic_remapping._run")
@patch("grit.steps.post_curation.pretext_to_asm._run")
def test_run_post_curation_dry_run_tracks_every_sub_step(
    mock_pta_run, mock_hic_run, mock_ctx, tmp_path
):
    """dry_run must flow through pretext_to_asm, haplotig_files, and hic_remapping
    without any real subprocess, and every tracked sub-step's fake output must
    be resolvable afterwards (proving the composite needs no branch of its own)."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.steps.post_curation.post_curation import run_post_curation

    mock_ctx.workdir = tmp_path
    mock_ctx.dry_run = True
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, mock_ctx.workdir)
    mock_ctx.tracker = RunTracker(tmp_path, registry=registry)

    run_post_curation(mock_ctx, run_hap2=True)

    mock_pta_run.assert_not_called()
    mock_hic_run.assert_not_called()

    hap1_fa = mock_ctx.tracker.get_output("pretext_to_asm", "hap1_fa")
    assert hap1_fa is not None and Path(hap1_fa).exists()

    hap1_pretext = mock_ctx.tracker.get_output("hic_remapping", "hap1_pretext")
    hap2_pretext = mock_ctx.tracker.get_output("hic_remapping_hap2", "hap2_pretext")
    assert hap1_pretext is not None and Path(hap1_pretext).exists()
    assert hap2_pretext is not None and Path(hap2_pretext).exists()

    # haplotig_files has no tracker output specs — it's a plain local file-existence
    # check/touch step, unaffected by dry_run — verify its real effect directly.
    pta_run_dir = Path(hap1_fa).parent
    assert (
        pta_run_dir / f"{mock_ctx.tol_id}.hap1.{mock_ctx.release_version}.all_haplotigs.curated.fa"
    ).exists()
    assert (
        pta_run_dir / f"{mock_ctx.tol_id}.hap2.{mock_ctx.release_version}.all_haplotigs.curated.fa"
    ).exists()


# ---------------------------------------------------------------------------
# haplotig-files CLI — dry-run
# ---------------------------------------------------------------------------


def test_cli_haplotig_files_dry_run_chains_after_pretext_to_asm_dry_run(tmp_path, monkeypatch):
    """`grit --dry-run haplotig-files` must no longer raise UsageError, and —
    chained after a real `grit --dry-run pretext-to-asm` run against the same
    isolated workdir — must create empty haplotig files for both haps of the
    dual-hap fixture ticket."""
    from grit.core.click_cli import cli

    monkeypatch.setattr("grit.core.registry.dry_run_root", lambda: tmp_path)

    fixtures_dir = Path(__file__).parent / "fixtures"
    config_path = str(fixtures_dir / "test_config.yaml")
    yaml_path = str(fixtures_dir / "uoEpiScra1_hap1_hap2.yaml")
    common_args = ["--config", config_path, "--yaml", yaml_path, "--dry-run"]

    runner = CliRunner()

    result_pta = runner.invoke(cli, [*common_args, "pretext-to-asm"])
    assert result_pta.exit_code == 0, result_pta.output

    result_haplotig = runner.invoke(cli, [*common_args, "haplotig-files"])
    assert result_haplotig.exit_code == 0, result_haplotig.output

    workdir = tmp_path / "uoEpiScra1"
    pta_run_dir = Path(next((workdir / "pretext_to_asm").iterdir()))
    assert list(pta_run_dir.glob("uoEpiScra1.hap1.*.all_haplotigs.curated.fa"))
    assert list(pta_run_dir.glob("uoEpiScra1.hap2.*.all_haplotigs.curated.fa"))
