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
    return CurationContext.from_ticket("RC-1234", TEST_USER_CONFIG, yaml_override=TEST_YAML_HAP1)


@pytest.fixture
def mock_ctx_primary():
    """CurationContext for a single-haplotype assembly (primary/alternate)."""
    return CurationContext.from_ticket("RC-5678", TEST_USER_CONFIG, yaml_override=TEST_YAML_PRIMARY)


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
