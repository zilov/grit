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
    show_global_status,
    show_ticket_history,
)
from grit.utils.output import console
from tests.conftest import TEST_USER_CONFIG, TEST_YAML_HAP1, TEST_YAML_PRIMARY


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
def test_print_scp_tips_splits_multi_value_output_into_separate_files(mock_print_tip):
    """fastga's 'idx' output is a MULTI_OUTPUT_SEP-joined pair (ref + query
    dgenies index) — both must reach the scp command, not just one."""
    step_latest = {
        "fastga": {
            "status": "success",
            "outputs": {
                "idx": "/lustre/foo/ref_name.idx\n/lustre/foo/query_name.idx",
                "paf": "/lustre/foo/run.paf",
            },
        },
    }

    _print_scp_tips(step_latest, "farm22", "sDipInt39")

    mock_print_tip.assert_called_once()
    tip = mock_print_tip.call_args[0][0]
    assert "scp farm22:/lustre/foo/ref_name.idx" in tip
    assert "scp farm22:/lustre/foo/query_name.idx" in tip
    assert "scp farm22:/lustre/foo/run.paf" in tip


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

    assert "fa(1)" in pta_line
    assert "fa(" not in fastga_line


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

    for marker in ("fa(", "hap(", "chr("):
        assert marker not in setup_line
        assert marker not in agp_line


def test_show_ticket_history_disambiguates_fa_vs_haplotigs_chr_list_owners(
    tmp_path, monkeypatch, capsys
):
    """Reproduces the exact 4-row bug report: `pretext_to_asm_recurate[_hap2]` and
    `rename_and_orient[_hap2]` are BOTH genuinely canonical at once, but for
    different output types — recurate still owns haplotigs/chr_list, while
    rename_and_orient (run later, with a fresher fa) has taken over the fa. The
    old bare ★ marker could not tell these apart; the new per-type marker must."""
    import os

    monkeypatch.setattr(console, "width", 200)
    tol_id = "sDipInt39"
    reg, tracker = _make_ticket_with_ctx(tmp_path, monkeypatch, tol_id)

    def _write(path, mtime_offset):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(">seq\nACGT\n")
        now = tracker.workdir.stat().st_mtime
        os.utime(path, (now + mtime_offset, now + mtime_offset))

    recurate_dir = tracker.start("pretext_to_asm_recurate", "RC-1234", tol_id)
    recurate_hap = recurate_dir / f"{tol_id}.hap1.2.all_haplotigs.curated.fa"
    recurate_chr = recurate_dir / f"{tol_id}.hap1.2.chromosome.list.csv"
    _write(recurate_hap, 10)
    _write(recurate_chr, 10)
    tracker.finish(
        "pretext_to_asm_recurate",
        recurate_dir,
        "success",
        outputs={"hap1_haplotigs": str(recurate_hap), "hap1_chr_list": str(recurate_chr)},
    )

    recurate_hap2_dir = tracker.start("pretext_to_asm_recurate_hap2", "RC-1234", tol_id)
    recurate_hap2_hap = recurate_hap2_dir / f"{tol_id}.hap2.2.all_haplotigs.curated.fa"
    recurate_hap2_chr = recurate_hap2_dir / f"{tol_id}.hap2.2.chromosome.list.csv"
    _write(recurate_hap2_hap, 10)
    _write(recurate_hap2_chr, 10)
    tracker.finish(
        "pretext_to_asm_recurate_hap2",
        recurate_hap2_dir,
        "success",
        outputs={"hap2_haplotigs": str(recurate_hap2_hap), "hap2_chr_list": str(recurate_hap2_chr)},
    )

    rao_dir = tracker.start("rename_and_orient", "RC-1234", tol_id)
    rao_fa = rao_dir / f"{tol_id}.hap1.3.renamed.fa"
    _write(rao_fa, 20)
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    rao_hap2_dir = tracker.start("rename_and_orient_hap2", "RC-1234", tol_id)
    rao_hap2_fa = rao_hap2_dir / f"{tol_id}.hap2.3.renamed.fa"
    _write(rao_hap2_fa, 20)
    tracker.finish(
        "rename_and_orient_hap2", rao_hap2_dir, "success", outputs={"hap2_fa": str(rao_hap2_fa)}
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    lines = out.splitlines()

    recurate_line = next(
        line for line in lines if "pretext_to_asm_recurate " in line + " " and "success" in line
    )
    recurate_hap2_line = next(
        line for line in lines if "pretext_to_asm_recurate_hap2" in line and "success" in line
    )
    rao_line = next(
        line for line in lines if "rename_and_orient " in line + " " and "success" in line
    )
    rao_hap2_line = next(
        line for line in lines if "rename_and_orient_hap2" in line and "success" in line
    )

    # recurate rows: canonical for haplotigs + chr_list, NOT for fa.
    assert "hap(1)" in recurate_line
    assert "chr(1)" in recurate_line
    assert "fa(" not in recurate_line
    assert "hap(2)" in recurate_hap2_line
    assert "chr(2)" in recurate_hap2_line
    assert "fa(" not in recurate_hap2_line

    # rename_and_orient rows: canonical for fa only, NOT haplotigs/chr_list.
    assert "fa(1)" in rao_line
    assert "hap(" not in rao_line
    assert "chr(" not in rao_line
    assert "fa(2)" in rao_hap2_line
    assert "hap(" not in rao_hap2_line
    assert "chr(" not in rao_hap2_line


def test_show_ticket_history_marker_shows_multiple_types_from_one_step(
    tmp_path, monkeypatch, capsys
):
    """When a single step's row owns more than one canonical output type at once
    (the common case — pretext_to_asm producing fa + haplotigs + chr_list together),
    the marker lists every owned type on that one row."""
    monkeypatch.setattr(console, "width", 200)
    tol_id = "sDipInt39"
    reg, tracker = _make_ticket_with_ctx(tmp_path, monkeypatch, tol_id)

    pta_dir = tracker.start("pretext_to_asm", "RC-1234", tol_id)
    fa_file = pta_dir / f"{tol_id}.hap1.1.curated.fa"
    hap_file = pta_dir / f"{tol_id}.hap1.1.all_haplotigs.curated.fa"
    chr_file = pta_dir / f"{tol_id}.hap1.1.chromosome.list.csv"
    for f in (fa_file, hap_file, chr_file):
        f.write_text(">seq\nACGT\n")
    tracker.finish(
        "pretext_to_asm",
        pta_dir,
        "success",
        outputs={
            "hap1_fa": str(fa_file),
            "hap1_haplotigs": str(hap_file),
            "hap1_chr_list": str(chr_file),
        },
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    pta_line = next(
        line for line in out.splitlines() if "pretext_to_asm " in line + " " and "success" in line
    )

    assert "fa(1)" in pta_line
    assert "hap(1)" in pta_line
    assert "chr(1)" in pta_line


def test_show_ticket_history_rename_and_orient_can_show_chr(tmp_path, monkeypatch, capsys):
    """Regression: after rename_and_orient's _OUTPUT_SPECS gained a chr_list
    key, its row can legitimately show `chr` (in addition to `fa`) once its
    chromosome-list output is the freshest tracked one for this haplotype —
    a scenario that was previously impossible since rename_and_orient never
    had a tracked chr_list output at all."""
    import os

    monkeypatch.setattr(console, "width", 200)
    tol_id = "sDipInt39"
    reg, tracker = _make_ticket_with_ctx(tmp_path, monkeypatch, tol_id)

    def _write(path, mtime_offset):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(">seq\nACGT\n")
        now = tracker.workdir.stat().st_mtime
        os.utime(path, (now + mtime_offset, now + mtime_offset))

    pta_dir = tracker.start("pretext_to_asm", "RC-1234", tol_id)
    pta_chr = pta_dir / f"{tol_id}.hap1.1.chromosome.list.csv"
    _write(pta_chr, 10)
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_chr_list": str(pta_chr)})

    rao_dir = tracker.start("rename_and_orient", "RC-1234", tol_id)
    rao_fa = rao_dir / f"{tol_id}.hap1.primary.renamed.fa"
    rao_chr = rao_dir / f"{tol_id}.hap1.primary.renamed.chromosome.list.csv"
    _write(rao_fa, 20)
    _write(rao_chr, 20)
    tracker.finish(
        "rename_and_orient",
        rao_dir,
        "success",
        outputs={"hap1_fa": str(rao_fa), "hap1_chr_list": str(rao_chr)},
    )

    show_ticket_history(reg, "RC-1234", TEST_USER_CONFIG)

    out = capsys.readouterr().out
    rao_line = next(
        line
        for line in out.splitlines()
        if "rename_and_orient " in line + " " and "success" in line
    )

    assert "fa(1)" in rao_line
    assert "chr(1)" in rao_line


def test_show_global_status_reads_from_passed_registry_not_default(tmp_path, monkeypatch, capsys):
    """RunTracker(workdir) inside show_global_status must read from the `registry`
    argument it's already given, not lazily build its own default RegistryManager()
    pointed at a different location."""
    default_dir = tmp_path / "default_registry"
    passed_dir = tmp_path / "passed_registry"
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", default_dir)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg = RegistryManager(registry_dir=passed_dir)
    reg.add_ticket("RC-1234", "sDipInt39", "species", workdir)
    tracker = RunTracker(workdir, registry=reg)
    run_dir = tracker.start("fastga", "RC-1234", "sDipInt39")
    tracker.finish("fastga", run_dir, "success")

    show_global_status(reg)

    out = capsys.readouterr().out
    assert "fastga" in out
    assert "success" in out


def _make_dry_run_ticket_with_ctx(tmp_path, monkeypatch, tol_id="sDipInt39"):
    """Seed a ticket+step in a dry-run-isolated registry/workdir (distinct from the
    default registry dir), and patch CurationContext.from_ticket to capture the
    kwargs it's called with and return a ctx wired to that same dry-run workdir."""
    default_dir = tmp_path / "default_registry"
    dry_dir = tmp_path / "dry_run_root"
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", default_dir)
    monkeypatch.setattr("grit.core.registry.dry_run_root", lambda: dry_dir)

    workdir = dry_dir / tol_id
    workdir.mkdir(parents=True)
    reg = RegistryManager(registry_dir=dry_dir)
    reg.add_ticket("RC-DRY", tol_id, "species", workdir)
    tracker = RunTracker(workdir, registry=reg)

    captured_kwargs: dict = {}

    def fake_from_ticket(cls, ticket_id, user_config, **kwargs):
        captured_kwargs.update(kwargs)
        ctx = CurationContext.from_yaml(
            "RC-DRY", TEST_YAML_HAP1, TEST_USER_CONFIG, dry_run=kwargs.get("dry_run", False)
        )
        ctx.workdir = workdir
        ctx.tol_id = tol_id
        ctx.tracker = tracker
        return ctx

    monkeypatch.setattr(
        "grit.core.context.CurationContext.from_ticket",
        classmethod(fake_from_ticket),
    )
    return reg, tracker, captured_kwargs


def test_show_ticket_history_dry_run_reads_isolated_registry_and_context(
    tmp_path, monkeypatch, capsys
):
    tol_id = "sDipInt39"
    reg, tracker, captured_kwargs = _make_dry_run_ticket_with_ctx(tmp_path, monkeypatch, tol_id)

    run_dir = tracker.start("rename_and_orient", "RC-DRY", tol_id)
    tracker.finish("rename_and_orient", run_dir, "success")

    show_ticket_history(reg, "RC-DRY", TEST_USER_CONFIG, dry_run=True)

    out = capsys.readouterr().out

    # CurationContext.from_ticket was called with dry_run=True.
    assert captured_kwargs.get("dry_run") is True
    # RunTracker read the passed-in (dry-run-isolated) registry's step history.
    assert "rename_and_orient" in out
    assert "success" in out


def test_show_ticket_history_dry_run_false_does_not_see_dry_run_ticket(tmp_path, monkeypatch):
    """A real (non-dry-run) registry lookup for the same ticket ID must not pick up
    the dry-run registry's data — the two registries are entirely separate objects,
    so a real lookup with a real (empty) registry simply won't find the ticket."""
    tol_id = "sDipInt39"
    dry_reg, tracker, _ = _make_dry_run_ticket_with_ctx(tmp_path, monkeypatch, tol_id)

    run_dir = tracker.start("rename_and_orient", "RC-DRY", tol_id)
    tracker.finish("rename_and_orient", run_dir, "success")

    real_registry_dir = tmp_path / "real_registry"
    real_reg = RegistryManager(registry_dir=real_registry_dir)

    with patch("grit.core.status.console") as mock_console:
        show_ticket_history(real_reg, "RC-DRY", TEST_USER_CONFIG, dry_run=False)

    printed = " ".join(str(call.args[0]) for call in mock_console.print.call_args_list)
    assert "not found" in printed
    assert "rename_and_orient" not in printed


def test_show_ticket_history_dry_run_with_yaml_override_builds_ctx_and_shows_marker(
    tmp_path, monkeypatch, capsys
):
    """A synthetic dry-run ticket has no real Jira issue, so from_ticket would
    normally raise and skip the canonical-files table / canonical marker entirely
    (ctx stays None). Passing yaml_override bypasses the Jira fetch, letting
    the real CurationContext build succeed against the dry-run-isolated workdir
    — the canonical files table and marker must then actually be produced."""
    tol_id = "ilHelSara1"
    ticket_id = "RC-DRY"
    dry_dir = tmp_path / "dry_run_root"
    monkeypatch.setattr("grit.core.registry.dry_run_root", lambda: dry_dir)

    workdir = dry_dir / ticket_id  # dry-run workdirs are keyed by ticket_id, not tol_id
    workdir.mkdir(parents=True)
    reg = RegistryManager(registry_dir=dry_dir)
    reg.add_ticket(ticket_id, tol_id, "species", workdir)
    tracker = RunTracker(workdir, registry=reg)

    run_dir = tracker.start("pretext_to_asm", "RC-DRY", tol_id)
    curated_fa = run_dir / f"{tol_id}.1.primary.curated.fa"
    curated_fa.write_text(">SCAFFOLD_1\nACGT\n")
    tracker.finish("pretext_to_asm", run_dir, "success", outputs={"hap1_fa": str(curated_fa)})

    show_ticket_history(
        reg, "RC-DRY", TEST_USER_CONFIG, dry_run=True, yaml_override=TEST_YAML_PRIMARY
    )

    out = capsys.readouterr().out
    assert "Could not build curation context" not in out
    assert "Canonical files" in out

    pta_line = next(
        line for line in out.splitlines() if "pretext_to_asm" in line and "success" in line
    )
    assert "fa" in pta_line
    # Single-hap ticket — no hap suffix needed since there's only one candidate.
    assert "fa(" not in pta_line
