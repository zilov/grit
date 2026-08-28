"""Tests for RunTracker."""

import pytest

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker


@pytest.fixture
def reg(tmp_path):
    return RegistryManager(registry_dir=tmp_path / ".grit_reg")


@pytest.fixture
def tracker(tmp_path, reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", tmp_path)
    return RunTracker(tmp_path, registry=reg)


def test_start_creates_run_dir(tracker, tmp_path):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    assert run_dir.exists()
    assert run_dir.parent.name == "pretext_to_asm"


def test_start_writes_to_registry(tracker):
    tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    records = tracker.history()
    assert len(records) == 1
    r = records[0]
    assert r["step"] == "pretext_to_asm"
    assert r["status"] == "started"
    assert r["ticket_id"] == "RC-1234"
    assert r["tol_id"] == "sDipInt39"


def test_finish_appends_success_record(tracker):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", run_dir, "success")
    records = tracker.history()
    assert len(records) == 2
    assert records[-1]["status"] == "success"
    assert records[-1]["run_dir"] == str(run_dir)


def test_finish_appends_failed_record(tracker):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", run_dir, "failed")
    records = tracker.history()
    assert records[-1]["status"] == "failed"


def test_history_filters_by_step(tracker):
    r1 = tracker.start("setup_curation", "RC-1234", "sDipInt39")
    tracker.finish("setup_curation", r1, "success")
    r2 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", r2, "success")

    setup_records = tracker.history("setup_curation")
    assert all(r["step"] == "setup_curation" for r in setup_records)
    assert len(setup_records) == 2  # started + finished


def test_latest_run_dir_returns_last_success(tracker):
    r1 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", r1, "failed")
    r2 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", r2, "success")

    result = tracker.latest_run_dir("pretext_to_asm")
    assert result == r2


def test_latest_run_dir_falls_back_to_started(tracker):
    r1 = tracker.start("qv", "RC-1234", "sDipInt39")
    # No finish call — bsub job still running

    result = tracker.latest_run_dir("qv")
    assert result == r1


def test_latest_run_dir_returns_none_when_no_history(tracker):
    result = tracker.latest_run_dir("nonexistent_step")
    assert result is None


def test_record_job_patches_started_entry(tracker):
    run_dir = tracker.start("sex_matcher", "RC-1234", "sDipInt39")
    tracker.record_job("sex_matcher", run_dir, "99999")

    records = tracker.history("sex_matcher")
    started = next(r for r in records if r["status"] == "started")
    assert started["job_id"] == "99999"


def test_pending_jobs_returns_started_with_job_id(tracker):
    r1 = tracker.start("qv", "RC-1234", "sDipInt39")
    tracker.record_job("qv", r1, "12345")
    tracker.start("sex_matcher", "RC-1234", "sDipInt39")
    # no job_id for sex_matcher yet

    pending = tracker.pending_jobs()
    assert len(pending) == 1
    assert pending[0]["job_id"] == "12345"


def test_print_only_does_not_write_history(tmp_path, reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", tmp_path)
    tracker = RunTracker(tmp_path, print_only=True, registry=reg)
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    assert not run_dir.exists()
    assert reg.get_steps(tmp_path) == []


def test_verify_outputs_ok(tracker):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    (run_dir / "sDipInt39.1.hap1.curated.fa").write_text(">seq\n")
    (run_dir / "sDipInt39.1.curated.agp").write_text("")

    result = tracker.verify_outputs("pretext_to_asm", "sDipInt39", run_dir)
    assert result == "ok"


def test_verify_outputs_missing(tracker):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    # No files created

    result = tracker.verify_outputs("pretext_to_asm", "sDipInt39", run_dir)
    assert result == "missing"


def test_verify_outputs_not_tracked(tracker):
    result = tracker.verify_outputs("unknown_step", "sDipInt39", None)
    assert result == "not_tracked"


def test_verify_outputs_setup_curation_checks_workdir(tracker, tmp_path):
    (tmp_path / "original.fa").write_text(">seq\n")
    tracker.start("setup_curation", "RC-1234", "sDipInt39")

    result = tracker.verify_outputs("setup_curation", "sDipInt39")
    assert result == "ok"


def test_untrack_marks_latest_success(tracker):
    r1 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39", suffix="a")
    tracker.finish("pretext_to_asm", r1, "success")
    r2 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39", suffix="b")
    tracker.finish("pretext_to_asm", r2, "success")

    result = tracker.untrack("pretext_to_asm")
    assert result is True
    # Latest success (r2) is now untracked; previous success (r1) becomes canonical
    assert tracker.latest_run_dir("pretext_to_asm") == r1


def test_untrack_returns_false_when_no_success(tracker):
    result = tracker.untrack("nonexistent_step")
    assert result is False


def test_get_output_skips_untracked(tracker):
    r1 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39", suffix="a")
    tracker.finish("pretext_to_asm", r1, "success", outputs={"fa": "/path/to/r1.fa"})
    r2 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39", suffix="b")
    tracker.finish("pretext_to_asm", r2, "success", outputs={"fa": "/path/to/r2.fa"})

    tracker.untrack("pretext_to_asm")  # untracks r2
    assert tracker.get_output("pretext_to_asm", "fa") == "/path/to/r1.fa"


def test_start_untracked_never_canonical(tracker):
    tracker.start("qv", "RC-1234", "sDipInt39", untracked=True)
    # Even though we have a run_dir, latest_run_dir should not return it
    assert tracker.latest_run_dir("qv") is None


def test_finish_untracked_keeps_status_untracked(tracker):
    run_dir = tracker.start("qv", "RC-1234", "sDipInt39", untracked=True)
    tracker.finish("qv", run_dir, "success", outputs={"fa": "/path/to/r.fa"}, untracked=True)

    records = tracker.history("qv")
    assert records[-1]["status"] == "untracked"
    assert records[-1]["outputs"] == {"fa": "/path/to/r.fa"}
    assert tracker.latest_run_dir("qv") is None
    assert tracker.get_output("qv", "fa") is None


def test_finish_untracked_run_can_be_promoted(tracker):
    """The real success/failure a finish(untracked=True) call recorded is preserved
    (not lost), so promoting the run later can reuse it — mirrors grit retrack."""
    run_dir = tracker.start("qv", "RC-1234", "sDipInt39", untracked=True)
    tracker.finish("qv", run_dir, "success", outputs={"fa": "/path/to/r.fa"}, untracked=True)

    tracker.finish("qv", run_dir, "success", outputs={"fa": "/path/to/r.fa"})
    assert tracker.latest_run_dir("qv") == run_dir
    assert tracker.get_output("qv", "fa") == "/path/to/r.fa"


def test_untrack_undo(tracker):
    r1 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", r1, "success", outputs={"fa": "/path/to/r1.fa"})
    tracker.untrack("pretext_to_asm")
    assert tracker.latest_run_dir("pretext_to_asm") is None

    # Undo: append a success record for r1
    tracker.finish("pretext_to_asm", r1, "success", outputs={"fa": "/path/to/r1.fa"})
    assert tracker.latest_run_dir("pretext_to_asm") == r1
    assert tracker.get_output("pretext_to_asm", "fa") == "/path/to/r1.fa"


def test_history_reads_from_registry(tmp_path, reg):
    """RunTracker.history() is a pure view over RegistryManager.get_steps()."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg.add_ticket("RC-9999", "xbTest1", "species", workdir)
    reg.append_step(
        workdir,
        {
            "step": "pretext_to_asm",
            "timestamp": "2026-07-01T10_00_00",
            "status": "success",
            "run_dir": str(workdir / "pretext_to_asm" / "2026-07-01T10_00_00"),
            "job_id": None,
        },
    )

    tracker = RunTracker(workdir, registry=reg)

    steps = tracker.history("pretext_to_asm")
    assert len(steps) == 1
    assert steps[0]["status"] == "success"

    all_steps = tracker.history()
    assert len(all_steps) == 1
