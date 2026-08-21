"""Tests for grit/core/base_command.py — GritCommand's --bsub-ram wiring."""

import rich_click as click
from click.testing import CliRunner

from grit.core.base_command import GritCommand
from grit.core.click_cli import GlobalState


def _make_command(name="dummy", **kwargs):
    @click.command(name, cls=GritCommand, **kwargs)
    @click.pass_context
    def dummy_cmd(ctx):
        click.echo(f"bsub_ram={ctx.obj.bsub_ram}")

    return dummy_cmd


def _invoke(cmd, args):
    runner = CliRunner()
    obj = GlobalState()
    result = runner.invoke(cmd, args, obj=obj)
    return result, obj


def test_bsub_ram_default_shown_in_help():
    cmd = _make_command(bsub_ram_default=24000)
    result = CliRunner().invoke(cmd, ["--help"], obj=GlobalState())
    assert "--bsub-ram" in result.output
    assert "24000" in result.output


def test_bsub_ram_not_added_without_default_or_help():
    cmd = _make_command()
    result = CliRunner().invoke(cmd, ["--help"], obj=GlobalState())
    assert "--bsub-ram" not in result.output


def test_bsub_ram_override_sets_ctx_obj(tmp_path):
    cmd = _make_command(bsub_ram_default=24000)
    result, obj = _invoke(cmd, ["-t", "RC-1234", "--bsub-ram", "64000"])
    assert result.exit_code == 0, result.output
    assert obj.bsub_ram == 64000


def test_bsub_ram_left_none_when_not_passed(tmp_path):
    cmd = _make_command(bsub_ram_default=24000)
    result, obj = _invoke(cmd, ["-t", "RC-1234"])
    assert result.exit_code == 0, result.output
    assert obj.bsub_ram is None


def test_bsub_ram_custom_help_text():
    cmd = _make_command(
        bsub_ram_help="LSF memory limit in MB (default: auto-scaled by FASTA size)."
    )
    result = CliRunner().invoke(cmd, ["--help"], obj=GlobalState())
    assert "auto-scaled by" in result.output


def test_dry_run_shown_in_help():
    cmd = _make_command()
    result = CliRunner().invoke(cmd, ["--help"], obj=GlobalState())
    assert "--dry-run" in result.output


def test_dry_run_flag_sets_ctx_obj():
    # Must be a command in _DRY_RUN_SUPPORTED_COMMANDS or the invoke()-level
    # guard added for Finding 1 rejects it before the callback runs.
    cmd = _make_command(name="setup")
    runner = CliRunner()
    obj = GlobalState()
    result = runner.invoke(cmd, ["-t", "RC-1234", "--dry-run"], obj=obj)
    assert result.exit_code == 0, result.output
    assert obj.dry_run is True


def test_dry_run_left_false_when_not_passed():
    cmd = _make_command()
    runner = CliRunner()
    obj = GlobalState()
    result = runner.invoke(cmd, ["-t", "RC-1234"], obj=obj)
    assert result.exit_code == 0, result.output
    assert obj.dry_run is False


def test_dry_run_unsupported_command_name_rejected():
    """A GritCommand not in _DRY_RUN_SUPPORTED_COMMANDS must refuse --dry-run
    before its callback runs, rather than silently proceeding as a real run."""
    cmd = _make_command()  # registered as "dummy" — never in the supported set
    runner = CliRunner()
    obj = GlobalState()
    result = runner.invoke(cmd, ["-t", "RC-1234", "--dry-run"], obj=obj)
    assert result.exit_code != 0
    assert "--dry-run is not yet supported for 'dummy'" in result.output


def test_dry_run_supported_command_name_allowed():
    from grit.core.base_command import _DRY_RUN_SUPPORTED_COMMANDS

    @click.command("pretext-to-asm", cls=GritCommand)
    @click.pass_context
    def supported_cmd(ctx):
        click.echo("ran")

    assert supported_cmd.name in _DRY_RUN_SUPPORTED_COMMANDS
    runner = CliRunner()
    obj = GlobalState()
    result = runner.invoke(supported_cmd, ["-t", "RC-1234", "--dry-run"], obj=obj)
    assert result.exit_code == 0, result.output
    assert "ran" in result.output


def test_dry_run_with_print_only_allows_unsupported_command():
    """print_only takes precedence over dry_run — combined with --dry-run on an
    unsupported command, print_only alone is always safe to allow."""
    cmd = _make_command()  # "dummy" — unsupported for --dry-run alone
    runner = CliRunner()
    obj = GlobalState()
    result = runner.invoke(cmd, ["-t", "RC-1234", "--dry-run", "--print-only"], obj=obj)
    assert result.exit_code == 0, result.output
