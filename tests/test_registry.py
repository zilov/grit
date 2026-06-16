"""Tests for RegistryManager."""

import json
from pathlib import Path

import pytest

from grit.core.registry import RegistryManager


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
    assert done[0]["status"] == "qc"


def test_mark_done_missing_ticket_warns(reg, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        reg.mark_done("MISSING")
    assert "not found" in caplog.text


def test_done_tickets_limit(reg):
    for i in range(10):
        reg.add_ticket(f"RC-{i:04d}", f"tol{i}", "species", Path(f"/work/{i}"))
        reg.mark_done(f"RC-{i:04d}")

    done = reg.done_tickets(limit=3)
    assert len(done) == 3


def test_refresh_statuses(reg, tmp_path):
    """refresh_statuses should re-derive status from runs.jsonl."""
    import json as _json
    from grit.core.run_tracker import RunTracker

    workdir = tmp_path / "work_sDipInt39"
    workdir.mkdir()
    reg.add_ticket("RC-1234", "sDipInt39", "species", workdir)

    # Write a runs.jsonl that shows pretext_to_asm succeeded
    grit_dir = workdir / ".grit"
    grit_dir.mkdir()
    runs = [
        {"step": "setup_curation", "timestamp": "2025-06-01T10_00_00", "status": "success",
         "ticket_id": "RC-1234", "tol_id": "sDipInt39", "run_dir": str(workdir)},
        {"step": "pretext_to_asm", "timestamp": "2025-06-01T12_00_00", "status": "success",
         "ticket_id": "RC-1234", "tol_id": "sDipInt39",
         "run_dir": str(workdir / "pretext_to_asm" / "2025-06-01T12_00_00")},
    ]
    (grit_dir / "runs.jsonl").write_text("\n".join(_json.dumps(r) for r in runs) + "\n")

    reg.refresh_statuses()

    t = reg.all_tickets()[0]
    assert t["status"] == "post_curation"
