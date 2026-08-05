"""Microchromosome second-shot curation: pre-curation step."""

import glob
import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, collect_outputs
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

_SECOND_SHOT_SCRIPT = (
    "/software/grit/projects/vgp_curation_scripts/birds_microchromosomes/"
    "microchr_second_shot_curation.py"
)

# Confirm these globs against setup_paths() in microchr_second_shot_curation.py
# on first real run — patterns here are inferred from its documented output
# structure, not yet exercised against real output.
_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("hap1_large_fa", "*.hap1.large.fa", []),
    ("hap2_large_fa", "*.hap2.large.fa", []),
    ("hap1_large_chr", "*.hap1.large.chr_list.csv", []),
    ("hap2_large_chr", "*.hap2.large.chr_list.csv", []),
    ("merged_small_fa", "*_curated_small_merged.fa", []),
]

# ---------------------------------------------------------------------------
# Public step function
# ---------------------------------------------------------------------------


def run_microchromosome_second_shot(ctx: CurationContext) -> None:
    """
    PRE-curation step of the second-shot microchromosome workflow.

    Typically used for birds (tol_id starts with ``b``) and large genomes
    with many small chromosomes (<20 Mbp).

    Notebook source: ``bird_curation()`` function.

    Steps:
        1. Locate curated hap1 (and optionally hap2) FASTAs and chromosome
           lists from ``ctx.workdir``.
        2. Run ``microchr_second_shot_curation.py`` which splits the assembly
           into large (>20 Mbp) and small (≤20 Mbp) scaffolds and runs HiC
           remapping on the merged small scaffolds. The script blocks
           internally on its own ``bsub -K`` MicroFinder/merge jobs, so its
           progress streams live to this terminal — this step runs
           synchronously (not an async bsub submission) to preserve that.

    Next step: curate the micro pretext map locally, then run
    ``microchromosome-combine`` (``run_microchromosome_combine``).

    Tracked as ``microchromosome_second_shot``.
    """
    log.info("microchromosome-second-shot | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Microchromosome second-shot curation")

    # --- find curated fastas and chr lists in workdir ---
    curated_fasta = glob.glob(str(ctx.workdir / f"{ctx.tol_id}*.primary.curated.fa"))
    curated_chr_list = glob.glob(str(ctx.workdir / f"{ctx.tol_id}*.primary.chromosome.list.csv"))

    hap1_fa_list = [x for x in curated_fasta if "hap1" in x or ctx.hap1_prefix in x]
    hap2_fa_list = [x for x in curated_fasta if "hap2" in x or ctx.hap2_prefix in x]
    hap1_chr_list = [x for x in curated_chr_list if "hap1" in x or ctx.hap1_prefix in x]
    hap2_chr_list = [x for x in curated_chr_list if "hap2" in x or ctx.hap2_prefix in x]

    hap1_fa = (
        hap1_fa_list[0]
        if hap1_fa_list
        else str(ctx.workdir / f"{ctx.tol_id}.hap1.primary.curated.fa")
    )
    hap1_chr = (
        hap1_chr_list[0]
        if hap1_chr_list
        else str(ctx.workdir / f"{ctx.tol_id}.hap1.primary.chromosome.list.csv")
    )
    has_hap2 = bool(hap2_fa_list)
    hap2_fa = hap2_fa_list[0] if has_hap2 else ""
    hap2_chr = hap2_chr_list[0] if hap2_chr_list else ""
    hap2_argument = f"-hap2 {hap2_fa} -hap2_chr {hap2_chr}" if has_hap2 else ""

    run_dir = (
        ctx.tracker.start(
            "microchromosome_second_shot", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        if ctx.tracker
        else ctx.workdir / "microchromosome_second_shot" / "untracked"
    )

    # --- run second-shot script (splits assembly + HiC remapping on smalls) ---
    second_shot_cmd = (
        f"{_SECOND_SHOT_SCRIPT} "
        f"-hap1 {hap1_fa} -hap1_chr {hap1_chr} {hap2_argument} "
        f"-hic {ctx.hic_dir} -lr {ctx.long_reads_dir}/fasta "
        f"-o {run_dir}"
    )
    try:
        _run(second_shot_cmd, ctx.print_only, capture=False)
        if ctx.tracker:
            outputs = collect_outputs(
                _OUTPUT_SPECS, run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
            )
            ctx.tracker.finish(
                "microchromosome_second_shot", run_dir, "success", outputs=outputs or None
            )
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish("microchromosome_second_shot", run_dir, "failed")
        raise

    # --- print scp of micro pretext map to local for curation ---
    scp_pretext_micro = (
        f"scp {run_dir}/hic/pretext_maps_processed/*hr.pretext "
        f"~/curations/work/{ctx.tol_id}/second_shot_microchromosomes"
    )
    log.info("Scp micro pretext map to local for curation: %s", scp_pretext_micro)

    print_done(f"Microchromosome second-shot curation submitted. Output → {run_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("microchromosome-second-shot", cls=GritCommand)
@click.pass_context
def microchromosome_second_shot_cmd(ctx):
    """Run microchromosome second-shot curation (pre)."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_microchromosome_second_shot(curation_ctx)
    except Exception:
        log.exception("microchromosome-second-shot failed")
        raise SystemExit(1)
