"""from_ticket caches the Jira fields it reads in the registry and reuses them."""

from types import SimpleNamespace

import yaml

from grit.core.context import CurationContext
from grit.core.registry import RegistryManager
from tests.conftest import TEST_USER_CONFIG, TEST_YAML_HAP1


def _jira(yaml_path, calls):
    class FakeIssue:
        def __init__(self, ticket_id):
            calls.append(ticket_id)
            self.yaml = yaml.safe_load(yaml_path.read_text())
            self.issue_json = {
                "fields": {"customfield_11650": "TTAGGG", "customfield_13210": {"value": "2"}}
            }

        def get_release_version(self):
            return "2"

        def get_custom_field(self, name):
            return str(yaml_path)

    return SimpleNamespace(GritJiraIssue=FakeIssue)


def test_from_ticket_caches_jira_fields_and_refresh_bypasses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", tmp_path / "reg")
    yaml_path = tmp_path / "ticket.yaml"
    yaml_path.write_text(yaml.safe_dump(TEST_YAML_HAP1))
    RegistryManager().add_ticket("RC-1", "x", "", tmp_path)
    calls = []
    jira = _jira(yaml_path, calls)

    fresh = CurationContext.from_ticket("RC-1", TEST_USER_CONFIG, gritjiraissue_module=jira)
    cached = CurationContext.from_ticket("RC-1", TEST_USER_CONFIG, gritjiraissue_module=jira)

    assert calls == ["RC-1"]
    assert RegistryManager().find_ticket("RC-1")["jira"] == {
        "yaml_path": str(yaml_path),
        "release_version": 2,
        "teloseq": "TTAGGG",
    }
    for ctx in (fresh, cached):
        assert ctx.release_version == 2 and ctx.teloseq == "--teloseq TTAGGG"
    assert fresh.workdir == cached.workdir
    assert fresh.chromosome_list_files == 2 and cached.chromosome_list_files is None

    refreshed = CurationContext.from_ticket(
        "RC-1", TEST_USER_CONFIG, gritjiraissue_module=jira, refresh_jira=True
    )
    assert calls == ["RC-1", "RC-1"] and refreshed.chromosome_list_files == 2


def test_from_ticket_does_not_cache_an_unregistered_ticket(tmp_path, monkeypatch):
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", tmp_path / "reg")
    yaml_path = tmp_path / "ticket.yaml"
    yaml_path.write_text(yaml.safe_dump(TEST_YAML_HAP1))
    calls = []

    jira = _jira(yaml_path, calls)
    for _ in range(2):
        CurationContext.from_ticket("RC-2", TEST_USER_CONFIG, gritjiraissue_module=jira)

    assert calls == ["RC-2", "RC-2"]
