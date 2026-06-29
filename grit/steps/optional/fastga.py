"""Run FastGA dot-plot comparison."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, _state_update_epilogue, _submit_bsub, build_bsub_opts, find_canonical_fa, find_latest_dir
from grit.utils.modules import module_cmd
from grit.utils.output import (
    print_done,
    print_step_header,
    print_tip,
)

log = logging.getLogger(__name__)


def _fastga_scp_tip(farm_host: str, run_dir: Path, tol_id: str, print_only: bool = False) -> str | None:
    """Return a print_tip string with scp commands for FastGA outputs, or None if no files found."""
    local_dir = f"~/curations/work/{tol_id}"
    if print_only:
        files = [str(run_dir / f"{tol_id}.fa.idx"), str(run_dir / f"{tol_id}_FastGA.paf")]
    else:
        files = sorted(glob.glob(str(run_dir / "*.idx")) + glob.glob(str(run_dir / "*FastGA.paf")))
    if not files:
        return None
    cmds = " && \\\n".join(f"scp {farm_host}:{f} {local_dir}" for f in files)
    return f"Download FastGA results:\n[bold cyan]{cmds}[/bold cyan]"


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

    # --- find canonical hap1 FASTA (rename_and_orient output preferred) ---
    hap1_fa = find_canonical_fa(ctx, ctx.hap1_prefix)
    log.info("Curated hap1 FASTA: %s", hap1_fa)

    # --- find reference ---
    if reference_path:
        ref_path = Path(reference_path)
        if not ctx.print_only and not ref_path.exists():
            raise FileNotFoundError(f"Reference not found: {ref_path}")
        log.info("Reference FASTA (explicit): %s", ref_path)
    else:
        ref_dir = find_latest_dir(ctx, "find_reference")
        ref_patterns = [
            str(ref_dir / "*.fna.gz"),
            str(ref_dir / "*.fna"),
            str(ref_dir / "*.fa.gz"),
            str(ref_dir / "*.fa"),
        ]
        ref_path = None
        for pattern in ref_patterns:
            matches = glob.glob(pattern)
            if matches:
                ref_path = Path(sorted(matches)[-1])
                break

        if ref_path is None or (not ctx.print_only and not ref_path.exists()):
            log.info("No reference found, running find-reference first")
            from grit.steps.pre_curation.find_reference import find_closest_reference

            find_closest_reference(ctx)
            ref_dir = find_latest_dir(ctx, "find_reference")
            ref_matches = glob.glob(str(ref_dir / "*.fna.gz")) + glob.glob(str(ref_dir / "*.fna"))
            if not ref_matches:
                raise FileNotFoundError(f"No reference found in {ref_dir}")
            ref_path = Path(sorted(ref_matches)[-1])

        log.info("Reference FASTA: %s", ref_path)

    # --- prepare reference (gunzip + reheader if needed) ---
    # Strip _reheader suffix so repeated runs don't chain: GCA_reheader_reheader_reheader.fna
    raw_stem = ref_path.stem.split(".")[0]
    ref_prefix = raw_stem.removesuffix("_reheader")
    assembly_prefix = hap1_fa.stem.split(".")[0]
    run_prefix = f"{ref_prefix}_vs_{assembly_prefix}"
    ref_reheader = ref_path.parent / f"{ref_prefix}_reheader.fna"

    if ref_reheader.exists():
        log.info("Reheadered reference already exists — skipping prep: %s", ref_reheader)
    else:
        if ref_path.suffix == ".gz":
            prep_cmd = f"gunzip {ref_path} && reheader {ref_path.with_suffix('')} > {ref_reheader}"
        else:
            prep_cmd = f"reheader {ref_path} > {ref_reheader}"
        ml_grit = module_cmd("GRIT")
        _run(f"{ml_grit} && {prep_cmd}", ctx.print_only)

    # --- submit bsub job ---
    # Each run gets its own tracker run_dir so multiple fastga runs don't overwrite each other
    run_dir = ctx.tracker.start("fastga", ctx.ticket_id, ctx.tol_id) if ctx.tracker else ctx.workdir / "fastga" / "untracked"
    fastga_script = "/software/grit/projects/vgp_curation_scripts/FastGA_dot_dgenies.sh"
    inner_cmd = (
        f"cd {run_dir} && "
        f"{module_cmd('GRIT')} && "
        f"{fastga_script} {ref_reheader} {hap1_fa} {run_prefix} {run_dir}"
    )
    bsub_opts = build_bsub_opts(
        group="team135",
        cores=8,
        memory_mb=24000,
        output="o_fastga",
        error="e_fastga",
        run_dir=run_dir,
    )
    epilogue = _state_update_epilogue(ctx.workdir, "fastga", run_dir) if run_dir else None
    try:
        job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
        if ctx.tracker and run_dir and job_id:
            ctx.tracker.record_job("fastga", run_dir, job_id)
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("fastga", run_dir, "failed")
        raise

    # --- tip: scp commands if output already exists ---
    tip = _fastga_scp_tip(ctx.farm_host, run_dir, ctx.tol_id, ctx.print_only)
    if tip:
        print_tip(tip)

    print_done("FastGA submitted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("fastga", cls=GritCommand)
@click.option("--reference", "-r", default=None, help="Path to reference FASTA (overrides auto-search in workdir/reference/).")
@click.pass_context
def fastga_cmd(ctx, reference):
    """Run FastGA dot-plot comparison of curated assembly vs reference."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_fastga(curation_ctx, reference_path=reference)
    except Exception:
        log.exception("fastga failed")
        raise SystemExit(1)
