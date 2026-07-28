"""Run BUSCO synteny analysis."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, _state_update_epilogue, _submit_bsub, build_bsub_opts, find_latest_dir
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REHEADER_SCRIPT = "/software/grit/projects/vgp_curation_scripts/reheader_fna.py"
# Path to the bundled busco-synteny script (relative to repo root)
_BUSCO_SYNTENY_SCRIPT = _REPO_ROOT / "scripts" / "busco-synteny.sh"


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_busco_synteny(ctx: CurationContext, lineage: str) -> None:
    """
    Runs BUSCO synteny analysis between the curated assembly and a reference genome.

    Steps:
        1. Ensure reference is available (download if needed).
        2. Prepare reference: gunzip, rename .fa to .fna, reheader, replace 'chr' with 'SUPER'.
        3. Find the curated hap1 FASTA as query.
        4. Submit BUSCO synteny job via bsub.

    Command structure:
        bsub -n 32 -o o_busco_synt -M 50G -R'select[mem>50G] rusage[mem=50G] span[hosts=1]' \\
            busco_synteny.sh -r <ref_fasta> -q <query_fasta> -l <lineage>

    Prints:
        Step header, reference preparation commands, bsub command.
    """
    log.info("busco-synteny | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run BUSCO synteny")

    # --- ensure reference is available ---
    ref_dir = find_latest_dir(ctx, "find_reference")
    ref_patterns = [
        str(ref_dir / "*_reheader.fa"),
        str(ref_dir / "*_reheader.fna"),
        str(ref_dir / "*.fa"),
        str(ref_dir / "*.fna"),
        str(ref_dir / "*.fa.gz"),
        str(ref_dir / "*.fna.gz"),
    ]
    ref_path = None
    for pattern in ref_patterns:
        if ctx.print_only:
            ref_path = Path(pattern.replace("*", "GCA_example"))
            break
        matches = glob.glob(pattern)
        if matches:
            ref_path = Path(sorted(matches)[-1])
            break

    if ref_path is None or (not ctx.print_only and not ref_path.exists()):
        log.info("No reference found, running find-reference first")
        from grit.steps.pre_curation.find_reference import find_closest_reference

        find_closest_reference(ctx)
        ref_dir = find_latest_dir(ctx, "find_reference")
        ref_matches = glob.glob(str(ref_dir / "*.fa.gz")) + glob.glob(str(ref_dir / "*.fa"))
        if not ref_matches:
            raise FileNotFoundError(f"No reference found in {ref_dir}")
        ref_path = Path(sorted(ref_matches)[-1])

    log.info("Reference FASTA: %s", ref_path)

    # --- prepare reference ---
    raw_stem = ref_path.stem.split(".")[0]
    ref_prefix = raw_stem.removesuffix("_reheader")
    ref_fna = ref_dir / f"{ref_prefix}.fna"
    ref_reheader = ref_dir / f"{ref_prefix}_reheader.fna"

    prep_cmds = []

    # gunzip if needed
    if ref_path.suffix == ".gz":
        gunzip_cmd = f"gunzip {ref_path}"
        prep_cmds.append(gunzip_cmd)
        ref_unzipped = ref_path.with_suffix("")
    else:
        ref_unzipped = ref_path

    # mv .fa to .fna if needed
    if ref_unzipped.suffix == ".fa":
        mv_cmd = f"mv {ref_unzipped} {ref_fna}"
        prep_cmds.append(mv_cmd)
    else:
        ref_fna = ref_unzipped

    # reheader
    reheader_cmd = f"python {_REHEADER_SCRIPT} {ref_fna}"
    prep_cmds.append(reheader_cmd)

    # sed to replace chr with SUPER
    sed_cmd = f"sed -i 's/chr/SUPER/g' {ref_reheader}"
    prep_cmds.append(sed_cmd)

    # Run preparation commands
    for cmd in prep_cmds:
        _run(cmd, ctx.print_only)

    log.info("Prepared reference: %s", ref_reheader)

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
    inner_cmd = f"bash {_BUSCO_SYNTENY_SCRIPT} -r {ref_reheader} -q {query_fa} -l {lineage} -p {ctx.workdir}"
    run_dir = ctx.tracker.start("busco_synteny", ctx.ticket_id, ctx.tol_id, invalidated=ctx.invalidated) if ctx.tracker else None
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
@click.pass_context
def busco_synteny_cmd(ctx, lineage):
    """Run BUSCO synteny analysis between curated assembly and reference genome."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_busco_synteny(curation_ctx, lineage)
    except Exception:
        log.exception("busco-synteny failed")
        raise SystemExit(1)
