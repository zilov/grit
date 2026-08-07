"""
Print-only smoke test — invokes every grit subcommand via CliRunner with
--print-only, mirroring tests/local_smoke_test.sh's coverage.

No external tool (bsub, pretext-to-asm, kmer_completeness.bash, etc.) is
executed and no HPC/NFS access is needed — this only exercises the path from
YAML parsing -> CurationContext -> command construction -> tracker/registry
bookkeeping, catching regressions that only surface once a real command is
built (e.g. a KeyError in an f-string, a missing ctx field).

Deliberately excludes commands that check for a prior step's real output
even in --print-only mode (add-gap-track, add-telo-track, fastga,
blast-contaminants, hic-remapping, rename-and-orient — each raises
FileNotFoundError against genuine farm paths) and sex-matcher (this fixture's
tol_id is an algae, not an insect, so it correctly exits 1 by design). Those
require actual prior pipeline output and are covered by
tests/local_smoke_test.sh run manually on the farm, not by this hermetic test.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from grit.core.click_cli import cli

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG = FIXTURES / "test_config.yaml"
HAP_YAML = FIXTURES / "uoEpiScra1_hap1_hap2.yaml"
PRIMARY_YAML = FIXTURES / "xbLimHian1_primary.yaml"

HAP_COMMANDS = [
    "setup",
    "find-reference",
    "pretext-to-asm",
    "haplotig-files",
    "qv",
    "finalize-qc",
]

PRIMARY_COMMANDS = [
    "setup",
    "find-reference",
]


def _invoke(yaml_path: Path, command: str):
    runner = CliRunner()
    return runner.invoke(
        cli,
        ["--config", str(CONFIG), "--print-only", "--yaml", str(yaml_path), command],
    )


def _assert_clean(result):
    assert result.exception is None, result.output
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", HAP_COMMANDS)
def test_hap_command_print_only(command):
    _assert_clean(_invoke(HAP_YAML, command))


@pytest.mark.parametrize("command", PRIMARY_COMMANDS)
def test_primary_command_print_only(command):
    _assert_clean(_invoke(PRIMARY_YAML, command))


def test_cli_help():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
