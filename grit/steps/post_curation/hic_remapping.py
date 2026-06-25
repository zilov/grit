"""Step: submit the HiC remapping pipeline (sanger-tol/curationpretext) via bsub."""

from __future__ import annotations

import glob
import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, find_latest_dir
from grit.utils.modules import module_cmd
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_hic_remapping(ctx: CurationContext) -> None:
    """
    Runs the HiC remapping pipeline (sanger-tol/curationpretext).

    Output goes into a timestamped run directory:
    ``{workdir}/hic_remapping/<timestamp>/``

    curationpretext.sh submits its own bsub job internally, so grit calls it
    directly (cd workdir first so logs and work/ land inside the run_dir).

    Notebook source: ``pre_and_post_curation()`` — ``hic_cmd`` section.

    Steps:
        1. Find the primary curated FASTA from the latest pretext_to_asm run.
        2. Start a new hic_remapping run_dir via tracker.
        3. cd to workdir and run curationpretext.sh with run_dir as outdir.
        4. Print scp command to copy the remapped pretext map to local machine.

    Prints:
        Step header, command, scp command for remapped pretext.
    Next step hint: ``run_qv(ctx)``
    """
    log.info("hic-remapping | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "HiC remapping")

    # Check for existing successful run; re-run if curated FASTA is newer than remapped pretext
    if not ctx.print_only and ctx.tracker:
        prev_dir = ctx.tracker.latest_run_dir("hic_remapping")
        hr_pretexts = (
            list(prev_dir.glob(f"pretext_maps_processed/{ctx.tol_id}*hr.pretext"))
            if prev_dir else []
        )
        if hr_pretexts:
            pta_dir = find_latest_dir(ctx, "pretext_to_asm")
            curated_fas = list(pta_dir.glob(f"{ctx.tol_id}*.curated.fa"))
            pretext_mtime = min(f.stat().st_mtime for f in hr_pretexts)
            fa_newer = curated_fas and max(
                f.stat().st_mtime for f in curated_fas
            ) > pretext_mtime
            if fa_newer:
                log.info("Curated FASTA is newer than remapped pretext — re-running hic_remapping")
            else:
                log.info("HiC remapping already done — skipping: %s", prev_dir)
                # Retroactively record success if the last log entry is still 'started'
                last = ctx.tracker.history("hic_remapping")
                if last and last[-1].get("status") == "started":
                    ctx.tracker.finish("hic_remapping", prev_dir, "success")
                print_done(f"Already done → {prev_dir}")
                return

    # Start tracking — run_dir is the nextflow outdir
    run_dir = ctx.tracker.start("hic_remapping", ctx.ticket_id, ctx.tol_id) if ctx.tracker else ctx.workdir / "hic_remapping" / "untracked"

    # Resolve input FASTA from pretext_to_asm run_dir (or workdir as fallback)
    if ctx.print_only:
        pta_dir = ctx.workdir / "pretext_to_asm" / "<timestamp>"
    else:
        pta_dir = find_latest_dir(ctx, "pretext_to_asm")

    hap1_fa_pattern = str(pta_dir / f"{ctx.tol_id}*.{ctx.hap1_prefix}*.curated.fa")

    if ctx.print_only:
        hap1_fa = hap1_fa_pattern
        log.info("Input FASTA (pattern): %s", hap1_fa)
    else:
        hap1_files = [f for f in glob.glob(hap1_fa_pattern) if "all_haplotigs" not in f]
        if not hap1_files:
            hap1_files = [f for f in glob.glob(str(pta_dir / f"{ctx.tol_id}*.curated.fa")) if "all_haplotigs" not in f]
        if not hap1_files:
            if ctx.tracker:
                ctx.tracker.finish("hic_remapping", run_dir, "failed")
            raise FileNotFoundError(
                f"No curated FASTA found at {hap1_fa_pattern}. "
                "Run run_pretext_to_asm first."
            )
        hap1_fa = hap1_files[0]
        log.info("Input FASTA: %s", hap1_fa)

    hic_cmd = (
        f"cd {run_dir} && "
        f"{module_cmd('CURATIONPRETEXT')} && "
        f"curationpretext.sh -profile sanger,singularity"
        f" --map_order unsorted"
        f" --input {hap1_fa}"
        f" --sample {ctx.tol_id}"
        f" --cram {ctx.hic_dir}"
        f" --reads {ctx.long_reads_dir}/fasta"
        f" --read_type {ctx.read_type}"
        f" --outdir {run_dir}"
    )
    if ctx.teloseq:
        hic_cmd += f" {ctx.teloseq}"
    hic_cmd += " -resume"

    try:
        output = _run(hic_cmd, ctx.print_only)
        # curationpretext.sh prints the bsub job ID — parse and record it so
        # grit status can poll bjobs for live status while the job runs
        if ctx.tracker and run_dir and output and "Job <" in output:
            import re
            m = re.search(r"Job <(\d+)>", output)
            if m:
                ctx.tracker.record_job("hic_remapping", run_dir, m.group(1))
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish("hic_remapping", run_dir, "failed")
        raise

    remapped_pattern = str(run_dir / "pretext_maps_processed" / f"{ctx.tol_id}*normal.pretext")
    scp_cmd = (
        f"scp {ctx.farm_host}:{remapped_pattern}"
        f" ~/curations/{ctx.tol_id}/{ctx.tol_id}_remapped.pretext"
    )
    console.print("\n[bold]After remapping, copy the map to your local machine:[/bold]")
    console.print(f"  [green]{scp_cmd}[/green]")



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
