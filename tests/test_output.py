"""Tests for grit/utils/output.py."""

from pathlib import Path

from grit.utils.output import shorten_path


def test_shorten_path_replaces_workdir_prefix():
    workdir = Path("/lustre/working/dz11_curation/xbTest1")
    path = workdir / "pretext_to_asm" / "run1" / "out.fa"

    assert shorten_path(path, workdir) == "{workdir}/pretext_to_asm/run1/out.fa"


def test_shorten_path_returns_full_path_when_not_under_workdir():
    workdir = Path("/lustre/working/dz11_curation/xbTest1")
    path = Path("/lustre/other/somewhere.fa")

    assert shorten_path(path, workdir) == str(path)
