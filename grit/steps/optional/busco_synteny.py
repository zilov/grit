"""Run BUSCO synteny analysis."""

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
    find_reheadered_reference,
)
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to the bundled busco-synteny script (relative to repo root)
_BUSCO_SYNTENY_SCRIPT = _REPO_ROOT / "scripts" / "busco-synteny.sh"


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_busco_synteny(
    ctx: CurationContext, lineage: str, reference_path: str | None = None
) -> None:
    """
    Runs BUSCO synteny analysis between the curated assembly and a reference genome.

    Steps:
        1. Find the reheadered reference (explicit --reference, or the one
           produced by 'grit find-reference').
        2. Find the curated hap1 FASTA as query.
        3. Submit BUSCO synteny job via bsub.

    Command structure:
        bsub -n 32 -o o_busco_synt -M 50G -R'select[mem>50G] rusage[mem=50G] span[hosts=1]' \\
            busco_synteny.sh -r <ref_fasta> -q <query_fasta> -l <lineage>

    Prints:
        Step header, bsub command.
    """
    log.info("busco-synteny | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run BUSCO synteny")

    from grit.steps.pre_curation.find_reference import reheader_reference

    # --- find reference ---
    if reference_path:
        ref_path = Path(reference_path)
        if not ctx.print_only and not ref_path.exists():
            raise FileNotFoundError(f"Reference not found: {ref_path}")
        log.info("Reference FASTA (explicit): %s", ref_path)
        ref_reheader = reheader_reference(ctx, ref_path)
    else:
        ref_reheader = find_reheadered_reference(ctx)
        log.info("Reference FASTA: %s", ref_reheader)

    # --- find query fasta (curated hap1) ---
    # haplotig-files writes *.curated.fa into the pretext_to_asm run dir, not workdir root
    if ctx.print_only:
        query_fa = ctx.workdir / f"{ctx.tol_id}.{ctx.hap1_prefix}.primary.curated.fa"
    else:
        base_dir = find_latest_dir(ctx, "pretext_to_asm")
        query_pattern = str(base_dir / f"{ctx.tol_id}*{ctx.hap1_prefix}*.curated.fa")
        query_matches = glob.glob(query_pattern)
        if not query_matches:
            raise FileNotFoundError(f"No curated hap1 FASTA found: {query_pattern}")
        query_fa = Path(sorted(query_matches)[-1])
    log.info("Query FASTA: %s", query_fa)

    # --- submit BUSCO synteny job ---
    # Each run gets its own run_dir so multiple busco-synteny runs don't overwrite each other
    run_dir = (
        ctx.tracker.start("busco_synteny", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / "busco_synteny" / "untracked"
    )
    inner_cmd = (
        f"bash {_BUSCO_SYNTENY_SCRIPT} -r {ref_reheader} -q {query_fa} -l {lineage} -p {run_dir}"
    )
    bsub_opts = build_bsub_opts(
        cores=32,
        memory_mb=50000,
        output="o_busco_synt",
        run_dir=run_dir,
    )
    epilogue = _state_update_epilogue(ctx.workdir, "busco_synteny", run_dir) if run_dir else None
    job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
    if ctx.tracker and run_dir and job_id:
        ctx.tracker.record_job("busco_synteny", run_dir, job_id)

    print_done("BUSCO synteny submitted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("busco-synteny", cls=GritCommand)
@click.option("--lineage", required=True, help="BUSCO lineage name (e.g. insecta_odb10).")
@click.option(
    "--reference",
    "-r",
    default=None,
    help="Path to reference FASTA (overrides auto-search via find-reference).",
)
@click.pass_context
def busco_synteny_cmd(ctx, lineage, reference):
    """Run BUSCO synteny analysis between curated assembly and reference genome."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_busco_synteny(curation_ctx, lineage, reference_path=reference)
    except Exception:
        log.exception("busco-synteny failed")
        raise SystemExit(1)
