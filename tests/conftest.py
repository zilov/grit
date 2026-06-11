"""
Test fixtures for grit.

mock_ctx — ready-made CurationContext built from test YAML without accessing Jira/NFS/Lustre.
"""

from pathlib import Path as _Path

import pytest
import yaml as _yaml

from grit.core.context import CurationContext

# --- test USER_CONFIG ---
TEST_USER_CONFIG = {
    "username": "testuser",
    "pretext_maps_nfs": "/nfs/treeoflife-01/teams/grit/data/pretext_maps",
    "curated_pretext_maps_nfs": "/nfs/treeoflife-01/teams/grit/data/curated_pretext_maps",
    "curation_savestates_nfs": "/nfs/treeoflife-01/teams/grit/data/curation_savestates",
    "farm_host": "farm22",
    "email": "testuser@sanger.ac.uk",
    "gritjiraissue_path": "/software/grit/lib",
}

# --- test YAML (mimics data from Jira) ---
TEST_YAML_HAP1 = {
    "specimen": "sDipInt39",
    "species": "Dipturus intermedius",
    "hap1": "/lustre/scratch122/tol/data/3/5/f/9/5/8/Dipturus_intermedius/assembly/draft/sDipInt39.1/sDipInt39.1.hap1.decontaminated.fa.gz",  # noqa: E501
    "hap2": "/lustre/scratch122/tol/data/3/5/f/9/5/8/Dipturus_intermedius/assembly/draft/sDipInt39.1/sDipInt39.1.hap2.decontaminated.fa.gz",  # noqa: E501
    "hic_read_dir": "/lustre/scratch122/tol/data/3/5/f/9/5/8/Dipturus_intermedius/genomic_data/sDipInt39/hic-arima2",  # noqa: E501
    "pacbio_read_dir": "/lustre/scratch122/tol/data/3/5/f/9/5/8/Dipturus_intermedius/genomic_data/sDipInt39/pacbio",  # noqa: E501
    "pacbio_read_type": "hifi",
    "ont_read_dir": None,
    "combine_for_curation": True,
    "release_version": 1,
}

TEST_YAML_PRIMARY = {
    "specimen": "ilHelSara1",
    "species": "Heliconius sara",
    "primary": "/lustre/scratch122/tol/data/1/2/a/b/c/d/Heliconius_sara/assembly/draft/ilHelSara1.1/ilHelSara1.1.primary.decontaminated.fa.gz",  # noqa: E501
    "hic_read_dir": "/lustre/scratch122/tol/data/1/2/a/b/c/d/Heliconius_sara/genomic_data/ilHelSara1/hic-arima2",  # noqa: E501
    "pacbio_read_dir": "/lustre/scratch122/tol/data/1/2/a/b/c/d/Heliconius_sara/genomic_data/ilHelSara1/pacbio",  # noqa: E501
    "pacbio_read_type": "hifi",
    "ont_read_dir": None,
    "combine_for_curation": False,
    "release_version": 1,
}


@pytest.fixture
def mock_ctx():
    """CurationContext for a dual-haplotype assembly (hap1/hap2)."""
    ctx = CurationContext.from_ticket("RC-1234", TEST_USER_CONFIG, yaml_override=TEST_YAML_HAP1)
    ctx.tracker = None  # unit tests must not touch the filesystem via tracker
    return ctx


@pytest.fixture
def mock_ctx_primary():
    """CurationContext for a single-haplotype assembly (primary/alternate)."""
    ctx = CurationContext.from_ticket("RC-5678", TEST_USER_CONFIG, yaml_override=TEST_YAML_PRIMARY)
    ctx.tracker = None
    return ctx


# --- real YAML fixtures (loaded from files) ---

_FIXTURES_DIR = _Path(__file__).parent / "fixtures"


@pytest.fixture
def real_ctx_hap1_hap2():
    """CurationContext built from the real uoEpiScra1 hap1/hap2 YAML fixture."""
    with open(_FIXTURES_DIR / "uoEpiScra1_hap1_hap2.yaml") as f:
        yaml_data = _yaml.safe_load(f)
    return CurationContext.from_ticket("RC-real-hap", TEST_USER_CONFIG, yaml_override=yaml_data)


@pytest.fixture
def real_ctx_primary():
    """CurationContext built from the real xbLimHian1 primary YAML fixture."""
    with open(_FIXTURES_DIR / "xbLimHian1_primary.yaml") as f:
        yaml_data = _yaml.safe_load(f)
    return CurationContext.from_ticket("RC-real-primary", TEST_USER_CONFIG, yaml_override=yaml_data)


@pytest.fixture
def fake_workdir(tmp_path, mock_ctx):
    """
    Populate a tmp_path with a minimal workdir structure for a hap1/hap2 ticket.

    Creates the canonical files that real step runs would produce, so tests for
    context-from-workdir (_extend_from_workdir) and RunTracker can run without
    a server or real data.

    Layout produced:
        tmp_path/
            original.fa                                 (setup output)
            sDipInt39.1.hap1.hr.pretext                 (copy_pretext_maps output)
            reference/
                GCA_000001.fa                           (find_reference output)
            sex_matcher/
                Best_match_sDipInt39.txt                (sex_matcher output)
            pretext_to_asm/
                2025-06-02T14:00:00/
                    sDipInt39.1.hap1.curated.fa
                    sDipInt39.1.curated.agp
            hic_remapping/
                2025-06-02T15:00:00/
                    sDipInt39.1.hap1.hr.pretext         (remapped map)
            .grit/
                runs.jsonl                              (RunTracker log)
    """
    import json

    mock_ctx.workdir = tmp_path
    tol_id = mock_ctx.tol_id          # sDipInt39
    tol_id_v = mock_ctx.tol_id_versioned  # sDipInt39.1

    # setup outputs
    (tmp_path / "original.fa").write_text(">seq1\nACGT\n")
    (tmp_path / f"{tol_id_v}.hap1.hr.pretext").write_text("")

    # find_reference output
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    (ref_dir / "GCA_000001.fa").write_text(">ref\nACGT\n")

    # sex_matcher output
    sm_dir = tmp_path / "sex_matcher"
    sm_dir.mkdir()
    (sm_dir / f"Best_match_{tol_id}.txt").write_text("XX\n")

    # pretext_to_asm run dir
    pta_ts = "2025-06-02T14:00:00"
    pta_dir = tmp_path / "pretext_to_asm" / pta_ts
    pta_dir.mkdir(parents=True)
    (pta_dir / f"{tol_id_v}.hap1.curated.fa").write_text(">curated\nACGT\n")
    (pta_dir / f"{tol_id_v}.curated.agp").write_text("")

    # hic_remapping run dir
    hic_ts = "2025-06-02T15:00:00"
    hic_dir = tmp_path / "hic_remapping" / hic_ts
    hic_dir.mkdir(parents=True)
    (hic_dir / f"{tol_id_v}.hap1.hr.pretext").write_text("")

    # .grit/runs.jsonl
    grit_dir = tmp_path / ".grit"
    grit_dir.mkdir()
    runs = [
        {"step": "setup_curation", "timestamp": "2025-06-02T10:00:00", "status": "success",
         "ticket_id": mock_ctx.ticket_id, "tol_id": tol_id, "run_dir": str(tmp_path)},
        {"step": "pretext_to_asm", "timestamp": pta_ts, "status": "success",
         "ticket_id": mock_ctx.ticket_id, "tol_id": tol_id, "run_dir": str(pta_dir)},
        {"step": "hic_remapping", "timestamp": hic_ts, "status": "success",
         "ticket_id": mock_ctx.ticket_id, "tol_id": tol_id, "run_dir": str(hic_dir)},
    ]
    (grit_dir / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs) + "\n")

    # Attach a tracker pointing to the real tmp_path
    from grit.core.run_tracker import RunTracker
    mock_ctx.tracker = RunTracker(tmp_path)

    return tmp_path
