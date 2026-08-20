"""Tests for grit/core/status.py."""

from unittest.mock import patch

from grit.core.context import CurationContext
from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.core.status import (
    _canonical_haps,
    _print_less_tips,
    _print_scp_tips,
    _resolve_canonical_files,
    show_ticket_history,
)
from tests.conftest import TEST_USER_CONFIG, TEST_YAML_HAP1


@patch("grit.core.status.print_tip")
def test_print_scp_tips_prints_for_successful_step_with_outputs(mock_print_tip):
    step_latest = {
        "busco_synteny": {
            "status": "success",
            "outputs": {"png": "/lustre/foo/Rf_vs_Qu.png"},
        },
    }

    _print_scp_tips(step_latest, "farm22", "sDipInt39")

    mock_print_tip.assert_called_once()
    tip = mock_print_tip.call_args[0][0]
    assert "scp farm22:/lustre/foo/Rf_vs_Qu.png" in tip


@patch("grit.core.status.print_tip")
def test_print_scp_tips_hic_remapping_only_offers_normal_pretext(mock_print_tip):
    step_latest = {
        "hic_remapping": {
            "status": "success",
            "outputs": {
                "hap1_pretext": "/lustre/foo/aEleAbb1.hap1_hr.pretext",
                "hap1_normal_pretext": "/lustre/foo/aEleAbb1.hap1_normal.pretext",
            },
        },
    }

    _print_scp_tips(step_latest, "farm22", "aEleAbb1")

    mock_print_tip.assert_called_once()
    tip = mock_print_tip.call_args[0][0]
    assert "hr.pretext" not in tip
    assert (
        "scp farm22:/lustre/foo/aEleAbb1.hap1_normal.pretext "
        "~/curations/work/aEleAbb1/aEleAbb1.hap1_remapped.pretext" in tip
    )


@patch("grit.core.status.print_tip")
def test_print_scp_tips_hic_remapping_both_haps_prints_two_tips(mock_print_tip):
    step_latest = {
        "hic_remapping": {
            "status": "success",
            "outputs": {"hap1_normal_pretext": "/lustre/foo/aEleAbb1.hap1_normal.pretext"},
        },
        "hic_remapping_hap2": {
            "status": "success",
            "outputs": {"hap2_normal_pretext": "/lustre/foo/aEleAbb1.hap2_normal.pretext"},
        },
    }

    _print_scp_tips(step_latest, "farm22", "aEleAbb1")

    assert mock_print_tip.call_count == 2
    tips = [c.args[0] for c in mock_print_tip.call_args_list]
    assert any("aEleAbb1.hap1_remapped.pretext" in t for t in tips)
    assert any("aEleAbb1.hap2_remapped.pretext" in t for t in tips)


@patch("grit.core.status.print_tip")
def test_print_scp_tips_skips_step_without_outputs(mock_print_tip):
    step_latest = {"fastga": {"status": "success", "outputs": {}}}

    _print_scp_tips(step_latest, "farm22", "sDipInt39")

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_scp_tips_skips_failed_step(mock_print_tip):
    step_latest = {
        "fastga_synteny": {
            "status": "failed",
            "outputs": {"png": "/lustre/foo/plot.png"},
        },
    }

    _print_scp_tips(step_latest, "farm22", "sDipInt39")

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_scp_tips_skips_step_not_in_history(mock_print_tip):
    _print_scp_tips({}, "farm22", "sDipInt39")

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_less_tips_prints_for_successful_fastga(mock_print_tip):
    step_latest = {
        "fastga": {
            "status": "success",
            "outputs": {
                "paf": "/lustre/foo/Rf_vs_Qu.FastGA.paf",
                "top_targets_summary": "/lustre/foo/Rf_vs_Qu.top_targets_summary.txt",
            },
        },
    }

    _print_less_tips(step_latest)

    mock_print_tip.assert_called_once()
    tip = mock_print_tip.call_args[0][0]
    assert "less /lustre/foo/Rf_vs_Qu.top_targets_summary.txt" in tip


@patch("grit.core.status.print_tip")
def test_print_less_tips_skips_step_missing_summary_output(mock_print_tip):
    step_latest = {"fastga": {"status": "success", "outputs": {"paf": "/lustre/foo/x.paf"}}}

    _print_less_tips(step_latest)

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_less_tips_skips_failed_step(mock_print_tip):
    step_latest = {
        "fastga": {
            "status": "failed",
            "outputs": {"top_targets_summary": "/lustre/foo/x.top_targets_summary.txt"},
        },
    }

    _print_less_tips(step_latest)

    mock_print_tip.assert_not_called()


@patch("grit.core.status.print_tip")
def test_print_less_tips_skips_step_not_in_history(mock_print_tip):
    _print_less_tips({})

    mock_print_tip.assert_not_called()


def _make_failed_step(tmp_path, monkeypatch, step="fastga", log_name="e_fastga", log_text=""):
    # show_ticket_history() builds its own RunTracker() with the *default* RegistryManager,
    # so point that default at our tmp_path registry too.
    registry_dir = tmp_path / ".grit_reg"
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", registry_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg = RegistryManager(registry_dir=registry_dir)
    reg.add_ticket("RC-1234", "sDipInt39", "species", workdir)
    tracker = RunTracker(workdir, registry=reg)
    run_dir = tracker.start(step, "RC-1234", "sDipInt39")
    if log_text:
        (run_dir / log_name).write_text(log_text)
    tracker.finish(step, run_dir, "failed")
    return reg


def test_show_ticket_history_surfaces_term_memlimit(tmp_path, capsys, monkeypatch):
    reg = _make_failed_step(
        tmp_path,
        monkeypatch,
        log_text="TERM_MEMLIMIT: job killed after reaching LSF memory usage limit.\n",
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "TERM_MEMLIMIT" in out


def test_show_ticket_history_prints_memlimit_tip(tmp_path, capsys, monkeypatch):
    reg = _make_failed_step(
        tmp_path,
        monkeypatch,
        log_text="TERM_MEMLIMIT: job killed after reaching LSF memory usage limit.\n",
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "--bsub-ram" in out
    assert "fastga" in out


def test_show_ticket_history_no_reason_when_log_has_none(tmp_path, capsys, monkeypatch):
    reg = _make_failed_step(
        tmp_path, monkeypatch, log_text="Successfully completed some other step.\n"
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "TERM_" not in out
    assert "--bsub-ram" not in out


def test_show_ticket_history_no_reason_when_no_log(tmp_path, capsys, monkeypatch):
    reg = _make_failed_step(tmp_path, monkeypatch, log_text="")

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "TERM_" not in out


def _make_ticket(tmp_path, monkeypatch, tol_id, completed_steps=()):
    registry_dir = tmp_path / ".grit_reg"
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", registry_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg = RegistryManager(registry_dir=registry_dir)
    reg.add_ticket("RC-1234", tol_id, "species", workdir)
    tracker = RunTracker(workdir, registry=reg)
    for step in completed_steps:
        run_dir = tracker.start(step, "RC-1234", tol_id)
        tracker.finish(step, run_dir, "success")
    return reg


def test_show_ticket_history_prints_microchromosome_tip_for_bird_tol_id(tmp_path, monkeypatch):
    reg = _make_ticket(tmp_path, monkeypatch, "bColMon1")

    with patch("grit.core.status.print_tip") as mock_print_tip:
        show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    tips = [call.args[0] for call in mock_print_tip.call_args_list]
    assert any("microchromosome-second-shot" in t for t in tips)


def test_show_ticket_history_skips_microchromosome_tip_for_non_bird_tol_id(tmp_path, monkeypatch):
    reg = _make_ticket(tmp_path, monkeypatch, "sDipInt39")

    with patch("grit.core.status.print_tip") as mock_print_tip:
        show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    tips = [call.args[0] for call in mock_print_tip.call_args_list]
    assert not any("microchromosome-second-shot" in t for t in tips)


def test_show_ticket_history_skips_microchromosome_tip_once_second_shot_ran(tmp_path, monkeypatch):
    reg = _make_ticket(
        tmp_path, monkeypatch, "bColMon1", completed_steps=["microchromosome_second_shot"]
    )

    with patch("grit.core.status.print_tip") as mock_print_tip:
        show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    tips = [call.args[0] for call in mock_print_tip.call_args_list]
    assert not any("microchromosome-second-shot" in t for t in tips)


def test_show_ticket_history_resolves_done_job_without_waiting_for_gone(
    tmp_path, monkeypatch, capsys
):
    """hic_remapping has no bsub -Ep epilogue (curationpretext.sh submits its own job),
    so grit only learns of completion via bjobs polling. Once bjobs reports the job
    DONE, grit should verify+finish immediately rather than waiting for the job to
    age out of `bjobs` history (which can take hours) — and the scp tip should show
    up in that same `grit status` call, not just the next one."""
    tol_id = "aEleAbb1"
    registry_dir = tmp_path / ".grit_reg"
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", registry_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg = RegistryManager(registry_dir=registry_dir)
    reg.add_ticket("RC-1234", tol_id, "species", workdir)
    tracker = RunTracker(workdir, registry=reg)

    run_dir = tracker.start("hic_remapping", "RC-1234", tol_id, suffix="primary")
    tracker.record_job("hic_remapping", run_dir, "685359")

    maps_dir = run_dir / "pretext_maps_processed"
    maps_dir.mkdir(parents=True)
    (maps_dir / f"{tol_id}.hap1_hr.pretext").write_text("")
    (maps_dir / f"{tol_id}.hap1_normal.pretext").write_text("")

    with (
        patch("grit.utils.helpers._check_bjobs", return_value={"685359": "DONE"}),
        patch("grit.core.status.print_tip") as mock_print_tip,
    ):
        show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    assert "done (check)" not in out
    assert "success" in out

    tips = [call.args[0] for call in mock_print_tip.call_args_list]
    assert any("hap1_normal.pretext" in t for t in tips)

    history = tracker.history("hic_remapping")
    assert history[-1]["status"] == "success"


def test_canonical_haps_dual_hap():
    ctx = CurationContext.from_yaml("RC-1234", TEST_YAML_HAP1, TEST_USER_CONFIG)
    assert _canonical_haps(ctx) == ["hap1", "hap2"]


def test_resolve_canonical_files_missing_returns_none_per_type(mock_ctx):
    mock_ctx.tracker = None  # no tracker, no filesystem outputs anywhere

    resolved = _resolve_canonical_files(mock_ctx, _canonical_haps(mock_ctx))

    assert set(resolved.keys()) == {"hap1", "hap2"}
    for by_type in resolved.values():
        assert by_type == {"fa": None, "haplotigs": None, "chr_list": None}


def test_resolve_canonical_files_finds_curated_fa(tmp_path, mock_ctx):
    mock_ctx.tracker = None
    mock_ctx.workdir = tmp_path
    pta_dir = tmp_path / "pretext_to_asm" / "2025-06-02T14_00_00"
    pta_dir.mkdir(parents=True)
    fa_file = pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa"
    fa_file.write_text(">seq\nACGT\n")

    resolved = _resolve_canonical_files(mock_ctx, ["hap1"])

    assert resolved["hap1"]["fa"] == fa_file
    # No haplotigs/chr-list files were created here.
    assert resolved["hap1"]["haplotigs"] is None
    assert resolved["hap1"]["chr_list"] is None


def _make_ticket_with_ctx(tmp_path, monkeypatch, tol_id="sDipInt39"):
    """Build a workdir + registry + a CurationContext wired to the same tracker,
    and patch CurationContext.from_ticket (as called inside show_ticket_history)
    to return it — avoiding real Jira access."""
    registry_dir = tmp_path / ".grit_reg"
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", registry_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg = RegistryManager(registry_dir=registry_dir)
    reg.add_ticket("RC-1234", tol_id, "species", workdir)
    tracker = RunTracker(workdir, registry=reg)

    ctx = CurationContext.from_yaml("RC-1234", TEST_YAML_HAP1, TEST_USER_CONFIG)
    ctx.workdir = workdir
    ctx.tol_id = tol_id
    ctx.tracker = RunTracker(workdir, registry=reg)

    monkeypatch.setattr(
        "grit.core.context.CurationContext.from_ticket",
        classmethod(lambda cls, *a, **kw: ctx),
    )
    return reg, tracker


def test_show_ticket_history_marks_step_holding_canonical_output(tmp_path, monkeypatch, capsys):
    tol_id = "sDipInt39"
    reg, tracker = _make_ticket_with_ctx(tmp_path, monkeypatch, tol_id)

    pta_dir = tracker.start("pretext_to_asm", "RC-1234", tol_id)
    fa_file = pta_dir / f"{tol_id}.hap1.1.curated.fa"
    fa_file.write_text(">seq\nACGT\n")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(fa_file)})

    fastga_dir = tracker.start("fastga", "RC-1234", tol_id)
    other_file = fastga_dir / "other.paf"
    other_file.write_text("x")
    tracker.finish("fastga", fastga_dir, "success", outputs={"paf": str(other_file)})

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    lines = out.splitlines()

    pta_line = next(line for line in lines if "pretext_to_asm" in line and "success" in line)
    fastga_line = next(line for line in lines if "fastga" in line and "success" in line)

    assert "★" in pta_line
    assert "★" not in fastga_line


def test_show_ticket_history_no_marker_when_no_outputs_recorded(tmp_path, monkeypatch, capsys):
    tol_id = "sDipInt39"
    reg, tracker = _make_ticket_with_ctx(tmp_path, monkeypatch, tol_id)

    run_dir = tracker.start("setup_curation", "RC-1234", tol_id)
    tracker.finish("setup_curation", run_dir, "success")

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    lines = out.splitlines()

    setup_line = next(line for line in lines if "setup_curation" in line)
    agp_line = next(line for line in lines if "agp_copied" in line)

    assert "★" not in setup_line
    assert "★" not in agp_line
