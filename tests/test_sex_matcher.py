"""Tests for run_sex_matcher's handling of stale 'started' history entries."""

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from grit.steps.pre_curation.sex_matcher import run_sex_matcher


def _base_ctx(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.workdir.mkdir()
    mock_ctx.tol_id = "ilHelSara1"
    mock_ctx.print_only = False
    return mock_ctx


@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_started_entry_with_existing_output_resolves_to_success(mock_bsub, mock_ctx, tmp_path):
    ctx = _base_ctx(mock_ctx, tmp_path)
    (ctx.workdir / "Best_match.txt").write_text("done")

    tracker = MagicMock()
    tracker.history.return_value = [
        {"status": "started", "run_dir": str(ctx.workdir / "sex_matcher" / "run1"), "job_id": "1"}
    ]
    ctx.tracker = tracker

    run_sex_matcher(ctx)

    tracker.finish.assert_called_once_with(
        "sex_matcher", ctx.workdir / "sex_matcher" / "run1", "success"
    )
    mock_bsub.assert_not_called()


@patch("grit.steps.pre_curation.sex_matcher._check_bjobs")
@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_started_entry_with_live_job_skips_resubmit(
    mock_bsub, mock_check_bjobs, mock_ctx, tmp_path
):
    ctx = _base_ctx(mock_ctx, tmp_path)

    tracker = MagicMock()
    tracker.history.return_value = [
        {"status": "started", "run_dir": str(ctx.workdir / "sex_matcher" / "run1"), "job_id": "42"}
    ]
    ctx.tracker = tracker
    mock_check_bjobs.return_value = {"42": "RUN"}

    run_sex_matcher(ctx)

    tracker.finish.assert_not_called()
    mock_bsub.assert_not_called()


@patch("grit.steps.pre_curation.sex_matcher._check_bjobs")
@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_started_entry_with_dead_job_and_no_output_resubmits(
    mock_bsub, mock_check_bjobs, mock_ctx, tmp_path
):
    ctx = _base_ctx(mock_ctx, tmp_path)

    (ctx.workdir / "original.fa").write_text("fa")
    run2 = ctx.workdir / "sex_matcher" / "run2"
    run2.mkdir(parents=True)

    tracker = MagicMock()
    tracker.history.return_value = [
        {"status": "started", "run_dir": str(ctx.workdir / "sex_matcher" / "run1"), "job_id": "42"}
    ]
    ctx.tracker = tracker
    ctx.tracker.start.return_value = run2
    mock_check_bjobs.return_value = {"42": "gone"}
    mock_bsub.return_value = "99"

    run_sex_matcher(ctx)

    tracker.finish.assert_called_once_with(
        "sex_matcher", ctx.workdir / "sex_matcher" / "run1", "failed"
    )
    mock_bsub.assert_called_once()


@patch("grit.steps.pre_curation.sex_matcher._check_bjobs")
@patch("grit.steps.pre_curation.sex_matcher._submit_bsub")
def test_dry_run_short_circuits_before_idempotency_and_tolid_checks(
    mock_bsub, mock_check_bjobs, mock_ctx, tmp_path
):
    """dry_run must sit before the tol_id-prefix validation and before any
    tracker-history/bjobs idempotency check — a bogus tol_id and a stale
    'started' history entry must not stop the dry-run branch."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    ctx = mock_ctx
    ctx.workdir = tmp_path
    # Genuinely fails the real check: lowercased ("xxnotaninsect1") does not
    # start with any of _INSECT_PREFIXES ("ic", "il", "id", "n").
    ctx.tol_id = "xxNotAnInsect1"
    ctx.print_only = False
    registry = RegistryManager(registry_dir=tmp_path / "registry")
    registry.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, ctx.workdir)
    ctx.tracker = RunTracker(tmp_path, registry=registry)
    ctx.dry_run = True

    run_sex_matcher(ctx)

    mock_bsub.assert_not_called()
    mock_check_bjobs.assert_not_called()

    history = ctx.tracker.history("sex_matcher")
    assert history[-1]["status"] == "success"
    placeholder = Path(history[-1]["run_dir"]) / "Best_match_to_Z_is_HAP1_SCAFFOLD_12"
    assert placeholder.exists()


# ---------------------------------------------------------------------------
# sex-matcher.sh — its exit status is the epilogue's success signal
# ---------------------------------------------------------------------------

_SCRIPT = Path(__file__).parent.parent / "grit" / "scripts" / "sex-matcher.sh"
_FAKE_BUSCO = "mkdir -p busco5/run_x && echo busco1 > busco5/run_x/full_table.tsv\n"


def _sandboxed_script(tmp_path, *, busco_ok=True, match_ok=True):
    """Copy sex-matcher.sh with its site paths swapped for fakes; return (script, run_dir, env)."""
    fakes = tmp_path / "fakes"
    (fakes / "bin").mkdir(parents=True)
    for name in ("coleop_X_buscos", "lep_Z_buscos", "dip_LG6", "nematode_X_buscos"):
        (fakes / name).write_text("busco1\n")
    singularity = fakes / "bin" / "singularity"
    singularity.write_text("#!/bin/sh\n" + (_FAKE_BUSCO if busco_ok else "exit 1\n"))
    matcher = fakes / "sex_matcher.py"
    matcher.write_text("#!/bin/sh\n" + ("echo hit > Best_match_1.txt\n" if match_ok else ""))
    for exe in (singularity, matcher):
        exe.chmod(0o755)
    body = (
        _SCRIPT.read_text()
        .replace("source /nfs/users/nfs_m/mh6/sing.bash", ":")
        .replace("/nfs/users/nfs_d/da16/vgp_curation_scripts/", f"{fakes}/")
        .replace("/software/grit/projects/vgp_curation_scripts/sex_matcher.py", str(matcher))
    )
    script = tmp_path / "sex-matcher.sh"
    script.write_text(body)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "original.fa").write_text(">s\nACGT\n")
    env = {**os.environ, "PATH": f"{fakes / 'bin'}{os.pathsep}{os.environ['PATH']}"}
    return script, run_dir, env


def _run_script(script, run_dir, env, tol_id="ilHelSara1"):
    return subprocess.run(
        ["bash", str(script), tol_id], cwd=run_dir, env=env, capture_output=True, text=True
    )


def test_sex_matcher_script_exits_zero_when_it_writes_best_match(tmp_path):
    script, run_dir, env = _sandboxed_script(tmp_path)
    result = _run_script(script, run_dir, env)
    assert result.returncode == 0, result.stderr
    assert list(run_dir.glob("Best_match*"))


def test_sex_matcher_script_fails_when_busco_fails(tmp_path):
    script, run_dir, env = _sandboxed_script(tmp_path, busco_ok=False)
    assert _run_script(script, run_dir, env).returncode != 0


def test_sex_matcher_script_fails_when_no_best_match_is_written(tmp_path):
    script, run_dir, env = _sandboxed_script(tmp_path, match_ok=False)
    assert _run_script(script, run_dir, env).returncode != 0


def test_sex_matcher_script_fails_for_an_unsupported_tol_id(tmp_path):
    script, run_dir, env = _sandboxed_script(tmp_path)
    assert _run_script(script, run_dir, env, tol_id="mMusMus1").returncode != 0
