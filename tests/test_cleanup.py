"""Tests for grit/core/cleanup.py."""

from unittest.mock import patch

from click.testing import CliRunner

from grit.core.cleanup import plan_cleanup, run_cleanup
from grit.core.click_cli import cli


class _FakeTracker:
    """Minimal tracker stub: no tracked run_dir, forces filesystem fallback (alphabetical last)."""

    def latest_run_dir(self, step):
        return None


def _actions_for(kind, actions):
    return [p for k, p in actions if k == kind]


def test_fastk_index_files_in_kept_dir_are_flagged_delete(tmp_path):
    workdir = tmp_path / "workdir"
    run_dir = workdir / "hic_remapping" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / ".foo.ktab.1").write_text("x")
    (run_dir / ".foo.post.3").write_text("x")
    (run_dir / "unrelated.txt").write_text("keep me alone")

    actions = plan_cleanup(workdir, "tolId1", _FakeTracker())

    deleted = _actions_for("delete", actions)
    assert run_dir / ".foo.ktab.1" in deleted
    assert run_dir / ".foo.post.3" in deleted
    # non-FastK, non-special files in a generic kept step dir are left alone
    assert run_dir / "unrelated.txt" not in deleted


def test_nextflow_scratch_in_kept_dir_is_deleted(tmp_path):
    workdir = tmp_path / "workdir"
    run_dir = workdir / "hic_remapping" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "work" / "ab").mkdir(parents=True)
    (run_dir / ".nextflow" / "cache").mkdir(parents=True)
    (run_dir / ".nextflow.log").write_text("log")
    (run_dir / ".nextflow.log.1").write_text("old log")

    actions = plan_cleanup(workdir, "tolId1", _FakeTracker())

    deleted = _actions_for("delete", actions)
    assert run_dir / "work" in deleted
    assert run_dir / ".nextflow" in deleted
    assert run_dir / ".nextflow.log" in deleted
    assert run_dir / ".nextflow.log.1" in deleted


def test_nextflow_scratch_in_old_run_dir_not_double_planned(tmp_path):
    """A work/ or .nextflow dir nested inside a non-kept (fully deleted) run dir
    must not also get its own delete action — it'll vanish with its parent, and
    a second delete attempt on an already-gone path would surface as a spurious
    error during execution."""
    workdir = tmp_path / "workdir"
    step_dir = workdir / "fastga"
    old_run = step_dir / "2026-01-01T00_00_00"
    new_run = step_dir / "2026-02-01T00_00_00"
    for run in (old_run, new_run):
        run.mkdir(parents=True)
    (old_run / "work" / "ab").mkdir(parents=True)
    (old_run / ".nextflow" / "cache").mkdir(parents=True)
    (old_run / ".nextflow.log").write_text("log")

    actions = plan_cleanup(workdir, "tolId1", _FakeTracker())

    deleted = _actions_for("delete", actions)
    assert old_run in deleted
    assert old_run / "work" not in deleted
    assert old_run / ".nextflow" not in deleted
    assert old_run / ".nextflow.log" not in deleted


def test_find_reference_kept_dir_truncate_and_delete(tmp_path):
    workdir = tmp_path / "workdir"
    run_dir = workdir / "find_reference" / "run1"
    run_dir.mkdir(parents=True)

    reheader = run_dir / "GCA_123_reheader.fna"
    reheader.write_text("ACGT" * 100)

    empty_reheader = run_dir / "GCA_empty_reheader.fna"
    empty_reheader.write_text("")

    raw_ref = run_dir / "GCA_123_genomic.fna"
    raw_ref.write_text("raw reference data")

    idx_file = run_dir / "GCA_123.bps"
    idx_file.write_text("index")

    ktab_file = run_dir / ".GCA_123.ktab.1"
    ktab_file.write_text("x")

    actions = plan_cleanup(workdir, "tolId1", _FakeTracker())

    truncated = _actions_for("truncate", actions)
    deleted = _actions_for("delete", actions)

    assert truncated == [reheader]
    assert empty_reheader not in truncated
    assert empty_reheader not in deleted  # already empty — no-op, not cluttered into the plan
    assert raw_ref in deleted
    assert idx_file in deleted
    assert ktab_file in deleted  # handled once via the generic FastK pass


def test_pretext_to_asm_kept_dir_gzips_nonzero_fa_only(tmp_path):
    workdir = tmp_path / "workdir"
    run_dir = workdir / "pretext_to_asm" / "run1"
    run_dir.mkdir(parents=True)

    curated = run_dir / "tolId1.hap1.primary.curated.fa"
    curated.write_text("ACGT" * 1000)

    empty_haplotigs = run_dir / "tolId1.all_haplotigs.curated.fa"
    empty_haplotigs.write_text("")

    actions = plan_cleanup(workdir, "tolId1", _FakeTracker())

    gzipped = _actions_for("gzip", actions)
    assert gzipped == [curated]
    assert empty_haplotigs not in gzipped
    assert not any(k == "delete" and p == empty_haplotigs for k, p in actions)


@patch("grit.core.cleanup._submit_bsub")
@patch("grit.core.cleanup.RegistryManager")
def test_run_cleanup_submits_one_gzip_job_per_pretext_to_asm_dir(
    mock_registry_cls, mock_submit_bsub, tmp_path
):
    workdir = tmp_path / "workdir"
    run_dir = workdir / "pretext_to_asm" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "a.hap1.curated.fa").write_text("ACGT" * 10)
    (run_dir / "b.hap2.curated.fa").write_text("ACGT" * 10)

    mock_registry = mock_registry_cls.return_value
    mock_registry.done_tickets.return_value = [
        {"ticket_id": "RC-1", "tol_id": "tolId1", "workdir": str(workdir)}
    ]
    mock_submit_bsub.return_value = "12345"

    with patch("grit.core.cleanup.RunTracker", return_value=_FakeTracker()):
        run_cleanup(dry_run=False)

    mock_submit_bsub.assert_called_once()
    inner_cmd = mock_submit_bsub.call_args[0][0]
    assert "pigz -p 8 *.fa" in inner_cmd
    assert str(run_dir) in inner_cmd


@patch("grit.core.cleanup._submit_bsub")
@patch("grit.core.cleanup.RegistryManager")
def test_run_cleanup_dry_run_does_not_submit_gzip_job(
    mock_registry_cls, mock_submit_bsub, tmp_path
):
    workdir = tmp_path / "workdir"
    run_dir = workdir / "pretext_to_asm" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "a.hap1.curated.fa").write_text("ACGT" * 10)

    mock_registry = mock_registry_cls.return_value
    mock_registry.done_tickets.return_value = [
        {"ticket_id": "RC-1", "tol_id": "tolId1", "workdir": str(workdir)}
    ]

    with patch("grit.core.cleanup.RunTracker", return_value=_FakeTracker()):
        run_cleanup(dry_run=True)

    mock_submit_bsub.assert_not_called()


@patch("grit.core.cleanup.RegistryManager")
def test_run_cleanup_passes_include_cleaned_to_done_tickets(mock_registry_cls, tmp_path):
    mock_registry = mock_registry_cls.return_value
    mock_registry.done_tickets.return_value = []

    run_cleanup(dry_run=True, include_cleaned=True)

    mock_registry.done_tickets.assert_called_once_with(limit=None, include_cleaned=True)


@patch("grit.core.cleanup._submit_bsub")
@patch("grit.core.cleanup.RegistryManager")
def test_run_cleanup_marks_ticket_cleaned_up_when_actions_succeed(
    mock_registry_cls, mock_submit_bsub, tmp_path
):
    workdir = tmp_path / "workdir"
    run_dir = workdir / "pretext_to_asm" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / "a.hap1.curated.fa").write_text("ACGT" * 10)

    mock_registry = mock_registry_cls.return_value
    mock_registry.done_tickets.return_value = [
        {"ticket_id": "RC-1", "tol_id": "tolId1", "workdir": str(workdir)}
    ]
    mock_submit_bsub.return_value = "12345"

    with patch("grit.core.cleanup.RunTracker", return_value=_FakeTracker()):
        run_cleanup(dry_run=False)

    mock_registry.mark_cleaned_up.assert_called_once_with("RC-1")


@patch("grit.core.cleanup.RegistryManager")
def test_run_cleanup_marks_ticket_cleaned_up_when_nothing_to_clean(mock_registry_cls, tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    mock_registry = mock_registry_cls.return_value
    mock_registry.done_tickets.return_value = [
        {"ticket_id": "RC-1", "tol_id": "tolId1", "workdir": str(workdir)}
    ]

    with patch("grit.core.cleanup.RunTracker", return_value=_FakeTracker()):
        run_cleanup(dry_run=False)

    mock_registry.mark_cleaned_up.assert_called_once_with("RC-1")


@patch("grit.core.cleanup.RegistryManager")
def test_run_cleanup_does_not_mark_cleaned_up_dry_run(mock_registry_cls, tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    mock_registry = mock_registry_cls.return_value
    mock_registry.done_tickets.return_value = [
        {"ticket_id": "RC-1", "tol_id": "tolId1", "workdir": str(workdir)}
    ]

    with patch("grit.core.cleanup.RunTracker", return_value=_FakeTracker()):
        run_cleanup(dry_run=True)

    mock_registry.mark_cleaned_up.assert_not_called()


@patch("grit.core.cleanup.RegistryManager")
def test_run_cleanup_does_not_mark_cleaned_up_on_delete_error(mock_registry_cls, tmp_path):
    workdir = tmp_path / "workdir"
    run_dir = workdir / "hic_remapping" / "run1"
    run_dir.mkdir(parents=True)
    (run_dir / ".foo.ktab.1").write_text("x")

    mock_registry = mock_registry_cls.return_value
    mock_registry.done_tickets.return_value = [
        {"ticket_id": "RC-1", "tol_id": "tolId1", "workdir": str(workdir)}
    ]

    with (
        patch("grit.core.cleanup.RunTracker", return_value=_FakeTracker()),
        patch("pathlib.Path.unlink", side_effect=OSError("boom")),
    ):
        run_cleanup(dry_run=False)

    mock_registry.mark_cleaned_up.assert_not_called()


def test_cleanup_cmd_rejects_dry_run(monkeypatch, tmp_path):
    """`grit --dry-run cleanup` must refuse rather than scanning the real registry."""
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", tmp_path)

    runner = CliRunner()
    result = runner.invoke(cli, ["--dry-run", "cleanup"])

    assert result.exit_code != 0
    assert "--dry-run is not supported" in result.output
