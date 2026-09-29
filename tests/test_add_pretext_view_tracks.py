"""Tests for grit/steps/pre_curation/add_pretext_view_tracks.py."""

import re
import shutil
import subprocess
from unittest.mock import patch

import pytest

from grit.steps.pre_curation.add_pretext_view_tracks import add_telo_track


def _extract_awk_program(cmd: str) -> str:
    m = re.search(r"awk '(.*)' \|", cmd)
    assert m, f"no awk program found in generated command: {cmd}"
    return m.group(1)


@patch("grit.steps.pre_curation.add_pretext_view_tracks._run")
@patch("grit.steps.pre_curation.add_pretext_view_tracks._find_pretext_map_in_workdir")
def test_add_telo_track_builds_a_syntactically_valid_awk_program(
    mock_find_map, mock_run, mock_ctx, tmp_path
):
    """CORR-21: the telomere track's awk program must not be mis-escaped —
    prove it by actually running the generated program (skipped if awk isn't
    installed). Before the fix, awk received literal backslash-quote pairs
    and died with a syntax error."""
    mock_ctx.print_only = True
    mock_find_map.return_value = tmp_path / "sDipInt39.hap1.hr.pretext"

    add_telo_track(mock_ctx)

    cmd = mock_run.call_args[0][0]
    awk_program = _extract_awk_program(cmd)

    if shutil.which("awk") is None:
        pytest.skip("awk not installed")

    result = subprocess.run(
        ["awk", awk_program],
        input="chr1\t100\t200\nchr2\t500\t950\n",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "chr1\t100\t200\t100\nchr2\t500\t950\t450\n"
