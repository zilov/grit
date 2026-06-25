"""Rename and orient chromosomes to reference."""

from __future__ import annotations

import glob
import logging
import subprocess
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import find_curated_fa, find_latest_dir
from grit.utils.output import (
    console,
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

_RENAME_AND_ORIENT_SCRIPT = "/software/grit/projects/vgp_curation_scripts/rename_and_orient.py"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_rename_and_orient_for_hap(
    ctx: CurationContext,
    hap_prefix: str,
    paf_file: Path,
    step_name: str,
    *,
    mapping_table: Path | None = None,
) -> Path:
    """
    Run rename_and_orient.py for one haplotype.

    For hap1: uses ``--paf`` for alignment.
    For hap2: pass ``mapping_table`` (the .mapping.tsv from the hap1 run) to
    use ``--mapping-table`` instead of re-aligning.

    Returns the path to the output ``.mapping.tsv`` (needed for hap2 call).
    Raises subprocess.CalledProcessError on failure.
    """
    input_fa = find_curated_fa(ctx, hap_prefix)
    log.info("Curated %s FASTA: %s", hap_prefix, input_fa)

    outdir = ctx.workdir / "rename_and_orient"
    prefix = f"{ctx.tol_id}.{hap_prefix}.primary.renamed"
    mapping_tsv = outdir / f"{prefix}.mapping.tsv"

    if mapping_table is not None:
        source_arg = f"--mapping-table {mapping_table}"
    else:
        source_arg = f"--paf {paf_file}"

    cmd = (
        f"python3 {_RENAME_AND_ORIENT_SCRIPT} "
        f"--fasta {input_fa} "
        f"{source_arg} "
        f"--output-dir {outdir} "
        f"--output-prefix {prefix}"
    )

    console.print(f"\n[yellow]Command ({hap_prefix}):[/yellow] [green]{cmd}[/green]")
    if ctx.print_only:
        return mapping_tsv

    run_dir = ctx.tracker.start(step_name, ctx.ticket_id, ctx.tol_id) if ctx.tracker else None
    try:
        subprocess.run(cmd, shell=True, check=True)
        if ctx.tracker and run_dir:
            ctx.tracker.finish(step_name, run_dir, "success")
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish(step_name, run_dir, "failed")
        raise

    return mapping_tsv


# ---------------------------------------------------------------------------
# Public step function
# ---------------------------------------------------------------------------


def run_rename_and_orient(ctx: CurationContext, *, run_hap2: bool = False) -> None:
    """
    Renames and orients chromosomes in the curated FASTA based on FastGA PAF alignment.

    Runs hap1 by default. Pass ``run_hap2=True`` to also process hap2 using
    the mapping table produced by the hap1 run (no re-alignment needed).
    hap2 is tracked separately as ``rename_and_orient_hap2``.

    Prerequisites:
        - Curated FASTA exists in pretext_to_asm dir.
        - FastGA has been run and PAF file exists in fastga/ directory.

    Output files (both haps share the same outdir):
        ``{workdir}/rename_and_orient/{tol_id}.{hap_prefix}.primary.renamed.fa``
        ``{workdir}/rename_and_orient/{tol_id}.{hap_prefix}.primary.renamed.mapping.tsv``
    """
    log.info("rename-and-orient | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Rename and orient to reference")

    # --- find FastGA PAF ---
    if ctx.print_only:
        paf_file = ctx.workdir / "fastga" / "example.FastGA.paf"
    else:
        fastga_dir = find_latest_dir(ctx, "fastga")
        paf_matches = glob.glob(str(fastga_dir / "*FastGA.paf"))
        if not paf_matches:
            raise FileNotFoundError(
                f"No FastGA PAF found in {fastga_dir}\nRun 'grit fastga -t {ctx.ticket_id}' first."
            )
        paf_file = Path(sorted(paf_matches)[-1])
    log.info("FastGA PAF: %s", paf_file)

    mapping_tsv = _run_rename_and_orient_for_hap(
        ctx, ctx.hap1_prefix, paf_file, "rename_and_orient"
    )

    if run_hap2:
        print_step_header(ctx.ticket_id, ctx.tol_id,
                          f"Rename and orient to reference ({ctx.hap2_prefix})")
        _run_rename_and_orient_for_hap(
            ctx, ctx.hap2_prefix, paf_file, "rename_and_orient_hap2",
            mapping_table=mapping_tsv,
        )

    outdir = ctx.workdir / "rename_and_orient"
    print_done(f"Renamed FASTA(s) saved to {outdir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("rename-and-orient", cls=GritCommand)
@click.option("--hap2", "run_hap2", is_flag=True, default=False,
              help="Also rename and orient hap2 using the mapping table from hap1.")
@click.pass_context
def rename_and_orient_cmd(ctx, run_hap2):
    """Rename and orient chromosomes in curated FASTA based on FastGA PAF alignment."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_rename_and_orient(curation_ctx, run_hap2=run_hap2)
    except Exception:
        log.exception("rename-and-orient failed")
        raise SystemExit(1)
