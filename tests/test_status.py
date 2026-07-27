"""Tests for grit.core.status.show_ticket_history — LSF exit reason surfacing."""

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.core.status import show_ticket_history
from tests.conftest import TEST_USER_CONFIG


def _make_failed_step(tmp_path, monkeypatch, step="fastga", log_name="e_fastga", log_text=""):
    # show_ticket_history() builds its own RunTracker() with the *default* RegistryManager,
    # so point that default at our tmp_path registry too.
    registry_dir = tmp_path / ".grit_reg"
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", registry_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg = RegistryManager(registry_dir=registry_dir)
    reg.add_ticket("RC-1234", "sDipInt39", "species", workdir)
    tracker = RunTracker(workdir, registry=reg)
    run_dir = tracker.start(step, "RC-1234", "sDipInt39")
    if log_text:
        (run_dir / log_name).write_text(log_text)
    tracker.finish(step, run_dir, "failed")
    return reg


def test_show_ticket_history_surfaces_term_memlimit(tmp_path, capsys, monkeypatch):
    reg = _make_failed_step(
        tmp_path,
        monkeypatch,
        log_text="TERM_MEMLIMIT: job killed after reaching LSF memory usage limit.\n",
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "TERM_MEMLIMIT" in out


def test_show_ticket_history_prints_memlimit_tip(tmp_path, capsys, monkeypatch):
    reg = _make_failed_step(
        tmp_path,
        monkeypatch,
        log_text="TERM_MEMLIMIT: job killed after reaching LSF memory usage limit.\n",
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "--bsub-ram" in out
    assert "fastga" in out


def test_show_ticket_history_no_reason_when_log_has_none(tmp_path, capsys, monkeypatch):
    reg = _make_failed_step(
        tmp_path, monkeypatch, log_text="Successfully completed some other step.\n"
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "TERM_" not in out
    assert "--bsub-ram" not in out


def test_show_ticket_history_no_reason_when_no_log(tmp_path, capsys, monkeypatch):
    reg = _make_failed_step(tmp_path, monkeypatch, log_text="")

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "TERM_" not in out
