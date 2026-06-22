"""Run FastGA dot-plot comparison."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, _state_update_epilogue, _submit_bsub, build_bsub_opts, find_latest_dir
from grit.utils.modules import module_cmd
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_fastga(ctx: CurationContext, reference_path: str | None = None) -> None:
    """
    Runs a FastGA dot-plot comparison of the curated assembly vs. a reference.

    Notebook source: ``run_fastga()`` and ``scp_fastga()`` functions.

    Steps:
        1. Determine the primary curated hap1 FASTA in ``ctx.workdir``.
        2. If reference is gzipped and not yet decompressed/reheadered::

               ml grit && gunzip {ref} && \
               reheader {ref.replace('.gz', '')} > {ref_reheader}

        3. Build bsub command::

               bsub -G team135 -n 8 -e e_fastga -o o_fastga \
                   -M 24000 -R'...' \
                   /software/grit/projects/vgp_curation_scripts/FastGA_dot_dgenies.sh \
                   {ref_reheader} {hap1_fa} {run_prefix} {outdir}

        4. Print command and submit via subprocess.
        5. If a ``fastga/`` output directory already exists: print scp commands
           for the index and PAF files::

               scp {ctx.farm_host}:{fastga_outdir}/*.f*a.idx ~/curations/.../
               scp {ctx.farm_host}:{fastga_outdir}/*FastGA.paf ~/curations/.../

    Prints:
        Step header, bsub command, scp commands (if output exists).
    """
    log.info("fastga | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run FastGA")

    # --- find curated hap1 fa ---
    # haplotig-files writes *.curated.fa into the pretext_to_asm run dir, not workdir root
    if ctx.print_only:
        hap1_fa = ctx.workdir / f"{ctx.tol_id}.{ctx.hap1_prefix}.primary.curated.fa"
    else:
        base_dir = find_latest_dir(ctx, "pretext_to_asm")
        hap1_pattern = str(base_dir / f"{ctx.tol_id}*{ctx.hap1_prefix}*.curated.fa")
        hap1_matches = glob.glob(hap1_pattern)
        if not hap1_matches:
            raise FileNotFoundError(f"No curated hap1 FASTA found: {hap1_pattern}")
        hap1_fa = Path(sorted(hap1_matches)[-1])
    log.info("Curated hap1 FASTA: %s", hap1_fa)

    # --- find reference ---
    ref_dir = ctx.workdir / "reference"
    ref_patterns = [
        str(ctx.workdir / "GC*.fna.gz"),
        str(ctx.workdir / "GC*.fna"),
        str(ref_dir / "*.fna.gz"),
        str(ref_dir / "*.fna"),
    ]
    ref_path = None
    for pattern in ref_patterns:
        if ctx.print_only:
            ref_path = Path(pattern.replace("*", "example"))
            break
        matches = glob.glob(pattern)
        if matches:
            ref_path = Path(sorted(matches)[-1])
            break

    if ref_path is None or (not ctx.print_only and not ref_path.exists()):
        log.info("No reference found, downloading closest reference")
        from grit.steps.find_reference import find_closest_reference

        find_closest_reference(ctx)
        # After download, find again
        ref_matches = glob.glob(str(ref_dir / "*.fna.gz")) + glob.glob(str(ref_dir / "*.fna"))
        if not ref_matches:
            raise FileNotFoundError(f"No reference downloaded to {ref_dir}")
        ref_path = Path(sorted(ref_matches)[-1])

    log.info("Reference FASTA: %s", ref_path)

    # --- prepare reference (gunzip + reheader if needed) ---
    ref_prefix = ref_path.stem.split(".")[0]
    assembly_prefix = hap1_fa.stem.split(".")[0]
    run_prefix = f"{ref_prefix}_vs_{assembly_prefix}"
    outdir = ctx.workdir / "fastga"
    ref_reheader = ctx.workdir / f"{ref_prefix}_reheader.fna"

    if ref_path.suffix == ".gz":
        gunzip_cmd = f"gunzip {ref_path}"
        reheader_cmd = f"reheader {ref_path.with_suffix('')} > {ref_reheader}"
        prep_cmd = f"{gunzip_cmd} && {reheader_cmd}"
    else:
        prep_cmd = f"reheader {ref_path} > {ref_reheader}"

    ml_grit = module_cmd("GRIT")
    _run(f"{ml_grit} && {prep_cmd}", ctx.print_only)

    run_dir = ctx.tracker.start("fastga", ctx.ticket_id, ctx.tol_id) if ctx.tracker else None

    fastga_script = "/software/grit/projects/vgp_curation_scripts/FastGA_dot_dgenies.sh"
    inner_cmd = f"{fastga_script} {ref_reheader} {hap1_fa} {run_prefix} {outdir}"
    bsub_opts = build_bsub_opts(
        group="team135",
        cores=8,
        memory_mb=24000,
        output="o_fastga",
        error="e_fastga",
    )
    epilogue = _state_update_epilogue(ctx.workdir, "fastga", run_dir) if run_dir else None
    job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)

    if ctx.tracker and run_dir and job_id:
        ctx.tracker.record_job("fastga", run_dir, job_id)

    # --- if output exists, print scp commands ---
    if ctx.print_only or outdir.exists():
        scp_local_dir = f"~/curations/work/{ctx.tol_id}"
        idx_files = (
            glob.glob(str(outdir / "*f*a.idx"))
            if not ctx.print_only
            else [str(outdir / "example.f*a.idx")]
        )
        paf_files = (
            glob.glob(str(outdir / "*FastGA.paf"))
            if not ctx.print_only
            else [str(outdir / "example.FastGA.paf")]
        )
        files_to_scp = idx_files + paf_files
        if files_to_scp:
            scp_cmds = [f"scp {ctx.farm_host}:{f} {scp_local_dir}" for f in files_to_scp]
            log.info("Scp FastGA results to local: %s", " && ".join(scp_cmds))

    print_done("FastGA submitted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("fastga", cls=GritCommand)
@click.pass_context
def fastga_cmd(ctx):
    """Run FastGA dot-plot comparison of curated assembly vs reference."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_fastga(curation_ctx)
    except Exception:
        log.exception("fastga failed")
        raise SystemExit(1)
