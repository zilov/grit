"""
Tests for CurationContext and build_context().
"""

from pathlib import Path

import pytest

from grit.core.context import CurationContext, _derive_workdir, _detect_assembly_type
from tests.conftest import TEST_USER_CONFIG, TEST_YAML_HAP1, TEST_YAML_PRIMARY

# --- _detect_assembly_type ---


def test_detect_assembly_type_hap1():
    atype, h1, h2 = _detect_assembly_type({"hap1": "...", "hap2": "..."})
    assert atype == "hap1"
    assert h1 == "hap1"
    assert h2 == "hap2"


def test_detect_assembly_type_primary():
    atype, h1, h2 = _detect_assembly_type({"primary": "..."})
    assert atype == "primary"
    assert h1 == "primary"
    assert h2 == "alternate"


def test_detect_assembly_type_unknown():
    with pytest.raises(ValueError, match="Cannot detect assembly type"):
        _detect_assembly_type({"unknown_key": "..."})


# --- _derive_workdir ---


def test_derive_workdir_replaces_draft_with_working():
    draft = Path("/lustre/scratch122/tol/data/3/5/f/9/5/8/Dipturus_intermedius/assembly/draft")
    result = _derive_workdir(draft, "dz11", "sDipInt39")
    assert "working" in str(result)
    assert "assembly/draft" not in str(result)
    assert "dz11_curation" in str(result)
    assert "sDipInt39" in str(result)


def test_derive_workdir_strips_version_from_tol_id():
    draft = Path("/lustre/scratch122/tol/data/3/5/f/Dipturus_intermedius/assembly/draft")
    result = _derive_workdir(draft, "user1", "sDipInt39.1")
    # version suffix .1 should be stripped from tol_id in workdir
    assert result.name == "sDipInt39"


def test_derive_workdir_raises_without_assembly_draft():
    bad_path = Path("/some/other/path/sDipInt39")
    with pytest.raises(ValueError, match="Expected 'assembly/draft'"):
        _derive_workdir(bad_path, "user1", "sDipInt39")


# --- build_context (hap1) ---


def test_build_context_hap1_basic(mock_ctx):
    assert mock_ctx.ticket_id == "RC-1234"
    assert mock_ctx.tol_id == "sDipInt39"
    assert mock_ctx.assembly_type == "hap1"
    assert mock_ctx.hap1_prefix == "hap1"
    assert mock_ctx.hap2_prefix == "hap2"
    assert mock_ctx.combine_for_curation is True
    assert mock_ctx.read_type == "hifi"


def test_build_context_workdir_contains_username(mock_ctx):
    assert "testuser_curation" in str(mock_ctx.workdir)


def test_build_context_workdir_derived_from_draft(mock_ctx):
    assert "working/testuser_curation/sDipInt39" in str(mock_ctx.workdir)
    assert "assembly/draft" not in str(mock_ctx.workdir)


def test_build_context_versioned_tol_id(mock_ctx):
    assert mock_ctx.tol_id_versioned == "sDipInt39.1"


def test_build_context_nfs_paths(mock_ctx):
    assert mock_ctx.pretext_maps_nfs == Path("/nfs/treeoflife-01/teams/grit/data/pretext_maps")


def test_build_context_no_teloseq_by_default(mock_ctx):
    assert mock_ctx.teloseq == ""


def test_build_context_bsub_ram_defaults_to_none(mock_ctx):
    assert mock_ctx.bsub_ram is None


def test_build_context_bsub_ram_override():
    ctx = CurationContext.from_ticket(
        "RC-1234", TEST_USER_CONFIG, yaml_override=TEST_YAML_PRIMARY, bsub_ram=64000
    )
    assert ctx.bsub_ram == 64000


# --- build_context (primary) ---


def test_build_context_primary_type(mock_ctx_primary):
    assert mock_ctx_primary.assembly_type == "primary"
    assert mock_ctx_primary.hap1_prefix == "primary"
    assert mock_ctx_primary.hap2_prefix == "alternate"
    assert mock_ctx_primary.combine_for_curation is False


def test_build_context_primary_tol_id(mock_ctx_primary):
    assert mock_ctx_primary.tol_id == "ilHelSara1"


# --- build_context with teloseq ---


def test_build_context_with_teloseq():
    yaml_with_telo = {**TEST_YAML_PRIMARY, "teloseq": "TTAGG"}
    # teloseq is passed via yaml_override — but in build_context it comes from a Jira field
    # verify that with yaml_override teloseq is empty (Jira is not accessible)
    ctx = CurationContext.from_ticket("RC-0001", TEST_USER_CONFIG, yaml_override=yaml_with_telo)
    assert ctx.teloseq == ""  # teloseq is read from Jira customfield, not from YAML


# --- real YAML fixtures ---


def test_real_hap1_assembly_draft_dir_has_version(real_ctx_hap1_hap2):
    """assembly_draft_dir must be the versioned subdir, not the parent of it."""
    ctx = real_ctx_hap1_hap2
    assert ctx.assembly_draft_dir.name == "uoEpiScra1.20241115"


def test_real_hap1_assembly_draft_dir_ends_with_draft_subdir(real_ctx_hap1_hap2):
    ctx = real_ctx_hap1_hap2
    assert "assembly/draft/uoEpiScra1.20241115" in str(ctx.assembly_draft_dir)


def test_real_hap1_curated_dir(real_ctx_hap1_hap2):
    ctx = real_ctx_hap1_hap2
    assert str(ctx.assembly_curated_dir).endswith("assembly/curated/uoEpiScra1.1")
    assert "assembly/draft" not in str(ctx.assembly_curated_dir)
    assert "20241115" not in str(ctx.assembly_curated_dir)


def test_real_hap1_assembly_type(real_ctx_hap1_hap2):
    ctx = real_ctx_hap1_hap2
    assert ctx.assembly_type == "hap1"
    assert ctx.tol_id == "uoEpiScra1"
    assert ctx.combine_for_curation is True


def test_real_hap1_workdir(real_ctx_hap1_hap2):
    ctx = real_ctx_hap1_hap2
    assert "working/testuser_curation/uoEpiScra1" in str(ctx.workdir)
    assert "assembly/draft" not in str(ctx.workdir)


def test_real_primary_assembly_draft_dir_has_version(real_ctx_primary):
    ctx = real_ctx_primary
    assert ctx.assembly_draft_dir.name == "xbLimHian1.20240425"


def test_real_primary_assembly_type(real_ctx_primary):
    ctx = real_ctx_primary
    assert ctx.assembly_type == "primary"
    assert ctx.tol_id == "xbLimHian1"
    assert ctx.combine_for_curation is False


def test_real_primary_curated_dir(real_ctx_primary):
    ctx = real_ctx_primary
    assert str(ctx.assembly_curated_dir).endswith("assembly/curated/xbLimHian1.1")
    assert "20240425" not in str(ctx.assembly_curated_dir)


# --- dry_run isolation ---


def test_dry_run_flag_threads_through_to_context():
    ctx = CurationContext.from_ticket(
        "RC-1234", TEST_USER_CONFIG, yaml_override=TEST_YAML_HAP1, dry_run=True
    )
    assert ctx.dry_run is True


def test_dry_run_defaults_to_false(mock_ctx):
    assert mock_ctx.dry_run is False


def test_dry_run_workdir_isolated_from_real_workdir(tmp_path, monkeypatch):
    """A dry_run=True context's workdir/tracker registry must live under
    dry_run_root(), never under the real derived workdir or ~/.grit."""
    monkeypatch.setattr("grit.core.registry.dry_run_root", lambda: tmp_path)

    real_ctx = CurationContext.from_ticket(
        "RC-1234", TEST_USER_CONFIG, yaml_override=TEST_YAML_HAP1, dry_run=False
    )
    dry_ctx = CurationContext.from_ticket(
        "RC-1234", TEST_USER_CONFIG, yaml_override=TEST_YAML_HAP1, dry_run=True
    )

    assert dry_ctx.workdir != real_ctx.workdir
    assert tmp_path in dry_ctx.workdir.parents or dry_ctx.workdir == tmp_path
    assert "assembly/draft" not in str(real_ctx.workdir)

    # tracker's underlying registry points at the monkeypatched dry_run_root, not ~/.grit
    assert dry_ctx.tracker._registry.dir == tmp_path
    assert dry_ctx.tracker.workdir == dry_ctx.workdir
