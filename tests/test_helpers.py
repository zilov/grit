"""Tests for grit/utils/helpers.py generic helpers."""

import time
from pathlib import Path

from grit.utils.helpers import (
    _check_bjobs,
    build_scp_tip,
    collect_outputs,
    inputs_newer_than_curated_fa,
    lsf_cluster,
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


# ---------------------------------------------------------------------------
# collect_outputs / write_fake_outputs — "multi" specs (4-element tuple)
# ---------------------------------------------------------------------------


def test_collect_outputs_multi_spec_joins_all_matches(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ref_idx = run_dir / "ref_name.idx"
    query_idx = run_dir / "query_name.idx"
    ref_idx.write_text("x")
    query_idx.write_text("x")

    found = collect_outputs([("idx", "*.idx", [], True)], run_dir, "sDipInt39")

    assert found["idx"] == "\n".join(sorted([str(ref_idx), str(query_idx)]))


def test_collect_outputs_non_multi_spec_keeps_only_last_match(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "a.idx").write_text("x")
    (run_dir / "b.idx").write_text("x")

    found = collect_outputs([("idx", "*.idx", [])], run_dir, "sDipInt39")

    assert found["idx"] == str(run_dir / "b.idx")


def test_write_fake_outputs_round_trips_through_collect_outputs_fastga(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    written = write_fake_outputs("fastga", run_dir, "sDipInt39")

    assert written
    assert len(written["idx"].split("\n")) == 2
    for path in written["idx"].split("\n"):
        assert Path(path).is_file()

    from grit.steps.optional.fastga import _OUTPUT_SPECS

    found = collect_outputs(_OUTPUT_SPECS, run_dir, "sDipInt39")
    assert found == written


def test_write_fake_outputs_round_trips_through_collect_outputs_fastga_stats(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    written = write_fake_outputs("fastga_stats", run_dir, "sDipInt39")

    assert written
    for key, path in written.items():
        assert Path(path).is_file()

    from grit.steps.optional.fastga import _OUTPUT_SPECS_STATS

    found = collect_outputs(_OUTPUT_SPECS_STATS, run_dir, "sDipInt39")
    assert found == written


# ----------------------------------------------------------------------
# _check_bjobs (CORR-04 / TEST-04)
# ----------------------------------------------------------------------


class _Completed:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr


def _patch_bjobs(monkeypatch, stdout="", stderr=""):
    monkeypatch.setattr(
        "grit.utils.helpers.subprocess.run",
        lambda *a, **kw: _Completed(stdout, stderr),
    )


def test_check_bjobs_parses_the_state_column(monkeypatch):
    _patch_bjobs(
        monkeypatch,
        stdout=(
            "793633  dz11    RUN   normal     farm22-agen node-13-12  probe Sep 23 12:29\n"
            "793634  dz11    PEND  normal     farm22-agen -           probe Sep 23 12:29\n"
        ),
    )
    assert _check_bjobs(["793633", "793634"]) == {"793633": "RUN", "793634": "PEND"}


def test_check_bjobs_marks_only_explicitly_unknown_jobs_gone(monkeypatch):
    """LSF reports each unknown job on stderr while still answering for the rest."""
    _patch_bjobs(
        monkeypatch,
        stdout="793633  dz11    RUN   normal     farm22-agen node-13-12  probe Sep 23 12:29\n",
        stderr="Job <111111> is not found\n",
    )
    assert _check_bjobs(["793633", "111111"]) == {"793633": "RUN", "111111": "gone"}


def test_check_bjobs_reports_unknown_when_lsf_cannot_be_asked(monkeypatch):
    """An LSF library error is not evidence that the jobs are over."""
    _patch_bjobs(monkeypatch, stderr="Failed in an LSF library call: Error 0\n")
    assert _check_bjobs(["753394", "753401"]) == {"753394": "unknown", "753401": "unknown"}


def test_check_bjobs_reports_unknown_when_bjobs_is_missing(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("bjobs")

    monkeypatch.setattr("grit.utils.helpers.subprocess.run", boom)
    assert _check_bjobs(["753394"]) == {"753394": "unknown"}


def test_check_bjobs_without_job_ids_does_not_call_lsf(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("bjobs should not be called")

    monkeypatch.setattr("grit.utils.helpers.subprocess.run", boom)
    assert _check_bjobs([]) == {}


def test_lsf_cluster_reads_the_cluster_name_from_the_environment(monkeypatch):
    monkeypatch.setenv("LSF_ENVDIR", "/software/lsf-farm22/conf")
    assert lsf_cluster() == "farm22"


def test_lsf_cluster_is_none_off_lsf(monkeypatch):
    monkeypatch.delenv("LSF_ENVDIR", raising=False)
    assert lsf_cluster() is None
