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
from grit.utils.helpers import find_hap_agp, is_single_hap
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output specs
# ---------------------------------------------------------------------------

_OUTPUT_SPECS = [("table_csv", "{tol_id}.super_to_scaffold.csv", [])]

# ---------------------------------------------------------------------------
# AGP parsing
# ---------------------------------------------------------------------------


def _parse_agp_supers(path: Path) -> list[dict]:
    """
    Parse a headerless, tab-separated AGP file and return, per super (object),
    the ``W``-type (real sequence) scaffold with the largest total length —
    summed across all its pieces, since a scaffold can be split into several
    pieces within the same super when another scaffold is inserted between them.

    Unplaced scaffolds appear in the AGP as their own object (named after the
    scaffold itself, not a super) — these are excluded; only objects named
    ``SUPER...`` are reported.

    A "piece" only starts a new count when a *different* scaffold interrupts
    it — a gap (``N``/``U`` row) between two ``W`` rows of the same scaffold
    is an internal gap within that scaffold, not a break into separate pieces.

    Returns a list of dicts with keys: super, scaffold, length, num_pieces,
    pct_of_super (summed scaffold length as a percentage of the super's total
    length, i.e. the max object_end seen for that super across all rows).
    """
    scaffolds_by_super: dict[str, dict[str, dict]] = {}
    totals: dict[str, int] = {}
    last_scaffold_by_super: dict[str, str | None] = {}

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 9:
            continue

        obj_name, _obj_beg, obj_end, _part_num, component_type = parts[:5]
        obj_end = int(obj_end)
        totals[obj_name] = max(totals.get(obj_name, 0), obj_end)

        if component_type != "W":
            continue

        component_id, comp_beg, comp_end = parts[5], int(parts[6]), int(parts[7])
        length = comp_end - comp_beg + 1

        scaffolds = scaffolds_by_super.setdefault(obj_name, {})
        entry = scaffolds.setdefault(component_id, {"length": 0, "num_pieces": 0})
        entry["length"] += length
        if component_id != last_scaffold_by_super.get(obj_name):
            entry["num_pieces"] += 1
        last_scaffold_by_super[obj_name] = component_id

    rows = []
    for obj_name, scaffolds in scaffolds_by_super.items():
        if not obj_name.startswith("SUPER"):
            continue
        scaffold_id, entry = max(scaffolds.items(), key=lambda item: item[1]["length"])
        total = totals.get(obj_name, entry["length"])
        pct = 100.0 * entry["length"] / total if total else 0.0
        rows.append(
            {
                "super": obj_name,
                "scaffold": scaffold_id,
                "length": entry["length"],
                "num_pieces": entry["num_pieces"],
                "pct_of_super": pct,
            }
        )
    return rows


# Tutorial example: the same ten chromosomes as fastga-stats' dry-run table.
_DRY_RUN_ROWS = [
    dict(zip(("super", "scaffold", "length", "num_pieces", "pct_of_super"), row))
    for row in [
        ("SUPER_1", "HAP1_SCAFFOLD_4", 43381220, 2, 93.2),
        ("SUPER_2", "HAP1_SCAFFOLD_1", 39750118, 1, 99.1),
        ("SUPER_3", "HAP1_SCAFFOLD_7", 36072445, 3, 81.6),
        ("SUPER_4", "HAP1_SCAFFOLD_2", 34886004, 1, 98.7),
        ("SUPER_5", "HAP1_SCAFFOLD_9", 30851761, 2, 90.4),
        ("SUPER_6", "HAP1_SCAFFOLD_3", 28570312, 1, 99.4),
        ("SUPER_7", "HAP1_SCAFFOLD_12", 27381900, 2, 84.5),
        ("SUPER_8", "HAP1_SCAFFOLD_5", 22724887, 1, 97.8),
        ("SUPER_9", "HAP1_SCAFFOLD_6", 19560213, 1, 98.9),
        ("SUPER_10", "HAP1_SCAFFOLD_15", 16471055, 2, 88.0),
    ]
]


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

    if ctx.dry_run:
        run_dir = ctx.tracker.start(
            "super_to_scaffold", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        rows = [{"hap": ctx.hap1_prefix, **row} for row in _DRY_RUN_ROWS]
        _print_table(rows)
        csv_path = _write_csv(rows, run_dir / f"{ctx.tol_id}.super_to_scaffold.csv")
        ctx.tracker.finish(
            "super_to_scaffold",
            run_dir,
            "success",
            outputs={"table_csv": str(csv_path)},
            untracked=ctx.untracked,
        )
        print_done(f"[dry-run] Table saved → {csv_path}")
        return

    haps_to_process = (
        [ctx.hap1_prefix] if is_single_hap(ctx) else [ctx.hap1_prefix, ctx.hap2_prefix]
    )

    if ctx.print_only:
        for hap_prefix in haps_to_process:
            log.info(
                "[%s] Would parse AGP: {pretext_to_asm run dir}/%s.%s.*.curated.agp",
                hap_prefix,
                ctx.tol_id,
                hap_prefix,
            )
        print_done("Would print super/scaffold table and save it as CSV.")
        return

    # Even for a hap1/hap2 assembly, curation may have been done in a single
    # combined window (e.g. combine_for_curation) — in that case there is no
    # separate hap2 AGP, so hap2 is dropped rather than treated as an error.
    if not is_single_hap(ctx):
        try:
            find_hap_agp(ctx, ctx.hap2_prefix)
        except FileNotFoundError:
            log.info(
                "No separate AGP for %s — treating as a single combined curation window",
                ctx.hap2_prefix,
            )
            haps_to_process = [ctx.hap1_prefix]

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

        csv_path = _write_csv(all_rows, run_dir / f"{ctx.tol_id}.super_to_scaffold.csv")

        if ctx.tracker:
            ctx.tracker.finish(
                "super_to_scaffold",
                run_dir,
                "success",
                outputs={"table_csv": str(csv_path)},
                untracked=ctx.untracked,
            )
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish("super_to_scaffold", run_dir, "failed", untracked=ctx.untracked)
        raise

    print_done(f"Table saved → {csv_path}")


def _write_csv(rows: list[dict], csv_path: Path) -> Path:
    """Write *rows* to *csv_path* and return it."""
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["hap", "super", "scaffold", "length", "num_pieces", "pct_of_super"],
        )
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def _print_table(rows: list[dict]) -> None:
    table = Table(title="Largest scaffold per super")
    table.add_column("Hap")
    table.add_column("Super")
    table.add_column("Scaffold")
    table.add_column("Length", justify="right")
    table.add_column("Pieces", justify="right")
    table.add_column("% of super", justify="right")

    for row in rows:
        table.add_row(
            row["hap"],
            row["super"],
            row["scaffold"],
            f"{row['length']:,}",
            str(row["num_pieces"]),
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
