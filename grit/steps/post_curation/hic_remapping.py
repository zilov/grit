"""Step: submit the HiC remapping pipeline (sanger-tol/curationpretext) via bsub."""

from __future__ import annotations

import logging
import re

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, find_canonical_fa, find_latest_dir
from grit.utils.modules import module_cmd
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _submit_hic_remapping(ctx: CurationContext, hap_prefix: str, step_name: str) -> None:
    """Submit one curationpretext run for *hap_prefix*, tracked under *step_name*."""

    # Check for existing successful run; re-run only if curated FASTA is newer
    if not ctx.print_only and ctx.tracker:
        prev_dir = ctx.tracker.latest_run_dir(step_name)
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
                log.info("Curated FASTA is newer than remapped pretext — re-running %s", step_name)
            else:
                log.info("HiC remapping already done — skipping: %s", prev_dir)
                last = ctx.tracker.history(step_name)
                if last and last[-1].get("status") == "started":
                    ctx.tracker.finish(step_name, prev_dir, "success")
                print_done(f"Already done → {prev_dir}")
                return

    run_dir = (
        ctx.tracker.start(step_name, ctx.ticket_id, ctx.tol_id, suffix=hap_prefix)
        if ctx.tracker
        else ctx.workdir / step_name / "untracked"
    )

    input_fa = find_canonical_fa(ctx, hap_prefix)
    log.info("Input FASTA: %s", input_fa)

    sample = f"{ctx.tol_id}.{hap_prefix}"

    hic_cmd = (
        f"cd {run_dir} && "
        f"{module_cmd('CURATIONPRETEXT')} && "
        f"curationpretext.sh -profile sanger,singularity"
        f" --map_order unsorted"
        f" --input {input_fa}"
        f" --sample {sample}"
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
        if ctx.tracker and run_dir and output and "Job <" in output:
            m = re.search(r"Job <(\d+)>", output)
            if m:
                ctx.tracker.record_job(step_name, run_dir, m.group(1))
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish(step_name, run_dir, "failed")
        raise

    remapped_pattern = str(run_dir / "pretext_maps_processed" / f"{sample}*normal.pretext")
    scp_cmd = (
        f"scp {ctx.farm_host}:{remapped_pattern}"
        f" ~/curations/{ctx.tol_id}/{sample}_remapped.pretext"
    )
    console.print("\n[bold]After remapping, copy the map to your local machine:[/bold]")
    console.print(f"  [green]{scp_cmd}[/green]")


# ---------------------------------------------------------------------------
# Public step function
# ---------------------------------------------------------------------------


def run_hic_remapping(ctx: CurationContext, *, run_hap2: bool = False) -> None:
    """
    Runs the HiC remapping pipeline (sanger-tol/curationpretext).

    Submits hap1 by default. Pass ``run_hap2=True`` to also submit hap2
    (tracked separately as ``hic_remapping_hap2``).

    Output goes into timestamped run directories:
    ``{workdir}/hic_remapping/<timestamp>/``
    ``{workdir}/hic_remapping_hap2/<timestamp>/``

    Steps:
        1. Find canonical FASTA for each haplotype (rename_and_orient output takes
           priority over pretext_to_asm output).
        2. Start a new run_dir via tracker.
        3. cd to run_dir and submit curationpretext.sh with run_dir as outdir.
        4. Print scp command to copy remapped pretext map to local machine.

    Next step hint: ``run_qv(ctx)``
    """
    log.info("hic-remapping | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "HiC remapping")

    _submit_hic_remapping(ctx, ctx.hap1_prefix, "hic_remapping")

    if run_hap2:
        print_step_header(ctx.ticket_id, ctx.tol_id, f"HiC remapping ({ctx.hap2_prefix})")
        _submit_hic_remapping(ctx, ctx.hap2_prefix, "hic_remapping_hap2")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("hic-remapping", cls=GritCommand)
@click.option("--hap2", "run_hap2", is_flag=True, default=False,
              help="Also submit HiC remapping for hap2.")
@click.pass_context
def hic_remapping_cmd(ctx, run_hap2):
    """Submit HiC remapping pipeline."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_hic_remapping(curation_ctx, run_hap2=run_hap2)
    except Exception:
        log.exception("hic-remapping failed")
        raise SystemExit(1)
