"""Tests for -t shell completion, ToL ID resolution and `grit init`'s bashrc snippet."""

import json
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from grit.config import init
from grit.core import registry as registry_mod
from grit.core.click_cli import cli
from grit.core.registry import RegistryManager, complete_ticket


def _ticket(ticket_id, tol_id, status="in_curation", workdir=None):
    return {
        "ticket_id": ticket_id,
        "tol_id": tol_id,
        "workdir": workdir or f"/w/{tol_id}",
        "status": status,
    }


@pytest.fixture
def reg_dir(tmp_path, monkeypatch):
    """Point the default registry at an isolated dir seeded with three tickets."""
    d = tmp_path / ".grit"
    d.mkdir()
    (d / "grit_registry.json").write_text(
        json.dumps(
            [
                _ticket("RC-1", "ilFoo1"),
                _ticket("RC-2", "xxBar1"),
                _ticket("RC-3", "ilOld1", status="done"),
            ]
        )
    )
    monkeypatch.setattr(registry_mod, "_DEFAULT_DIR", d)
    monkeypatch.setenv("HOME", str(tmp_path))
    return d


def _ctx(command="qv"):
    root = SimpleNamespace(params={"dry_run": False})
    return SimpleNamespace(find_root=lambda: root, command=SimpleNamespace(name=command))


def test_complete_prefix_rc_returns_active_ticket_ids(reg_dir):
    assert complete_ticket(_ctx(), None, "RC") == ["RC-1", "RC-2"]


def test_complete_returns_both_forms(reg_dir):
    assert set(complete_ticket(_ctx(), None, "")) == {"RC-1", "ilFoo1", "RC-2", "xxBar1"}
    assert complete_ticket(_ctx(), None, "il") == ["ilFoo1"]


def test_complete_reopen_offers_done_only(reg_dir):
    assert complete_ticket(_ctx("reopen"), None, "") == ["RC-3", "ilOld1"]


def test_complete_corrupt_registry_returns_empty(reg_dir):
    (reg_dir / "grit_registry.json").write_text("{not json")
    assert complete_ticket(_ctx(), None, "") == []


def test_resolve_ticket_passthrough_and_tol_id(reg_dir):
    reg = RegistryManager()
    assert reg.resolve_ticket("RC-2") == "RC-2"
    assert reg.resolve_ticket("ilFoo1") == "RC-1"
    assert reg.resolve_ticket("ilOld1") == "RC-3"  # done-only match, for reopen
    assert reg.resolve_ticket("RC-9999") == "RC-9999"


def test_resolve_ticket_prefers_single_active(tmp_path):
    reg = RegistryManager(registry_dir=tmp_path)
    reg._save([_ticket("RC-1", "ilFoo1", "done"), _ticket("RC-5", "ilFoo1", workdir="/w/ilFoo1.2")])
    assert reg.resolve_ticket("ilFoo1") == "RC-5"


def test_resolve_ticket_rerelease_ambiguity(tmp_path):
    reg = RegistryManager(registry_dir=tmp_path)
    reg._save(
        [
            _ticket("RC-1", "ilFoo1", "done"),
            _ticket("RC-5", "ilFoo1", "done", workdir="/w/ilFoo1.2"),
        ]
    )
    with pytest.raises(click.UsageError, match=r"RC-1 \(ilFoo1, done\)"):
        reg.resolve_ticket("ilFoo1")


def test_bash_complete_end_to_end(reg_dir):
    result = CliRunner().invoke(
        cli,
        env={"_GRIT_COMPLETE": "bash_complete", "COMP_WORDS": "grit qv -t RC", "COMP_CWORD": "3"},
        prog_name="grit",
    )
    assert result.output.split() == ["plain,RC-1", "plain,RC-2"]


def test_enable_completion_is_idempotent(tmp_path):
    bashrc = tmp_path / ".bashrc"
    bashrc.write_text("export X=1")
    assert init.enable_completion(bashrc)
    assert not init.enable_completion(bashrc)
    assert bashrc.read_text() == "export X=1\n" + init.COMPLETION_SNIPPET


def test_init_offers_completion_when_config_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    config = tmp_path / "cfg.yaml"
    config.write_text("x: 1")
    monkeypatch.setattr(init, "DEFAULT_CONFIG_PATH", config)
    result = CliRunner().invoke(cli, ["init"], input="y\n")
    assert "already exists" in result.output
    assert init.COMPLETION_SNIPPET in (tmp_path / ".bashrc").read_text()
