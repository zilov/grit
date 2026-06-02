"""Step: ensure all expected haplotig FASTA files are present after pretext-to-asm."""

from __future__ import annotations

import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.output import (
    print_done,
    print_info,
    print_next_step,
    print_step_header,
    print_warning,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_haplotig_files(ctx: CurationContext) -> None:
    """
    Ensures all expected haplotig FASTA files are present after pretext-to-asm.
    Creates empty files for any that are missing (e.g. if the Haplotig tag was not used).

    Notebook source: ``pre_and_post_curation()`` — ``haplotigs_exists`` check.

    Steps:
        1. Build the expected haplotig filename:
           ``{tol_id}.{hap1_prefix}.{release_version}.all_haplotigs.curated.fa``
           (for primary assemblies: ``{tol_id}.{release_version}.all_haplotigs.curated.fa``)
        2. If the file is absent or empty: create it with ``touch``.
        3. Print a warning if an existing haplotig file is non-empty
           (curator should verify its contents).

    Prints:
        Status per expected file (found / created).
    Next step hint: ``run_hic_remapping(ctx)``
    """
    log.info("haplotig-files | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Ensure haplotig files")

    # hap1/hap2: {tol_id}.hap1.1.all_haplotigs.curated.fa
    # primary:   {tol_id}.1.all_haplotigs.curated.fa
    if ctx.assembly_type in ("hap1", "paternal"):
        haplotig_name = (
            f"{ctx.tol_id}.{ctx.hap1_prefix}.{ctx.release_version}.all_haplotigs.curated.fa"
        )
    else:
        haplotig_name = f"{ctx.tol_id}.{ctx.release_version}.all_haplotigs.curated.fa"

    haplotig_path = ctx.workdir / haplotig_name

    if ctx.print_only:
        print_info("Expected haplotig file", str(haplotig_path))
        print_next_step("run_hic_remapping(ctx)")
        return

    if haplotig_path.exists() and haplotig_path.stat().st_size > 10:
        print_warning(f"Haplotig file is non-empty: {haplotig_path}")
        print_info("Status", "found (non-empty — verify contents)")
    elif haplotig_path.exists():
        print_info("Status", f"found (empty) — {haplotig_name}")
    else:
        haplotig_path.touch()
        print_info("Status", f"created empty — {haplotig_name}")

    print_done("Haplotig files ready")
    print_next_step("run_hic_remapping(ctx)")


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("haplotig-files", cls=GritCommand)
@click.pass_context
def haplotig_files_cmd(ctx):
    """Ensure haplotig files are present."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_haplotig_files(curation_ctx)
    except Exception:
        log.exception("haplotig-files failed")
        raise SystemExit(1)
