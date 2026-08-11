"""Tests for the `grit remove` CLI command."""

import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from grit.core.click_cli import cli
from grit.core.registry import RegistryManager


@pytest.fixture(autouse=True)
def _patch_registry_dir(tmp_path, monkeypatch):
    """remove_cmd constructs RegistryManager() with no args, so point the
    default registry dir at tmp_path for the duration of each test."""
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def reg(tmp_path):
    return RegistryManager(registry_dir=tmp_path)


def _seed_ticket(reg, tmp_path, ticket_id="RC-1234", tol_id="xbTest1"):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "dummy.txt").write_text("data")
    reg.add_ticket(ticket_id, tol_id, "species", workdir)
    return workdir


def test_remove_confirmed_deletes_workdir_and_entry(reg, tmp_path):
    workdir = _seed_ticket(reg, tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["remove", "-t", "RC-1234"], input="RC-1234\n")

    assert result.exit_code == 0, result.output
    assert not workdir.exists()
    assert reg.find_ticket("RC-1234") is None


def test_remove_confirmation_mismatch_deletes_nothing(reg, tmp_path):
    workdir = _seed_ticket(reg, tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["remove", "-t", "RC-1234"], input="WRONG\n")

    assert result.exit_code == 1
    assert workdir.exists()
    assert reg.find_ticket("RC-1234") is not None


def test_remove_yes_skips_prompt(reg, tmp_path):
    workdir = _seed_ticket(reg, tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["remove", "-t", "RC-1234", "--yes"])

    assert result.exit_code == 0, result.output
    assert not workdir.exists()
    assert reg.find_ticket("RC-1234") is None


def test_remove_ticket_not_found(reg, tmp_path):
    runner = CliRunner()

    result = runner.invoke(cli, ["remove", "-t", "RC-9999", "--yes"])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_remove_workdir_already_missing_still_removes_entry(reg, tmp_path):
    workdir = _seed_ticket(reg, tmp_path)
    shutil.rmtree(workdir)
    assert not workdir.exists()
    runner = CliRunner()

    result = runner.invoke(cli, ["remove", "-t", "RC-1234", "--yes"])

    assert result.exit_code == 0, result.output
    assert reg.find_ticket("RC-1234") is None


def test_remove_path_guard_refuses_home_workdir(reg, tmp_path):
    _seed_ticket(reg, tmp_path)
    tickets = reg._load()
    tickets[0]["workdir"] = str(Path.home())
    reg._save(tickets)
    runner = CliRunner()

    result = runner.invoke(cli, ["remove", "-t", "RC-1234", "--yes"])

    assert result.exit_code == 1
    assert reg.find_ticket("RC-1234") is not None
