"""Tests for validate_files.py's --dry-run CLI wiring.

`validate-files` is not registered on the `cli` group today (see the commented-out
import/add_command lines in grit/core/click_cli.py) — so the command object is
invoked directly with CliRunner, following the pattern in tests/test_base_command.py,
rather than through the full `cli` group as in tests/test_click_cli.py.
"""

from unittest.mock import patch

from click.testing import CliRunner

from grit.core.click_cli import GlobalState
from grit.steps.post_curation.validate_files import validate_files_cmd


@patch("grit.core.click_cli.build_context")
def test_cli_validate_files_dry_run_runs_to_completion(mock_build_context, mock_ctx, tmp_path):
    """`--dry-run validate-files` must no longer raise UsageError and must run to
    completion (reporting missing files gracefully) even before qv's dry-run
    output exists."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.release_version = 1
    mock_ctx.assembly_curated_dir = tmp_path / "curated"
    mock_ctx.dry_run = True
    mock_ctx.print_only = False
    mock_build_context.return_value = mock_ctx

    runner = CliRunner()
    obj = GlobalState(dry_run=True)
    result = runner.invoke(validate_files_cmd, ["-t", "RC-1234", "--dry-run"], obj=obj)

    assert result.exit_code == 0, result.output
    assert "MISSING" in result.output
