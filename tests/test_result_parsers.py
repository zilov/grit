"""Tests for grit/utils/result_parsers.py."""

from grit.utils.result_parsers import parse_pta_log


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
