"""Run BUSCO on curated genome."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _state_update_epilogue, _submit_bsub, build_bsub_opts, find_latest_dir
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUSCO_SIF = "/nfs/treeoflife-01/teams/grit/users/mh6/singularity/busco.sif"
_BUSCO_LINEAGES = "/lustre/scratch122/tol/resources/busco/latest/lineages"


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_busco_curated(ctx: CurationContext, lineage: str) -> None:
    """
    Runs BUSCO analysis on the curated genome assembly.

    Steps:
        1. Find the curated FASTA file (merged or hap1 curated.fa).
        2. Determine file size and select appropriate memory allocation.
        3. Submit BUSCO job via bsub using singularity.

    Memory allocation based on FASTA size:
        - < 1GB: 50GB
        - < 2GB: 100GB
        - < 3GB: 150GB
        - >= 3GB: 220GB

    Command structure:
        bsub -q normal -e e_busco_{mem_gb} -o o_busco_{mem_gb} -n 32 -M {mem_mb} \\
            -R'select[mem>{mem_mb}] rusage[mem={mem_mb}] span[hosts=1]' \\
            singularity exec -B /lustre {_BUSCO_SIF} busco \\
                -i {input_fa} -o {output_dir} -m genome \\
                -l {_BUSCO_LINEAGES}/{lineage} -c 32 -f

    Prints:
        Step header, input FASTA, file size, memory allocation, bsub command.
    """
    log.info("busco-curated | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run BUSCO on curated genome")

    # --- find curated FASTA ---
    # haplotig-files writes *.curated.fa into the pretext_to_asm run dir, not workdir root
    if ctx.print_only:
        curated_fa = ctx.workdir / f"{ctx.tol_id}_merged_curated.{ctx.hap1_prefix}.fa"
    else:
        base_dir = find_latest_dir(ctx, "pretext_to_asm")
        curated_pattern = str(base_dir / f"{ctx.tol_id}*.curated.fa")
        curated_matches = glob.glob(curated_pattern)
        if not curated_matches:
            raise FileNotFoundError(f"No curated FASTA found: {curated_pattern}")
        curated_fa = Path(sorted(curated_matches)[-1])
    log.info("Curated FASTA: %s", curated_fa)

    # --- determine file size and memory ---
    if ctx.print_only:
        file_size_gb = 2.5  # example
    else:
        file_size_bytes = curated_fa.stat().st_size
        file_size_gb = file_size_bytes / (1024**3)

    if file_size_gb < 1:
        mem_mb = 50000
    elif file_size_gb < 2:
        mem_mb = 100000
    elif file_size_gb < 3:
        mem_mb = 150000
    else:
        mem_mb = 220000

    mem_gb = mem_mb // 1000
    log.info("File size: %.2f GB", file_size_gb)
    log.info("Memory allocation: %d GB", mem_gb)

    # --- build output dir ---
    output_dir = ctx.workdir / f"{ctx.tol_id}_busco_singularity"

    # --- build inner command ---
    busco_lineage = str(Path(_BUSCO_LINEAGES) / lineage)
    inner_cmd = (
        f"singularity exec -B /lustre {_BUSCO_SIF} busco "
        f"-i {curated_fa} -o {output_dir} -m genome "
        f"-l {busco_lineage} -c 32 -f"
    )

    # --- build bsub options ---
    run_dir = ctx.tracker.start("busco_curated", ctx.ticket_id, ctx.tol_id) if ctx.tracker else None
    bsub_opts = build_bsub_opts(
        memory_mb=mem_mb,
        cores=32,
        output=f"o_busco_{mem_gb}",
        error=f"e_busco_{mem_gb}",
        run_dir=run_dir,
    )

    # --- submit ---
    epilogue = _state_update_epilogue(ctx.workdir, "busco_curated", run_dir) if run_dir else None
    job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
    if ctx.tracker and run_dir and job_id:
        ctx.tracker.record_job("busco_curated", run_dir, job_id)

    print_done("BUSCO on curated genome submitted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("busco-curated", cls=GritCommand)
@click.option("--lineage", required=True, help="BUSCO lineage name (e.g. insecta_odb10).")
@click.pass_context
def busco_curated_cmd(ctx, lineage):
    """Run BUSCO on the curated genome assembly."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_busco_curated(curation_ctx, lineage)
    except Exception:
        log.exception("busco-curated failed")
        raise SystemExit(1)
