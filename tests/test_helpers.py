"""Tests for grit/utils/helpers.py generic helpers."""

import time
from pathlib import Path

from grit.utils.helpers import (
    build_scp_tip,
    collect_outputs,
    inputs_newer_than_curated_fa,
    write_fake_outputs,
)


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


# ---------------------------------------------------------------------------
# write_fake_outputs
# ---------------------------------------------------------------------------


def test_write_fake_outputs_round_trips_through_collect_outputs_pretext_to_asm(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    written = write_fake_outputs("pretext_to_asm", run_dir, "sDipInt39")

    assert written
    for key, path in written.items():
        assert Path(path).is_file()

    from grit.steps.post_curation.pretext_to_asm import _OUTPUT_SPECS

    found = collect_outputs(_OUTPUT_SPECS, run_dir, "sDipInt39")
    assert found == written


def test_write_fake_outputs_round_trips_through_collect_outputs_rename_and_orient(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    written = write_fake_outputs("rename_and_orient", run_dir, "sDipInt39")

    assert written
    from grit.steps.optional.rename_and_orient import _OUTPUT_SPECS

    found = collect_outputs(_OUTPUT_SPECS, run_dir, "sDipInt39")
    assert found == written


def test_write_fake_outputs_round_trips_through_collect_outputs_hic_remapping(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    written = write_fake_outputs("hic_remapping", run_dir, "sDipInt39")

    assert written
    from grit.steps.post_curation.hic_remapping import _OUTPUT_SPECS

    found = collect_outputs(_OUTPUT_SPECS, run_dir, "sDipInt39")
    assert found == written


def test_write_fake_outputs_uses_content_override(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    written = write_fake_outputs(
        "rename_and_orient",
        run_dir,
        "sDipInt39",
        content={"hap1_fa": b">real\nACGTACGT\n"},
    )

    assert Path(written["hap1_fa"]).read_bytes() == b">real\nACGTACGT\n"


def test_write_fake_outputs_writes_trivial_stub_without_content(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    written = write_fake_outputs("rename_and_orient", run_dir, "sDipInt39")

    assert Path(written["hap1_fa"]).read_bytes() == b">fake\nACGT\n"


def test_write_fake_outputs_unknown_step_returns_empty_and_writes_nothing(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    written = write_fake_outputs("not_a_real_step", run_dir, "sDipInt39")

    assert written == {}
    assert list(run_dir.iterdir()) == []
