"""Step: submit the HiC remapping pipeline (sanger-tol/curationpretext) via bsub."""

from __future__ import annotations

import glob
import logging
from datetime import datetime

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _submit_bsub, build_bsub_opts
from grit.utils.modules import module_cmd
from grit.utils.output import console, print_next_step, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_hic_remapping(ctx: CurationContext) -> None:
    """
    Submits the HiC remapping pipeline (sanger-tol/curationpretext) via bsub.

    Notebook source: ``pre_and_post_curation()`` — ``hic_cmd`` section.

    Steps:
        1. Determine the primary curated FASTA for remapping:
           ``{ctx.workdir}/{ctx.tol_id}*.{hap1_prefix}*.primary.curated.fa``
        2. Build the nextflow command via curationpretext.sh and submit via bsub.
        3. Print scp command to copy the remapped pretext map to local machine.

    Prints:
        Step header, bsub command, job ID, scp command for remapped pretext.
    Next step hint: ``run_qv(ctx)``
    """
    log.info("hic-remapping | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "HiC remapping")

    hap1_fa_pattern = str(ctx.workdir / f"{ctx.tol_id}*.{ctx.hap1_prefix}*.primary.curated.fa")

    if ctx.print_only:
        hap1_fa = hap1_fa_pattern
        log.info("Input FASTA (pattern): %s", hap1_fa)
    else:
        hap1_files = glob.glob(hap1_fa_pattern)
        if not hap1_files:
            # fallback: any primary curated fa
            hap1_files = glob.glob(str(ctx.workdir / f"{ctx.tol_id}*.primary.curated.fa"))
        if not hap1_files:
            raise FileNotFoundError(
                f"No primary curated FASTA found at {hap1_fa_pattern}. "
                "Run run_pretext_to_asm first."
            )
        hap1_fa = hap1_files[0]
        log.info("Input FASTA: %s", hap1_fa)

    outdir = ctx.workdir / f"{ctx.tol_id}_curationpretext"

    hic_cmd = (
        f"{module_cmd('CURATIONPRETEXT')} && "
        f"curationpretext.sh -profile sanger,singularity"
        f" --map_order unsorted"
        f" --input {hap1_fa}"
        f" --sample {ctx.tol_id}"
        f" --cram {ctx.hic_dir}"
        f" --reads {ctx.long_reads_dir}/fasta"
        f" --read_type {ctx.read_type}"
        f" --outdir {outdir}"
    )
    if ctx.teloseq:
        hic_cmd += f" {ctx.teloseq}"
    hic_cmd += " -resume"

    date_str = datetime.now().strftime("%d_%m_%Y")
    bsub_opts = build_bsub_opts(
        queue="oversubscribed",
        memory_mb=1200,
        output=f"curationpretext_{date_str}.log",
    )
    _submit_bsub(hic_cmd, bsub_opts, ctx.print_only)

    remapped_pattern = f"{outdir}/pretext_maps_processed/{ctx.tol_id}*normal.pretext"
    scp_cmd = (
        f"scp {ctx.farm_host}:{remapped_pattern}"
        f" ~/curations/{ctx.tol_id}/{ctx.tol_id}_remapped.pretext"
    )
    console.print("\n[bold]After remapping, copy the map to your local machine:[/bold]")
    console.print(f"  [green]{scp_cmd}[/green]")

    print_next_step("run_qv(ctx)")


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("hic-remapping", cls=GritCommand)
@click.pass_context
def hic_remapping_cmd(ctx):
    """Submit HiC remapping pipeline."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_hic_remapping(curation_ctx)
    except Exception:
        log.exception("hic-remapping failed")
        raise SystemExit(1)
