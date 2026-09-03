"""Unit tests for grit/scripts/paf_top_targets_by_coverage.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent / "grit" / "scripts" / "paf_top_targets_by_coverage.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("paf_top_targets_by_coverage", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _load_script()


def _paf_line(q_name, q_len, q_start, q_end, strand, t_name, t_len, t_start, t_end):
    # Minimal 12-column PAF record; columns 10/11/12 (matches/block-len/mapq)
    # are unused by this script but required for the >= 12 column check.
    matches = q_end - q_start
    block_len = q_end - q_start
    return (
        f"{q_name}\t{q_len}\t{q_start}\t{q_end}\t{strand}\t"
        f"{t_name}\t{t_len}\t{t_start}\t{t_end}\t{matches}\t{block_len}\t60\n"
    )


def test_merge_intervals_sums_non_overlapping_bp(script):
    assert script.merge_intervals([(0, 100), (50, 150), (200, 300)]) == 250


def test_merge_intervals_empty(script):
    assert script.merge_intervals([]) == 0


def test_parse_paf_drops_records_below_min_length(script, tmp_path):
    paf_path = tmp_path / "in.paf"
    paf_path.write_text(
        _paf_line("SUPER_1", 1000000, 0, 5000, "+", "chr1", 900000, 0, 5000)
        + _paf_line("SUPER_1", 1000000, 10000, 10500, "+", "chr1", 900000, 10000, 10500)
    )

    query_order, pair_intervals, _pair_alns, target_lengths = script.parse_paf(
        str(paf_path), min_length=3000
    )

    assert query_order == ["SUPER_1"]
    assert pair_intervals[("SUPER_1", "chr1")] == [(0, 5000)]
    assert target_lengths == {"chr1": 900000}


def test_best_targets_by_coverage_picks_highest_summed_coverage_not_longest_single_hit(script):
    """
    Regression test for the bug this script fixes: a single very long
    alignment to the wrong target must not beat a target with more total
    non-overlapping coverage spread across several alignments.
    """
    query_order = ["SUPER_1"]
    pair_intervals = {
        ("SUPER_1", "chr_wrong"): [(0, 20000)],  # one long hit: 20000bp
        ("SUPER_1", "chr_right"): [(0, 8000), (8000, 16000), (16000, 24000)],  # 24000bp total
    }
    target_lengths = {"chr_wrong": 100000, "chr_right": 100000}

    best = script.best_targets_by_coverage(query_order, pair_intervals, target_lengths)

    target, aligned_length, pct = best["SUPER_1"]
    assert target == "chr_right"
    assert aligned_length == 24000
    assert pct == pytest.approx(24.0)


def test_best_targets_by_coverage_omits_queries_with_no_surviving_alignments(script):
    best = script.best_targets_by_coverage(
        query_order=["SUPER_1"], pair_intervals={}, target_lengths={}
    )
    assert "SUPER_1" not in best


def test_main_writes_top1_out_with_new_columns(script, tmp_path, monkeypatch, capsys):
    paf_path = tmp_path / "in.paf"
    paf_path.write_text(
        _paf_line("SUPER_1", 1000000, 0, 9000, "+", "chr1", 900000, 0, 9000)
        + _paf_line("SUPER_1", 1000000, 0, 500, "+", "chr2", 900000, 0, 500)  # below min-length
    )
    top1_out = tmp_path / "out.top1_targets.tsv"

    monkeypatch.setattr(sys, "argv", ["prog", str(paf_path), "--top1-out", str(top1_out)])
    script.main()

    lines = top1_out.read_text().splitlines()
    assert lines[0] == "curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length"
    assert lines[1] == "SUPER_1\tchr1\t9000\t1.00"


def test_main_respects_custom_min_length(script, tmp_path, monkeypatch):
    paf_path = tmp_path / "in.paf"
    paf_path.write_text(_paf_line("SUPER_1", 1000000, 0, 500, "+", "chr1", 900000, 0, 500))
    top1_out = tmp_path / "out.top1_targets.tsv"

    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", str(paf_path), "--top1-out", str(top1_out), "--min-length", "100"],
    )
    script.main()

    lines = top1_out.read_text().splitlines()
    assert lines[1] == "SUPER_1\tchr1\t500\t0.06"
