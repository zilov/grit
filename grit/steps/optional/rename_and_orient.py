"""Rename and orient chromosomes to reference."""

import glob
import logging
import subprocess
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.output import (
    console,
    print_done,
    print_info,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_rename_and_orient(ctx: CurationContext) -> None:
    """
    Renames and orients chromosomes in the curated FASTA based on FastGA PAF alignment to reference.

    Prerequisites:
        - Curated FASTA exists in workdir (from post-curation steps)
        - FastGA has been run and PAF file exists in fastga/ directory

    Steps:
        1. Find the curated hap1 FASTA in workdir.
        2. Find the FastGA PAF file in fastga/ directory.
        3. Run rename_and_orient.py script::

               python3 {script_path} --fasta {fasta} --paf {paf}
               --output-dir {outdir} --output-prefix {prefix}

    Prints:
        Step header, FASTA and PAF paths, command executed.
    """
    log.info("rename-and-orient | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Rename and orient to reference")

    # --- find curated hap1 fa ---
    hap1_pattern = str(ctx.workdir / f"{ctx.tol_id}*{ctx.hap1_prefix}*.curated.fa")
    if ctx.print_only:
        hap1_fa = ctx.workdir / f"{ctx.tol_id}.{ctx.hap1_prefix}.primary.curated.fa"
    else:
        hap1_matches = glob.glob(hap1_pattern)
        if not hap1_matches:
            raise FileNotFoundError(f"No curated hap1 FASTA found: {hap1_pattern}")
        hap1_fa = Path(sorted(hap1_matches)[-1])
    print_info("Curated hap1 FASTA", str(hap1_fa))

    # --- find FastGA PAF ---
    fastga_dir = ctx.workdir / "fastga"
    paf_pattern = str(fastga_dir / "*FastGA.paf")
    if ctx.print_only:
        paf_file = fastga_dir / "example.FastGA.paf"
    else:
        paf_matches = glob.glob(paf_pattern)
        if not paf_matches:
            raise FileNotFoundError(
                f"No FastGA PAF found: {paf_pattern}\nRun 'fastga' command first."
            )
        paf_file = Path(sorted(paf_matches)[-1])
    print_info("FastGA PAF", str(paf_file))

    # --- prepare output ---
    outdir = ctx.workdir / "rename_and_orient"
    prefix = f"{ctx.tol_id}.{ctx.hap1_prefix}.primary.renamed"

    # Path to the rename_and_orient.py script
    script_path = (
        Path(__file__).parent.parent.parent
        / "rename_and_orient_fasta_to_reference"
        / "rename_and_orient.py"
    )

    cmd = (
        f"python3 {script_path} "
        f"--fasta {hap1_fa} "
        f"--paf {paf_file} "
        f"--output-dir {outdir} "
        f"--output-prefix {prefix}"
    )

    console.print(f"\n[yellow]Command:[/yellow] [green]{cmd}[/green]")
    if ctx.print_only:
        return
    subprocess.run(cmd, shell=True, check=True)
    print_done(f"Renamed FASTA saved to {outdir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("rename-and-orient", cls=GritCommand)
@click.pass_context
def rename_and_orient_cmd(ctx):
    """Rename and orient chromosomes in curated FASTA based on FastGA PAF alignment."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_rename_and_orient(curation_ctx)
    except Exception:
        log.exception("rename-and-orient failed")
        raise SystemExit(1)
