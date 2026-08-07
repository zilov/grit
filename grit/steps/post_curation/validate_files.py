"""Step: read and print curation stats; verify all expected output files are present."""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import find_latest_dir
from grit.utils.output import (
    console,
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_validate_files(ctx: CurationContext) -> None:
    """
    Reads and prints curation stats for the Jira comment: QV, completeness, and log.

    Notebook source: ``pre_and_post_curation()`` — "Reading files for Jira" section.

    Steps:
        1. Open the curation log and parse lines starting with ``"Curation made"``
           to extract breaks/cuts/joins counts.
        2. Read ``{ctx.tol_id}.completeness.stats`` (completeness) from the tracked
           ``qv`` step output, or ``{ctx.assembly_curated_dir}/merquryk/`` as fallback.
        3. Read ``{ctx.tol_id}.qv`` (QV score) the same way.
        4. Verify that all expected output files exist in ``ctx.workdir``
           (curated FA, chromosome list CSV, haplotig FA, log, AGP);
           report any missing files.

    Prints:
        Breaks / joins counts, QV table, completeness table, missing-file warnings.
    Next step hint: ``finalize_for_qc(ctx)``
    """
    log.info("validate-files | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Validate curated files")

    # --- curation log ---
    if ctx.release_version > 1:
        log_path = ctx.workdir / f"{ctx.tol_id}.{ctx.release_version}.log"
    else:
        log_path = ctx.workdir / f"{ctx.tol_id}.log"

    console.print("\n[bold]Curation log:[/bold]")
    if ctx.print_only:
        log.info("Log path (expected): %s", log_path)
    elif log_path.exists():
        with open(log_path) as fh:
            for line in fh:
                if line.startswith("Curation made"):
                    try:
                        cuts = int(line.split(" cut")[0].split()[-1])
                        breaks = int(line.split(" break")[0].split()[-1])
                        joins = int(line.split(" join")[0].split()[-1])
                        console.print(
                            f"  Breaks: [bold]{breaks}[/bold], Joins: [bold]{joins + cuts}[/bold]"
                        )
                    except (ValueError, IndexError):
                        console.print(f"  {line.strip()}")
    else:
        log.warning("Curation log not found: %s", log_path)

    # --- QV / completeness ---
    qv_dir = ctx.assembly_curated_dir / "merquryk"
    console.print("\n[bold]QV and completeness:[/bold]")
    if ctx.print_only:
        log.info("QV dir (expected): %s", qv_dir)
    else:
        qv_file = None
        completeness_file = None
        if ctx.tracker:
            qv_out = ctx.tracker.get_output("qv", "qv")
            if qv_out:
                qv_file = Path(qv_out)
            comp_out = ctx.tracker.get_output("qv", "completeness_stats")
            if comp_out:
                completeness_file = Path(comp_out)
        if qv_file is None:
            qv_file = qv_dir / f"{ctx.tol_id}.qv"
        if completeness_file is None:
            completeness_file = qv_dir / f"{ctx.tol_id}.completeness.stats"

        found_files = [f for f in (qv_file, completeness_file) if f.exists()]
        if not found_files:
            log.warning("No QV results found in %s. Run run_qv first.", qv_dir)
        for f in found_files:
            console.print(f"\n  [dim]{f}[/dim]")
            with open(f) as fh:
                for line in fh:
                    if line.strip():
                        console.print(f"  {line.rstrip()}")

    # --- check expected files ---
    # Curated files live in the pretext_to_asm run_dir; AGP/log remain in workdir.
    pta_dir = find_latest_dir(ctx, "pretext_to_asm")

    console.print("\n[bold]Expected files:[/bold]")
    curated_patterns = [
        (pta_dir, f"{ctx.tol_id}*.curated.fa"),
        (pta_dir, f"{ctx.tol_id}*.chromosome.list.csv"),
        (pta_dir, f"{ctx.tol_id}*haplotigs*.fa"),
        (ctx.workdir, f"{ctx.tol_id}*.agp*"),
        (ctx.workdir, f"{ctx.tol_id}*.log"),
    ]
    all_ok = True
    for base, pattern in curated_patterns:
        if ctx.print_only:
            console.print(f"  [dim]{base / pattern}[/dim]")
        else:
            found = glob.glob(str(base / pattern))
            status = "[green]✓[/green]" if found else "[red]✗ MISSING[/red]"
            console.print(f"  {status}  {pattern}")
            if not found:
                all_ok = False

    if not ctx.print_only:
        if all_ok:
            print_done("All expected files present")
        else:
            log.warning("Some expected files are missing — see above")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("validate-files", cls=GritCommand)
@click.pass_context
def validate_files_cmd(ctx):
    """Read curation stats and verify all expected output files are present."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_validate_files(curation_ctx)
    except Exception:
        log.exception("validate-files failed")
        raise SystemExit(1)
