"""Tests for the super-to-scaffold AGP parser."""

from pathlib import Path

import pytest

from grit.steps.optional.super_to_scaffold import _natural_super_key, _parse_agp_supers
from grit.utils.helpers import find_hap_agp

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _rows_by_super(rows):
    return {row["super"]: row for row in rows}


def test_parse_agp_supers_single_component_super_is_100pct():
    rows = _rows_by_super(_parse_agp_supers(_FIXTURES_DIR / "bAraMil1.hap1.1.primary.curated.agp"))

    super_2 = rows["SUPER_2_HAP1"]
    assert super_2["scaffold"] == "HAP1_SCAFFOLD_24"
    assert super_2["length"] == 164288677
    assert super_2["pct_of_super"] == pytest.approx(100.0)


def test_parse_agp_supers_picks_longest_component():
    rows = _rows_by_super(_parse_agp_supers(_FIXTURES_DIR / "bAraMil1.hap1.1.primary.curated.agp"))

    super_4 = rows["SUPER_4_HAP1"]
    # SUPER_4_HAP1 has two W components: 122153285bp and 3654898bp, total 125808283bp.
    assert super_4["scaffold"] == "HAP1_SCAFFOLD_26"
    assert super_4["length"] == 122153285
    assert super_4["pct_of_super"] == pytest.approx(100.0 * 122153285 / 125808283)


def test_parse_agp_supers_hap2_fixture_has_rows():
    rows = _parse_agp_supers(_FIXTURES_DIR / "bAraMil1.hap2.1.primary.curated.agp")
    assert rows
    for row in rows:
        assert row["length"] > 0
        assert 0 < row["pct_of_super"] <= 100.0


def test_natural_super_key_orders_numerically():
    supers = ["SUPER_10_HAP1", "SUPER_2_HAP1", "SUPER_1_HAP1"]
    assert sorted(supers, key=_natural_super_key) == [
        "SUPER_1_HAP1",
        "SUPER_2_HAP1",
        "SUPER_10_HAP1",
    ]


def test_find_hap_agp_matches_hap_specific_pattern(mock_ctx, tmp_path):
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_dir.mkdir(parents=True)
    hap1_agp = pta_dir / f"{mock_ctx.tol_id}.hap1.1.primary.curated.agp"
    hap1_agp.write_text("1\tSUPER_1\t1\t10\t1\tW\tSCAFFOLD_1\t1\t10\t+\n")
    mock_ctx.tracker.finish("pretext_to_asm", pta_dir, "success")

    assert find_hap_agp(mock_ctx, "hap1") == hap1_agp


def test_find_hap_agp_missing_raises(mock_ctx, tmp_path):
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    mock_ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_dir.mkdir(parents=True)
    mock_ctx.tracker.finish("pretext_to_asm", pta_dir, "success")

    with pytest.raises(FileNotFoundError):
        find_hap_agp(mock_ctx, "hap1")
