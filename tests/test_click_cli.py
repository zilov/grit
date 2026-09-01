"""Tests for `grit status` / `grit untrack` --dry-run isolation.

Follows the CliRunner + _DEFAULT_DIR-monkeypatch pattern established in
tests/test_remove_cmd.py.
"""

import pytest
import yaml
from click.testing import CliRunner

from grit.core.click_cli import cli
from grit.core.registry import RegistryManager
from tests.conftest import TEST_USER_CONFIG


@pytest.fixture(autouse=True)
def _patch_registry_dir(tmp_path, monkeypatch):
    """status_cmd/untrack_cmd construct RegistryManager() with no args in the
    non-dry-run path, so point the default registry dir at tmp_path for the
    duration of each test — keeps any accidental real-registry write off ~/.grit."""
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def dry_run_dir(tmp_path_factory, monkeypatch):
    """Separate location that dry_run_root() is monkeypatched to return —
    distinct from the autouse _DEFAULT_DIR fixture's tmp_path."""
    d = tmp_path_factory.mktemp("dry_run_root")
    monkeypatch.setattr("grit.core.registry.dry_run_root", lambda: d)
    return d


@pytest.fixture
def user_config_path(tmp_path):
    """A local user-config YAML file, for status_cmd's -t path (load_user_config)."""
    path = tmp_path / "grit_curation_config.yaml"
    path.write_text(yaml.safe_dump(TEST_USER_CONFIG))
    return path


def _seed_ticket(registry_dir, tmp_path, ticket_id="RC-1234", tol_id="xbTest1"):
    reg = RegistryManager(registry_dir=registry_dir)
    workdir = tmp_path / f"workdir_{registry_dir.name}"
    workdir.mkdir(exist_ok=True)
    reg.add_ticket(ticket_id, tol_id, "species", workdir)
    return reg, workdir


def test_status_dry_run_reads_from_dry_run_registry_not_default(
    tmp_path, dry_run_dir, _patch_registry_dir
):
    # Seed a ticket only in the dry-run registry.
    _seed_ticket(dry_run_dir, tmp_path, ticket_id="RC-DRY", tol_id="xbDry1")

    runner = CliRunner()
    result = runner.invoke(cli, ["--dry-run", "status"])

    assert result.exit_code == 0, result.output
    assert "RC-DRY" in result.output

    # The default (non-dry-run) registry has no tickets, so a plain `status`
    # invocation must not see RC-DRY.
    result_default = runner.invoke(cli, ["status"])
    assert result_default.exit_code == 0, result_default.output
    assert "RC-DRY" not in result_default.output


def test_status_default_reads_from_default_registry_not_dry_run(
    tmp_path, dry_run_dir, _patch_registry_dir
):
    # Seed a ticket only in the default (_patch_registry_dir) registry.
    _seed_ticket(_patch_registry_dir, tmp_path, ticket_id="RC-REAL", tol_id="xbReal1")

    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0, result.output
    assert "RC-REAL" in result.output

    result_dry = runner.invoke(cli, ["--dry-run", "status"])
    assert result_dry.exit_code == 0, result_dry.output
    assert "RC-REAL" not in result_dry.output


def test_untrack_dry_run_targets_dry_run_registry(tmp_path, dry_run_dir, _patch_registry_dir):
    from grit.core.run_tracker import RunTracker

    reg, workdir = _seed_ticket(dry_run_dir, tmp_path, ticket_id="RC-DRY", tol_id="xbDry1")
    tracker = RunTracker(workdir, registry=reg)
    run_dir = tracker.start("rename_and_orient", "RC-DRY", "xbDry1")
    tracker.finish("rename_and_orient", run_dir, "success")

    runner = CliRunner()
    result = runner.invoke(cli, ["--dry-run", "untrack", "-t", "RC-DRY", "-s", "rename_and_orient"])

    assert result.exit_code == 0, result.output
    runs = reg.get_steps(workdir, "rename_and_orient")
    assert runs[-1]["status"] == "untracked"


def test_retrack_promotes_a_run_started_as_untracked(tmp_path, dry_run_dir, _patch_registry_dir):
    """A run started with `--untracked` (never previously canonical) must still be
    promotable via `grit retrack`, using the outputs its own finish() call
    recorded — not just outputs from a prior `success` record (see run_tracker.finish)."""
    from grit.core.run_tracker import RunTracker

    reg, workdir = _seed_ticket(dry_run_dir, tmp_path, ticket_id="RC-DRY", tol_id="xbDry1")
    tracker = RunTracker(workdir, registry=reg)
    run_dir = tracker.start("qv", "RC-DRY", "xbDry1", untracked=True)
    tracker.finish("qv", run_dir, "success", outputs={"qv_report": "/path/qv.txt"}, untracked=True)

    runner = CliRunner()
    result = runner.invoke(cli, ["--dry-run", "retrack", "-t", "RC-DRY", "-s", "qv"])

    assert result.exit_code == 0, result.output
    assert tracker.latest_run_dir("qv") == run_dir
    assert tracker.get_output("qv", "qv_report") == "/path/qv.txt"


def test_retrack_no_untracked_run_errors(tmp_path, dry_run_dir, _patch_registry_dir):
    _seed_ticket(dry_run_dir, tmp_path, ticket_id="RC-DRY", tol_id="xbDry1")

    runner = CliRunner()
    result = runner.invoke(cli, ["--dry-run", "retrack", "-t", "RC-DRY", "-s", "qv"])

    assert result.exit_code == 1
    assert "No untracked runs found" in result.output


def test_untrack_dry_run_does_not_touch_default_registry(
    tmp_path, dry_run_dir, _patch_registry_dir
):
    # Ticket only exists in the default registry — a --dry-run untrack must not find it.
    _seed_ticket(_patch_registry_dir, tmp_path, ticket_id="RC-REAL", tol_id="xbReal1")

    runner = CliRunner()
    result = runner.invoke(cli, ["--dry-run", "untrack", "-t", "RC-REAL", "-s", "qv"])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_status_dry_run_ticket_history_reads_from_dry_run_registry(
    tmp_path, dry_run_dir, _patch_registry_dir, user_config_path
):
    """`grit --dry-run status -t <ticket>` must surface step history via the
    dry-run-isolated registry (show_ticket_history's own RunTracker(workdir) call),
    not the real default registry that _patch_registry_dir points elsewhere."""
    from grit.core.run_tracker import RunTracker

    reg, workdir = _seed_ticket(dry_run_dir, tmp_path, ticket_id="RC-DRY", tol_id="xbDry1")
    tracker = RunTracker(workdir, registry=reg)
    run_dir = tracker.start("rename_and_orient", "RC-DRY", "xbDry1")
    tracker.finish("rename_and_orient", run_dir, "success")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--config", str(user_config_path), "--dry-run", "status", "-t", "RC-DRY"]
    )

    assert result.exit_code == 0, result.output
    assert "rename_and_orient" in result.output
    assert "success" in result.output


def test_status_default_ticket_history_does_not_see_dry_run_ticket(
    tmp_path, dry_run_dir, _patch_registry_dir, user_config_path
):
    # Ticket only exists in the dry-run registry — a plain `status -t` must not find it.
    _seed_ticket(dry_run_dir, tmp_path, ticket_id="RC-DRY", tol_id="xbDry1")

    runner = CliRunner()
    result = runner.invoke(cli, ["--config", str(user_config_path), "status", "-t", "RC-DRY"])

    assert result.exit_code == 0, result.output
    assert "not found" in result.output


def test_status_dry_run_passes_dry_run_flag_into_context(
    tmp_path, dry_run_dir, _patch_registry_dir, user_config_path, monkeypatch
):
    """status_cmd must thread `dry_run=True` into show_ticket_history's
    CurationContext.from_ticket(...) call."""
    _seed_ticket(dry_run_dir, tmp_path, ticket_id="RC-DRY", tol_id="xbDry1")

    captured = {}

    def fake_from_ticket(cls, ticket_id, user_config, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop before any real Jira/context work")

    monkeypatch.setattr(
        "grit.core.context.CurationContext.from_ticket", classmethod(fake_from_ticket)
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["--config", str(user_config_path), "--dry-run", "status", "-t", "RC-DRY"]
    )

    assert result.exit_code == 0, result.output
    assert captured.get("dry_run") is True


# ---------------------------------------------------------------------------
# --dry-run guard on plain (non-GritCommand) registry-mutating commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["done", "-t", "RC-REAL"],
        ["reopen", "-t", "RC-REAL"],
        ["remove", "-t", "RC-REAL", "--yes"],
    ],
)
def test_dry_run_guard_rejects_and_leaves_real_registry_untouched(
    args, tmp_path, _patch_registry_dir
):
    """`grit --dry-run <cmd>` for done/reopen/remove must refuse outright
    rather than silently operating on the real registry/workdir."""
    reg, workdir = _seed_ticket(_patch_registry_dir, tmp_path, ticket_id="RC-REAL")

    runner = CliRunner()
    result = runner.invoke(cli, ["--dry-run", *args])

    assert result.exit_code != 0
    assert "--dry-run is not supported" in result.output
    # Ticket and workdir must survive untouched.
    entry = reg.find_ticket("RC-REAL")
    assert entry is not None
    assert entry.get("status") != "done"
    assert workdir.exists()
