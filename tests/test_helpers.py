"""Tests for grit/utils/helpers.py generic helpers."""

import time

from grit.utils.helpers import build_scp_tip, inputs_newer_than_curated_fa


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


# ---------------------------------------------------------------------------
# inputs_newer_than_curated_fa
# ---------------------------------------------------------------------------


def _touch(path, content="x"):
    path.write_text(content)
    return path


def test_inputs_newer_than_curated_fa_false_when_no_curated_fa(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    assert inputs_newer_than_curated_fa(workdir, "sDipInt39", None) is False


def test_inputs_newer_than_curated_fa_true_when_agp_newer(tmp_path):
    workdir = tmp_path / "workdir"
    pta_dir = tmp_path / "pta"
    workdir.mkdir()
    pta_dir.mkdir()

    _touch(pta_dir / "sDipInt39.curated.fa")
    time.sleep(0.01)
    _touch(workdir / "sDipInt39.pretext.agp_1")

    assert inputs_newer_than_curated_fa(workdir, "sDipInt39", pta_dir) is True


def test_inputs_newer_than_curated_fa_true_when_extra_input_newer(tmp_path):
    """original.fa (passed via extra_inputs) being touched should also trigger a rerun."""
    workdir = tmp_path / "workdir"
    pta_dir = tmp_path / "pta"
    workdir.mkdir()
    pta_dir.mkdir()

    _touch(workdir / "sDipInt39.pretext.agp_1")
    _touch(pta_dir / "sDipInt39.curated.fa")
    time.sleep(0.01)
    original_fa = _touch(workdir / "original.fa")

    assert (
        inputs_newer_than_curated_fa(workdir, "sDipInt39", pta_dir, extra_inputs=[original_fa])
        is True
    )


def test_inputs_newer_than_curated_fa_false_when_all_inputs_older(tmp_path):
    workdir = tmp_path / "workdir"
    pta_dir = tmp_path / "pta"
    workdir.mkdir()
    pta_dir.mkdir()

    _touch(workdir / "sDipInt39.pretext.agp_1")
    original_fa = _touch(workdir / "original.fa")
    time.sleep(0.01)
    _touch(pta_dir / "sDipInt39.curated.fa")

    assert (
        inputs_newer_than_curated_fa(workdir, "sDipInt39", pta_dir, extra_inputs=[original_fa])
        is False
    )
