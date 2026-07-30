"""Tests for grit/utils/helpers.py generic helpers."""

from grit.utils.helpers import build_scp_tip


def test_build_scp_tip_returns_none_when_no_files():
    assert build_scp_tip("farm22", "sDipInt39", [], "some outputs") is None


def test_build_scp_tip_single_file():
    tip = build_scp_tip("farm22", "sDipInt39", ["/lustre/foo/bar.png"], "busco-synteny plot")

    assert tip == (
        "Download busco-synteny plot:\n"
        "[bold cyan]scp farm22:/lustre/foo/bar.png ~/curations/work/sDipInt39[/bold cyan]"
    )


def test_build_scp_tip_multiple_files_joined_with_and():
    tip = build_scp_tip("farm22", "sDipInt39", ["/a.idx", "/b.paf"], "FastGA results")

    assert "scp farm22:/a.idx ~/curations/work/sDipInt39" in tip
    assert "scp farm22:/b.paf ~/curations/work/sDipInt39" in tip
    assert " && " in tip
