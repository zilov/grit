"""Tests for grit/core/base_command.py — GritCommand's --bsub-ram wiring."""

import rich_click as click
from click.testing import CliRunner

from grit.core.base_command import GritCommand
from grit.core.click_cli import GlobalState


def _make_command(**kwargs):
    @click.command("dummy", cls=GritCommand, **kwargs)
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
