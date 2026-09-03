"""Tests for RegistryManager."""

import json
import os
from pathlib import Path

import pytest

from grit.core.registry import (
    SNAPSHOT_RETENTION,
    RegistryError,
    RegistryManager,
    dry_run_root,
)


@pytest.fixture
def reg(tmp_path):
    return RegistryManager(registry_dir=tmp_path)


def test_add_ticket_creates_registry(reg, tmp_path):
    reg.add_ticket("RC-1234", "sDipInt39", "Dipturus intermedius", Path("/work/sDipInt39"))
    tickets = reg.all_tickets()
    assert len(tickets) == 1
    t = tickets[0]
    assert t["ticket_id"] == "RC-1234"
    assert t["tol_id"] == "sDipInt39"
    assert t["status"] == "in_curation"
    assert "added_at" in t


def test_add_ticket_idempotent(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "Dipturus intermedius", Path("/work"))
    reg.add_ticket("RC-1234", "sDipInt39", "Dipturus intermedius", Path("/work"))
    assert len(reg.all_tickets()) == 1


def test_add_ticket_updates_status(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"), status="in_curation")
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"), status="post_curation")
    t = reg.all_tickets()[0]
    assert t["status"] == "post_curation"


def test_update_status(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.update_status("RC-1234", "remapping")
    t = reg.all_tickets()[0]
    assert t["status"] == "remapping"


def test_update_status_missing_ticket_warns(reg, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        reg.update_status("MISSING", "remapping")
    assert "not found" in caplog.text


def test_mark_done_moves_to_done(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.mark_done("RC-1234")

    assert len(reg.all_tickets()) == 0
    done = reg.done_tickets()
    assert len(done) == 1
    assert done[0]["ticket_id"] == "RC-1234"
    assert done[0]["status"] == "done"


def test_mark_done_missing_ticket_warns(reg, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        reg.mark_done("MISSING")
    assert "not found" in caplog.text


def test_delete_ticket_removes_and_returns_entry(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    removed = reg.delete_ticket("RC-1234")

    assert removed is not None
    assert removed["ticket_id"] == "RC-1234"
    assert reg.find_ticket("RC-1234") is None
    assert reg.all_tickets() == []


def test_delete_ticket_missing_returns_none_and_leaves_registry_untouched(reg, caplog):
    import logging

    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    before = reg._load()

    with caplog.at_level(logging.WARNING):
        removed = reg.delete_ticket("MISSING")

    assert removed is None
    assert "not found" in caplog.text
    assert reg._load() == before


def test_done_tickets_limit(reg):
    for i in range(10):
        reg.add_ticket(f"RC-{i:04d}", f"tol{i}", "species", Path(f"/work/{i}"))
        reg.mark_done(f"RC-{i:04d}")

    done = reg.done_tickets(limit=3)
    assert len(done) == 3


def test_append_step_and_get_steps(reg, tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    reg.add_ticket("RC-1234", "xbTest1", "species", workdir)

    record = {
        "step": "pretext_to_asm",
        "timestamp": "2026-07-01T10_00_00",
        "status": "success",
        "run_dir": str(workdir / "pretext_to_asm" / "2026-07-01T10_00_00"),
        "job_id": None,
        "outputs": {"hap1_fa": "/path/to/hap1.fa"},
    }
    reg.append_step(workdir, record)

    steps = reg.get_steps(workdir)
    assert len(steps) == 1
    assert steps[0]["step"] == "pretext_to_asm"
    assert steps[0]["outputs"]["hap1_fa"] == "/path/to/hap1.fa"


def test_get_steps_filtered_by_name(reg, tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    reg.add_ticket("RC-1234", "xbTest1", "species", workdir)

    reg.append_step(workdir, {"step": "setup_curation", "status": "success"})
    reg.append_step(workdir, {"step": "pretext_to_asm", "status": "success"})

    assert len(reg.get_steps(workdir, "setup_curation")) == 1
    assert len(reg.get_steps(workdir, "pretext_to_asm")) == 1
    assert len(reg.get_steps(workdir)) == 2


def test_get_steps_unknown_workdir(reg, tmp_path):
    assert reg.get_steps(tmp_path / "nonexistent") == []


def test_append_step_unknown_workdir_warns(reg, tmp_path, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        reg.append_step(tmp_path / "nonexistent", {"step": "qv", "status": "started"})
    assert "no ticket found" in caplog.text


def test_patch_step_job_id(reg, tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    reg.add_ticket("RC-1234", "xbTest1", "species", workdir)

    run_dir = workdir / "qv" / "2026-07-01T10_00_00"
    reg.append_step(
        workdir,
        {
            "step": "qv",
            "timestamp": "2026-07-01T10_00_00",
            "status": "started",
            "run_dir": str(run_dir),
            "job_id": None,
        },
    )

    reg.patch_step_job_id(workdir, "qv", run_dir, "99999")

    steps = reg.get_steps(workdir, "qv")
    assert steps[0]["job_id"] == "99999"


def test_refresh_statuses_reads_from_steps_array(reg, tmp_path):
    """refresh_statuses re-derives status from the registry steps array."""
    workdir = tmp_path / "work"
    workdir.mkdir()
    reg.add_ticket("RC-1234", "xbTest1", "species", workdir)

    reg.append_step(
        workdir,
        {
            "step": "pretext_to_asm",
            "timestamp": "2026-07-01T10_00_00",
            "status": "success",
            "run_dir": str(workdir / "pretext_to_asm" / "2026-07-01T10_00_00"),
        },
    )

    reg.refresh_statuses()

    t = reg.all_tickets()[0]
    assert t["status"] == "post_curation"


def test_add_ticket_stores_hap_prefixes(reg):
    """add_ticket stores hap1_prefix and hap2_prefix in the registry record."""
    reg.add_ticket(
        "RC-5678",
        "xbTest2",
        "Test species",
        Path("/work/xbTest2"),
        hap1_prefix="primary",
        hap2_prefix="alternate",
    )
    t = reg.find_ticket("RC-5678")
    assert t is not None
    assert t["hap1_prefix"] == "primary"
    assert t["hap2_prefix"] == "alternate"


def test_add_ticket_hap_prefix_defaults(reg):
    """add_ticket defaults hap prefixes to hap1/hap2 when not supplied."""
    reg.add_ticket("RC-0001", "xbTest3", "species", Path("/work/xbTest3"))
    t = reg.find_ticket("RC-0001")
    assert t["hap1_prefix"] == "hap1"
    assert t["hap2_prefix"] == "hap2"


def test_add_ticket_updates_hap_prefixes(reg):
    """Calling add_ticket again updates hap prefixes on the existing record."""
    reg.add_ticket(
        "RC-9999", "xbTest4", "species", Path("/work"), hap1_prefix="hap1", hap2_prefix="hap2"
    )
    reg.add_ticket(
        "RC-9999",
        "xbTest4",
        "species",
        Path("/work"),
        hap1_prefix="paternal",
        hap2_prefix="maternal",
    )
    t = reg.find_ticket("RC-9999")
    assert t["hap1_prefix"] == "paternal"
    assert t["hap2_prefix"] == "maternal"


def test_find_ticket_by_workdir(reg, tmp_path):
    """find_ticket_by_workdir returns the ticket matching the given workdir."""
    workdir_a = tmp_path / "sDipInt39"
    workdir_b = tmp_path / "xbOther1"
    reg.add_ticket("RC-1234", "sDipInt39", "Dipturus intermedius", workdir_a)
    reg.add_ticket("RC-5678", "xbOther1", "Other species", workdir_b)

    found = reg.find_ticket_by_workdir(workdir_a)
    assert found is not None
    assert found["ticket_id"] == "RC-1234"


def test_find_ticket_by_workdir_not_found(reg, tmp_path):
    """find_ticket_by_workdir returns None when no ticket matches."""
    assert reg.find_ticket_by_workdir(tmp_path / "nonexistent") is None


def test_mark_cleaned_up_sets_flag(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.mark_done("RC-1234")
    reg.mark_cleaned_up("RC-1234")

    t = reg.find_ticket("RC-1234")
    assert t["cleaned_up"] is True


def test_mark_cleaned_up_missing_ticket_warns(reg, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        reg.mark_cleaned_up("MISSING")
    assert "not found" in caplog.text


def test_done_tickets_excludes_cleaned_by_default(reg):
    reg.add_ticket("RC-1", "tol1", "species", Path("/work/1"))
    reg.mark_done("RC-1")
    reg.add_ticket("RC-2", "tol2", "species", Path("/work/2"))
    reg.mark_done("RC-2")
    reg.mark_cleaned_up("RC-2")

    done = reg.done_tickets(limit=None)
    assert [t["ticket_id"] for t in done] == ["RC-1"]


def test_done_tickets_include_cleaned_returns_all(reg):
    reg.add_ticket("RC-1", "tol1", "species", Path("/work/1"))
    reg.mark_done("RC-1")
    reg.add_ticket("RC-2", "tol2", "species", Path("/work/2"))
    reg.mark_done("RC-2")
    reg.mark_cleaned_up("RC-2")

    done = reg.done_tickets(limit=None, include_cleaned=True)
    assert {t["ticket_id"] for t in done} == {"RC-1", "RC-2"}


def test_dry_run_root_is_isolated_subdir_of_home():
    root = dry_run_root()
    assert root == Path.home() / ".grit" / "dry_run"
    assert root != Path.home() / ".grit"


# ----------------------------------------------------------------------
# Fail-closed loading (CORR-01)
# ----------------------------------------------------------------------


def test_missing_registry_reads_as_empty(reg):
    assert reg.all_tickets() == []


def test_unreadable_registry_raises_instead_of_reading_as_empty(reg):
    reg.registry_path.write_text("{ this is not json")
    with pytest.raises(RegistryError):
        reg.all_tickets()


def test_unreadable_registry_is_not_overwritten_by_the_next_write(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.registry_path.write_text("{ truncated")

    with pytest.raises(RegistryError):
        reg.add_ticket("RC-9999", "sOther1", "species", Path("/work2"))

    assert reg.registry_path.read_text() == "{ truncated"


def test_unreadable_registry_error_names_the_backup_to_restore_from(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.add_ticket("RC-5678", "sOther1", "species", Path("/work2"))
    reg.registry_path.write_text("{ truncated")

    with pytest.raises(RegistryError) as exc:
        reg.all_tickets()

    assert str(reg.backup_path) in str(exc.value)


# ----------------------------------------------------------------------
# Backups
# ----------------------------------------------------------------------


def test_save_copies_the_previous_version_to_the_backup(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.add_ticket("RC-5678", "sOther1", "species", Path("/work2"))

    backed_up = json.loads(reg.backup_path.read_text())
    assert [t["ticket_id"] for t in backed_up] == ["RC-1234"]


def test_first_save_of_the_day_keeps_a_dated_snapshot(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.add_ticket("RC-5678", "sOther1", "species", Path("/work2"))

    snapshots = sorted(reg.dir.glob("grit_registry.2*.json"))
    assert len(snapshots) == 1
    assert [t["ticket_id"] for t in json.loads(snapshots[0].read_text())] == ["RC-1234"]


def test_dated_snapshot_is_not_overwritten_later_the_same_day(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.add_ticket("RC-5678", "sOther1", "species", Path("/work2"))
    reg.add_ticket("RC-9999", "sThird1", "species", Path("/work3"))

    snapshots = sorted(reg.dir.glob("grit_registry.2*.json"))
    assert len(snapshots) == 1
    assert [t["ticket_id"] for t in json.loads(snapshots[0].read_text())] == ["RC-1234"]


def test_dated_snapshots_are_pruned_to_the_retention_window(reg):
    for day in range(1, 12):
        (reg.dir / f"grit_registry.2020-01-{day:02d}.json").write_text("[]")
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.add_ticket("RC-5678", "sOther1", "species", Path("/work2"))

    snapshots = sorted(p.name for p in reg.dir.glob("grit_registry.2*.json"))
    assert len(snapshots) == SNAPSHOT_RETENTION
    assert "grit_registry.2020-01-01.json" not in snapshots


# ----------------------------------------------------------------------
# Write safety (CORR-02 interim mitigation, SEC-03)
# ----------------------------------------------------------------------


def test_temp_file_is_not_a_path_shared_between_writers(reg, monkeypatch):
    seen = []
    monkeypatch.setattr(os, "replace", lambda src, dst: seen.append(Path(src)))

    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))

    assert seen, "expected _save to install the registry via os.replace"
    for src in seen:
        assert src.name != "grit_registry.tmp"
        assert str(os.getpid()) in src.name


def test_failed_install_leaves_no_orphan_temp_file(reg, monkeypatch):
    def boom(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))

    assert list(reg.dir.glob("*.tmp*")) == []


def test_registry_and_backups_are_written_user_only(reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", Path("/work"))
    reg.add_ticket("RC-5678", "sOther1", "species", Path("/work2"))

    written = [reg.registry_path, reg.backup_path, *reg.dir.glob("grit_registry.2*.json")]
    for path in written:
        assert path.stat().st_mode & 0o777 == 0o600, path
