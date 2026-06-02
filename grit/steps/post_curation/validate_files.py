"""Step: read and print curation stats; verify all expected output files are present."""

from __future__ import annotations

import glob
import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.output import (
    console,
    print_done,
    print_next_step,
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
        2. Glob and read ``{ctx.assembly_curated_dir}/merquryk/*.stats`` (completeness).
        3. Glob and read ``{ctx.assembly_curated_dir}/merquryk/{ctx.tol_id}.qv`` (QV score).
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
        stats_files = glob.glob(str(qv_dir / "*.stats"))
        qv_files = glob.glob(str(qv_dir / f"{ctx.tol_id}.qv"))

        if not stats_files and not qv_files:
            log.warning("No QV results found in %s. Run run_qv first.", qv_dir)
        for f in stats_files:
            console.print(f"\n  [dim]{f}[/dim]")
            with open(f) as fh:
                for line in fh:
                    if line.strip():
                        console.print(f"  {line.rstrip()}")
        for f in qv_files:
            console.print(f"\n  [dim]{f}[/dim]")
            with open(f) as fh:
                for line in fh:
                    console.print(f"  {line.rstrip()}")

    # --- check expected files ---
    console.print("\n[bold]Expected files in workdir:[/bold]")
    expected_patterns = [
        f"{ctx.tol_id}*.primary.curated.fa",
        f"{ctx.tol_id}*.chromosome.list.csv",
        f"{ctx.tol_id}*haplotigs*.fa",
        f"{ctx.tol_id}*.agp*",
        f"{ctx.tol_id}*.log",
    ]
    all_ok = True
    for pattern in expected_patterns:
        if ctx.print_only:
            console.print(f"  [dim]{ctx.workdir / pattern}[/dim]")
        else:
            found = glob.glob(str(ctx.workdir / pattern))
            status = "[green]✓[/green]" if found else "[red]✗ MISSING[/red]"
            console.print(f"  {status}  {pattern}")
            if not found:
                all_ok = False

    if not ctx.print_only:
        if all_ok:
            print_done("All expected files present")
        else:
            log.warning("Some expected files are missing — see above")

    print_next_step("finalize_for_qc(ctx)")


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
