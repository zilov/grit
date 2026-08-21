"""Tests for `grit status` / `grit untrack` --dry-run isolation.

Follows the CliRunner + _DEFAULT_DIR-monkeypatch pattern established in
tests/test_remove_cmd.py.
"""

import pytest
from click.testing import CliRunner

from grit.core.click_cli import cli
from grit.core.registry import RegistryManager


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


def test_untrack_dry_run_does_not_touch_default_registry(
    tmp_path, dry_run_dir, _patch_registry_dir
):
    # Ticket only exists in the default registry — a --dry-run untrack must not find it.
    _seed_ticket(_patch_registry_dir, tmp_path, ticket_id="RC-REAL", tol_id="xbReal1")

    runner = CliRunner()
    result = runner.invoke(cli, ["--dry-run", "untrack", "-t", "RC-REAL", "-s", "qv"])

    assert result.exit_code == 1
    assert "not found" in result.output
