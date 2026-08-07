"""Tests for grit/utils/result_parsers.py."""

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.utils.result_parsers import (
    _build_allosome_string,
    collect_curation_results,
    find_lsf_log,
    parse_chromosome_list,
    parse_lsf_exit_reason,
    parse_pta_log,
)


def test_parse_pta_log_plural(tmp_path):
    log = tmp_path / "pta.log"
    log.write_text("Curation made 3 cuts in contigs, 2 breaks at gaps and 11 joins\n")
    assert parse_pta_log(log) == (3, 2, 11)


def test_parse_pta_log_singular_with_article(tmp_path):
    """pretext-to-asm uses 'a contig' / 'a gap' when the count is 1."""
    log = tmp_path / "pta.log"
    log.write_text("Curation made 1 cut in a contig, 1 break at a gap and 11 joins\n")
    assert parse_pta_log(log) == (1, 1, 11)


def test_parse_pta_log_zero(tmp_path):
    log = tmp_path / "pta.log"
    log.write_text("Curation made 0 cuts in contigs, 0 breaks at gaps and 5 joins\n")
    assert parse_pta_log(log) == (0, 0, 5)


def test_parse_pta_log_not_found(tmp_path):
    log = tmp_path / "pta.log"
    log.write_text("nothing relevant here\n")
    assert parse_pta_log(log) is None


def test_build_allosome_string_zz_male_across_two_haplotypes_stays_zz():
    """Z appearing once in hap1 and once in hap2 (ZZ male) must not collapse to 'ZO'."""
    assert _build_allosome_string(["Z", "Z"]) == "ZZ"


def test_build_allosome_string_single_z_is_zo():
    assert _build_allosome_string(["Z"]) == "ZO"


def test_build_allosome_string_zw_pair():
    assert _build_allosome_string(["W", "Z"]) == "ZW"


def test_parse_chromosome_list_dedupes_within_same_file(tmp_path):
    """Duplicate sex-chrom rows within one hap CSV (e.g. leftover unloc fragments
    not caught by the scaffold-name filter) should be deduped."""
    csv = tmp_path / "hap1.chromosome.list.csv"
    csv.write_text("scaffold_1,Z\nscaffold_2,Z\nscaffold_3,1\n")
    autosomes, sex_ids = parse_chromosome_list(csv)
    assert autosomes == 1
    assert sex_ids == ["Z"]


def test_parse_chromosome_list_excludes_unloc_marker_on_scaffold_name(tmp_path):
    """unloc marker on the auto-generated scaffold name (column 0)."""
    csv = tmp_path / "hap1.chromosome.list.csv"
    csv.write_text("SUPER_1,1\nSUPER_Z,Z\nSUPER_Z_unloc_1,Z\nSUPER_Z_unloc_2,Z\n")
    autosomes, sex_ids = parse_chromosome_list(csv)
    assert autosomes == 1
    assert sex_ids == ["Z"]


def test_parse_chromosome_list_excludes_unloc_marker_on_chrom_label(tmp_path):
    """unloc marker on the curator-typed chromosome label (column 1), e.g. "Zunloc10" —
    the naming convention 03a0914 fixed for and a8d21db later regressed by only
    checking the scaffold name."""
    csv = tmp_path / "hap1.chromosome.list.csv"
    csv.write_text("scaffold_1,1\nscaffold_2,Z\nscaffold_3,Zunloc10\nscaffold_4,Zunloc11\n")
    autosomes, sex_ids = parse_chromosome_list(csv)
    assert autosomes == 1
    assert sex_ids == ["Z"]


# --- parse_lsf_exit_reason ---


def test_parse_lsf_exit_reason_memlimit(tmp_path):
    log = tmp_path / "e_fastga"
    log.write_text(
        "some job output\n"
        "TERM_MEMLIMIT: job killed after reaching LSF memory usage limit.\n"
        "Exited with exit code 143.\n"
    )
    assert parse_lsf_exit_reason(log) == "TERM_MEMLIMIT"


def test_parse_lsf_exit_reason_runlimit(tmp_path):
    log = tmp_path / "e_fastga"
    log.write_text("TERM_RUNLIMIT: job killed after reaching LSF run time limit.\n")
    assert parse_lsf_exit_reason(log) == "TERM_RUNLIMIT"


def test_parse_lsf_exit_reason_no_match(tmp_path):
    log = tmp_path / "e_fastga"
    log.write_text("Successfully completed.\n")
    assert parse_lsf_exit_reason(log) is None


def test_parse_lsf_exit_reason_missing_file(tmp_path):
    assert parse_lsf_exit_reason(tmp_path / "does_not_exist.log") is None


# --- find_lsf_log ---


def test_find_lsf_log_prefers_error_file(tmp_path):
    (tmp_path / "o_fastga").write_text("out")
    (tmp_path / "e_fastga").write_text("err")
    assert find_lsf_log(tmp_path) == tmp_path / "e_fastga"


def test_find_lsf_log_falls_back_to_output_file(tmp_path):
    (tmp_path / "o_fastga").write_text("out")
    assert find_lsf_log(tmp_path) == tmp_path / "o_fastga"


def test_find_lsf_log_returns_none_when_no_candidates(tmp_path):
    assert find_lsf_log(tmp_path) is None


def test_find_lsf_log_returns_none_for_missing_dir(tmp_path):
    assert find_lsf_log(tmp_path / "missing") is None


def _make_tracker(tmp_path, tol_id="sDipInt39"):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket("RC-1234", tol_id, "species", workdir)
    return RunTracker(workdir, registry=reg), workdir


def test_collect_curation_results_prefers_tracker_output_over_curated_dir_glob(tmp_path):
    tracker, workdir = _make_tracker(tmp_path)

    # Registered qv output — a file NOT under curated_dir/merquryk at all.
    tracked_qv = tmp_path / "elsewhere" / "sDipInt39.qv"
    tracked_qv.parent.mkdir()
    tracked_qv.write_text("qv\t60.0\n")
    tracker.start("qv", "RC-1234", "sDipInt39")
    tracker.finish("qv", workdir / "qv" / "run1", "success", outputs={"qv": str(tracked_qv)})

    # curated_dir/merquryk also has a same-named file with different content —
    # the tracker-registered path must win.
    curated_dir = tmp_path / "curated"
    merquryk = curated_dir / "merquryk"
    merquryk.mkdir(parents=True)
    (merquryk / "sDipInt39.qv").write_text("qv\t0.0 (should not be used)\n")

    result = collect_curation_results(tracker, workdir, "sDipInt39", curated_dir=curated_dir)
    assert result.qv_text == "qv\t60.0"


def test_collect_curation_results_zz_male_across_haps_reports_zz(tmp_path):
    tracker, workdir = _make_tracker(tmp_path)

    (workdir / "sDipInt39.hap1.primary.chromosome.list.csv").write_text(
        "scaffold_1,1\nscaffold_2,Z\n"
    )
    (workdir / "sDipInt39.hap2.primary.chromosome.list.csv").write_text(
        "scaffold_1,1\nscaffold_2,Z\n"
    )

    result = collect_curation_results(tracker, workdir, "sDipInt39")
    assert result.allosomes == "ZZ"


def test_collect_curation_results_falls_back_to_curated_dir_glob(tmp_path):
    tracker, workdir = _make_tracker(tmp_path)

    curated_dir = tmp_path / "curated"
    merquryk = curated_dir / "merquryk"
    merquryk.mkdir(parents=True)
    (merquryk / "sDipInt39.qv").write_text("qv\t55.0\n")
    (merquryk / "sDipInt39.completeness.stats").write_text("completeness\t99.0\n")

    result = collect_curation_results(tracker, workdir, "sDipInt39", curated_dir=curated_dir)
    assert result.qv_text == "qv\t55.0"
    assert result.completeness_text == "completeness\t99.0"


def test_collect_curation_results_sums_breaks_joins_with_micro_run(tmp_path):
    """Tickets that went through the birds microchromosome workflow should get
    one combined breaks/joins total across the main + micro pretext-to-asm runs."""
    tracker, workdir = _make_tracker(tmp_path)

    pta_dir = workdir / "pretext_to_asm" / "run1"
    pta_dir.mkdir(parents=True)
    (pta_dir / "sDipInt39.log").write_text(
        "Curation made 3 cuts in contigs, 2 breaks at gaps and 11 joins\n"
    )
    tracker.finish("pretext_to_asm", pta_dir, "success")

    micro_dir = workdir / "pretext_to_asm_micro" / "run1"
    micro_dir.mkdir(parents=True)
    (micro_dir / "sDipInt39.log").write_text(
        "Curation made 1 cut in a contig, 1 break at a gap and 4 joins\n"
    )
    tracker.finish("pretext_to_asm_micro", micro_dir, "success")

    result = collect_curation_results(tracker, workdir, "sDipInt39")
    assert (result.cuts, result.breaks, result.joins) == (4, 3, 15)


def test_collect_curation_results_ignores_micro_run_when_it_never_ran(tmp_path):
    """No microchromosome workflow → totals unaffected, same as before this feature."""
    tracker, workdir = _make_tracker(tmp_path)

    pta_dir = workdir / "pretext_to_asm" / "run1"
    pta_dir.mkdir(parents=True)
    (pta_dir / "sDipInt39.log").write_text(
        "Curation made 3 cuts in contigs, 2 breaks at gaps and 11 joins\n"
    )
    tracker.finish("pretext_to_asm", pta_dir, "success")

    result = collect_curation_results(tracker, workdir, "sDipInt39")
    assert (result.cuts, result.breaks, result.joins) == (3, 2, 11)
