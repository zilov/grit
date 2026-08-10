"""Report the largest scaffold within each super for hap1/hap2 curated AGPs."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path

import rich_click as click
from rich.table import Table

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import find_hap_agp
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AGP parsing
# ---------------------------------------------------------------------------


def _parse_agp_supers(path: Path) -> list[dict]:
    """
    Parse a headerless, tab-separated AGP file and return, per super (object),
    the longest ``W``-type (real sequence) component.

    Returns a list of dicts with keys: super, scaffold, length, pct_of_super
    (scaffold length as a percentage of the super's total length, i.e. the
    max object_end seen for that super across all rows).
    """
    supers: dict[str, dict] = {}
    totals: dict[str, int] = {}

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 9:
            continue

        obj_name, obj_beg, obj_end, _part_num, component_type = parts[:5]
        obj_end = int(obj_end)
        totals[obj_name] = max(totals.get(obj_name, 0), obj_end)

        if component_type != "W":
            continue

        component_id, comp_beg, comp_end = parts[5], int(parts[6]), int(parts[7])
        length = comp_end - comp_beg + 1

        best = supers.get(obj_name)
        if best is None or length > best["length"]:
            supers[obj_name] = {"super": obj_name, "scaffold": component_id, "length": length}

    rows = []
    for obj_name, row in supers.items():
        total = totals.get(obj_name, row["length"])
        pct = 100.0 * row["length"] / total if total else 0.0
        rows.append({**row, "pct_of_super": pct})
    return rows


def _natural_super_key(super_name: str) -> tuple:
    """Sort key so 'SUPER_2' sorts before 'SUPER_10'."""
    m = re.search(r"(\d+)", super_name)
    return (int(m.group(1)) if m else 0, super_name)


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_super_to_scaffold(ctx: CurationContext) -> None:
    """
    Parses hap1/hap2 curated AGPs and reports the largest scaffold within
    each super, and what percentage of that super's total length it makes up.

    Steps:
        1. Find each haplotype's curated AGP via ``find_hap_agp``
           (``{tol_id}.{hap}.*.curated.agp`` in the latest pretext_to_asm run dir).
        2. Parse the AGP; for every super (object), keep the longest ``W`` component.
        3. Print a table (hap, super, scaffold, length, % of super) and save it as CSV.

    Prints:
        Step header, table, path to saved CSV.
    """
    log.info("super-to-scaffold | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Super to scaffold")

    is_single_hap = ctx.hap1_prefix in ("primary", "paternal")
    haps_to_process = [ctx.hap1_prefix] if is_single_hap else [ctx.hap1_prefix, ctx.hap2_prefix]

    if ctx.print_only:
        for hap_prefix in haps_to_process:
            log.info("[%s] Would parse AGP: {pretext_to_asm run dir}/%s.%s.*.curated.agp",
                      hap_prefix, ctx.tol_id, hap_prefix)
        print_done("Would print super/scaffold table and save it as CSV.")
        return

    run_dir = (
        ctx.tracker.start("super_to_scaffold", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / "super_to_scaffold" / "untracked"
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        all_rows: list[dict] = []
        for hap_prefix in haps_to_process:
            agp_path = find_hap_agp(ctx, hap_prefix)
            log.info("[%s] AGP: %s", hap_prefix, agp_path)
            for row in _parse_agp_supers(agp_path):
                all_rows.append({"hap": hap_prefix, **row})

        all_rows.sort(key=lambda r: (r["hap"], _natural_super_key(r["super"])))

        _print_table(all_rows)

        csv_path = run_dir / f"{ctx.tol_id}.super_to_scaffold.csv"
        with csv_path.open("w", newline="") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["hap", "super", "scaffold", "length", "pct_of_super"]
            )
            writer.writeheader()
            writer.writerows(all_rows)

        if ctx.tracker:
            ctx.tracker.finish(
                "super_to_scaffold", run_dir, "success", outputs={"table_csv": str(csv_path)}
            )
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish("super_to_scaffold", run_dir, "failed")
        raise

    print_done(f"Table saved → {csv_path}")


def _print_table(rows: list[dict]) -> None:
    table = Table(title="Largest scaffold per super")
    table.add_column("Hap")
    table.add_column("Super")
    table.add_column("Scaffold")
    table.add_column("Length", justify="right")
    table.add_column("% of super", justify="right")

    for row in rows:
        table.add_row(
            row["hap"],
            row["super"],
            row["scaffold"],
            f"{row['length']:,}",
            f"{row['pct_of_super']:.1f}",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("super-to-scaffold", cls=GritCommand)
@click.pass_context
def super_to_scaffold_cmd(ctx):
    """Report the largest scaffold within each super for hap1/hap2 curated AGPs."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_super_to_scaffold(curation_ctx)
    except Exception:
        log.exception("super-to-scaffold failed")
        raise SystemExit(1)
