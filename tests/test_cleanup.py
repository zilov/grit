"""Tests for grit/core/cleanup.py."""

from unittest.mock import patch

from grit.core.cleanup import plan_cleanup, run_cleanup


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
