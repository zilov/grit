"""Run BUSCO on curated genome."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _state_update_epilogue,
    _submit_bsub,
    build_bsub_opts,
    find_latest_dir,
    write_fake_outputs,
)
from grit.utils.modules import module_cmd
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

# BUSCO always creates a folder of its own named after -o and refuses to write
# into an existing one (-f makes it rm -rf that folder instead, which on the run
# dir would delete the LSF logs and its own cwd). So it writes into a staging
# subdir that is flattened into the run dir as soon as it finishes.
_BUSCO_STAGE_DIR = "busco_out"
_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("summary", "short_summary.specific.*.txt", []),
    ("full_table", "run_*/full_table.tsv", []),
]


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def _dry_run_busco_curated(ctx: CurationContext, run_dir: Path) -> dict[str, str]:
    """Write one placeholder per _OUTPUT_SPECS into *run_dir*, returning {key: path}."""
    return write_fake_outputs(
        "busco_curated", run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
    )


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

    BUSCO runs from the step's run dir and writes into a staging subdir that is
    flattened into it on success, so the outputs sit directly in
    ``{workdir}/busco_curated/{timestamp}/`` beside the LSF logs.

    Prints:
        Step header, input FASTA, file size, memory allocation, bsub command.
    """
    log.info("busco-curated | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run BUSCO on curated genome")

    if ctx.dry_run:
        run_dir = ctx.tracker.start(
            "busco_curated", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        outputs = _dry_run_busco_curated(ctx, run_dir)
        ctx.tracker.finish(
            "busco_curated", run_dir, "success", outputs=outputs, untracked=ctx.untracked
        )
        print_done(f"[dry-run] BUSCO on curated genome → {run_dir}")
        return

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

    mem_mb = ctx.bsub_ram or mem_mb
    mem_gb = mem_mb // 1000
    log.info("File size: %.2f GB", file_size_gb)
    log.info("Memory allocation: %d GB", mem_gb)

    # --- build inner command ---
    # BUSCO's -o is a *name*, not a path: given a path it strips the leading
    # slash and recreates the whole tree under the cwd. The directory goes in
    # --out_path, and the cd keeps busco_downloads/ out of wherever grit ran.
    run_dir = (
        ctx.tracker.start("busco_curated", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / "busco_curated" / "untracked"
    )
    stage_dir = run_dir / _BUSCO_STAGE_DIR
    busco_lineage = str(Path(_BUSCO_LINEAGES) / lineage)
    inner_cmd = (
        f"cd {run_dir} && "
        f"{module_cmd('GRIT')} && "
        f"singularity exec -B /lustre {_BUSCO_SIF} busco "
        f"-i {curated_fa} -o {_BUSCO_STAGE_DIR} --out_path {run_dir} -m genome "
        f"-l {busco_lineage} -c 32 && "
        f"mv {stage_dir}/* {run_dir}/ && rmdir {stage_dir}"
    )

    # --- build bsub options ---
    bsub_opts = build_bsub_opts(
        memory_mb=mem_mb,
        cores=32,
        output=f"o_busco_{mem_gb}",
        error=f"e_busco_{mem_gb}",
        run_dir=run_dir,
    )

    # --- submit ---
    epilogue = (
        _state_update_epilogue(ctx.workdir, "busco_curated", run_dir, untracked=ctx.untracked)
        if run_dir
        else None
    )
    job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
    if ctx.tracker and run_dir and job_id:
        ctx.tracker.record_job("busco_curated", run_dir, job_id)

    print_done("BUSCO on curated genome submitted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command(
    "busco-curated",
    cls=GritCommand,
    bsub_ram_help=(
        "LSF memory limit in MB "
        "(default: auto-scaled by curated FASTA size — 50000/100000/150000/220000)."
    ),
)
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
