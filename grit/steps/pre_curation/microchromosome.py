"""Microchromosome second-shot curation steps."""

import glob
import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_microchromosome_curation(ctx: CurationContext) -> None:
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
           remapping on the merged small scaffolds::

               microchr_second_shot_curation.py \\
                   -hap1 {hap1_fa} -hap1_chr {hap1_chr} [-hap2 … -hap2_chr …] \\
                   -hic {ctx.hic_dir} -lr {ctx.long_reads_dir}/fasta \\
                   -o {workdir}/second_shot_microchromosomes

        3. Print scp command to copy the resulting micro pretext map to local
           for curation.

    Next step: curate the micro pretext map locally, then run
    ``microchromosome-post`` (``run_microchromosome_post_curation``).

    Prints:
        Step header, command, scp instructions.
    """
    log.info("microchromosome | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Microchromosome second-shot curation (pre)")

    micro_dir = ctx.workdir / "second_shot_microchromosomes"

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

    # --- run second-shot script (splits assembly + HiC remapping on smalls) ---
    second_shot_cmd = (
        f"/software/grit/projects/vgp_curation_scripts/birds_microchromosomes/"
        f"microchr_second_shot_curation.py "
        f"-hap1 {hap1_fa} -hap1_chr {hap1_chr} {hap2_argument} "
        f"-hic {ctx.hic_dir} -lr {ctx.long_reads_dir}/fasta "
        f"-o {micro_dir}"
    )
    _run(second_shot_cmd, ctx.print_only)

    # --- print scp of micro pretext map to local for curation ---
    scp_pretext_micro = (
        f"scp {micro_dir}/hic/pretext_maps_processed/*hr.pretext "
        f"~/curations/work/{ctx.tol_id}/second_shot_microchromosomes"
    )
    log.info("Scp micro pretext map to local for curation: %s", scp_pretext_micro)


def run_microchromosome_post_curation(ctx: CurationContext) -> None:
    """
    POST-curation step of the second-shot microchromosome workflow.

    Run after the micro pretext map has been curated locally and the resulting
    AGP file has been copied back to
    ``{workdir}/second_shot_microchromosomes/``.

    Steps:
        1. Locate the curated AGP file in ``second_shot_microchromosomes/``.
           Raises ``FileNotFoundError`` if no AGP is present (unless
           print_only).
        2. Print the scp command used to upload the AGP from local (for
           reference / print_only mode).
        3. Run ``pretext-to-asm`` on the merged small FASTA using the AGP::

               module load grit && pretext-to-asm \\
                   -a {merged_small_fa} -p {agp} -o {tol_id}_small.fa

        4. Combine the curated small hap1 (and hap2) FASTA with the large
           FASTA via ``combine_curated_micros.py``::

               combine_curated_micros.py \\
                   -l {large_hap1_fa} -s {small_curated_hap1_fa} \\
                   -o {final_dir}/{tol_id}_merged_curated.hap1.fa \\
                   --large-chr {large_hap1_chr} --small-chr {small_curated_hap1_chr} \\
                   --chr-output {final_dir}/{tol_id}_merged_curated.hap1.chr_list.csv

    Prints:
        Step header, each command, path to final merged FASTAs.
    """
    log.info("microchromosome-post | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Microchromosome second-shot curation (post)")

    micro_dir = ctx.workdir / "second_shot_microchromosomes"
    merged_small_fa = micro_dir / f"{ctx.tol_id}_curated_small_merged.fa"

    # --- locate AGP produced by local curation ---
    agp_matches = glob.glob(str(micro_dir / "*.agp*"))
    if ctx.print_only:
        agp = str(micro_dir / f"{ctx.tol_id}_micro.agp")
    elif not agp_matches:
        raise FileNotFoundError(
            f"No AGP file found in {micro_dir}.\n"
            "Copy the curated AGP from local first:\n"
            f"  scp ~/curations/work/{ctx.tol_id}/second_shot_microchromosomes/*agp* "
            f"{ctx.farm_host}:{micro_dir}/"
        )
    else:
        agp = sorted(agp_matches)[-1]

    # --- scp reminder (shown for reference / print_only) ---
    scp_micro_agp = (
        f"scp ~/curations/work/{ctx.tol_id}/second_shot_microchromosomes/*agp* "
        f"{ctx.farm_host}:{micro_dir}/"
    )
    log.info("AGP should have been uploaded with: %s", scp_micro_agp)
    log.info("AGP file: %s", agp)

    # --- run pretext-to-asm on small chromosomes ---
    small_out_fa = micro_dir / f"{ctx.tol_id}_small.fa"
    small_pretext_to_asm = (
        f"module load grit && pretext-to-asm -a {merged_small_fa} -p {agp} -o {small_out_fa}"
    )
    _run(small_pretext_to_asm, ctx.print_only)

    small_curated_hap1_fa = micro_dir / f"{ctx.tol_id}_small.hap1.fa"
    small_curated_hap1_chr = micro_dir / f"{ctx.tol_id}_small.hap1.chromosome.list.csv"

    # --- locate large fastas/chr lists produced by the pre step ---
    large_hap1_fa_matches = glob.glob(
        str(micro_dir / f"{ctx.tol_id}*hap1*.primary.curated.large.fa")
    )
    large_hap1_fa = (
        large_hap1_fa_matches[0]
        if large_hap1_fa_matches
        else str(micro_dir / f"{ctx.tol_id}.hap1.primary.curated.large.fa")
    )
    large_hap1_chr_matches = glob.glob(str(micro_dir / f"{ctx.tol_id}*hap1*.large.chr_list.csv"))
    large_hap1_chr = (
        large_hap1_chr_matches[0]
        if large_hap1_chr_matches
        else str(micro_dir / f"{ctx.tol_id}.hap1.large.chr_list.csv")
    )

    has_hap2_large = bool(
        glob.glob(str(micro_dir / f"{ctx.tol_id}*hap2*.primary.curated.large.fa"))
    )
    if ctx.print_only:
        has_hap2_large = ctx.hap2_prefix in ("hap2", "maternal")

    # --- combine large + small via combine_curated_micros.py ---
    final_dir = micro_dir / "final_curated"
    merged_curated_hap1_fa = final_dir / f"{ctx.tol_id}_merged_curated.hap1.fa"
    merged_curated_hap1_chr = final_dir / f"{ctx.tol_id}_merged_curated.hap1.chr_list.csv"

    merge_hap1_cmd = (
        f"~/gitlab/vgp_curation_scripts/birds_microchromosomes/combine_curated_micros.py "
        f"-l {large_hap1_fa} -s {small_curated_hap1_fa} -o {merged_curated_hap1_fa} "
        f"--large-chr {large_hap1_chr} --small-chr {small_curated_hap1_chr} "
        f"--chr-output {merged_curated_hap1_chr}"
    )
    _run(merge_hap1_cmd, ctx.print_only)

    if has_hap2_large:
        large_hap2_fa_matches = glob.glob(
            str(micro_dir / f"{ctx.tol_id}*hap2*.primary.curated.large.fa")
        )
        large_hap2_fa = (
            large_hap2_fa_matches[0]
            if large_hap2_fa_matches
            else str(micro_dir / f"{ctx.tol_id}.hap2.primary.curated.large.fa")
        )
        large_hap2_chr_matches = glob.glob(
            str(micro_dir / f"{ctx.tol_id}*hap2*.large.chr_list.csv")
        )
        large_hap2_chr = (
            large_hap2_chr_matches[0]
            if large_hap2_chr_matches
            else str(micro_dir / f"{ctx.tol_id}.hap2.large.chr_list.csv")
        )
        small_curated_hap2_fa = micro_dir / f"{ctx.tol_id}_small.hap2.fa"
        small_curated_hap2_chr = micro_dir / f"{ctx.tol_id}_small.hap2.chromosome.list.csv"
        merged_curated_hap2_fa = final_dir / f"{ctx.tol_id}_merged_curated.hap2.fa"
        merged_curated_hap2_chr = final_dir / f"{ctx.tol_id}_merged_curated.hap2.chr_list.csv"
        merge_hap2_cmd = (
            f"~/gitlab/vgp_curation_scripts/birds_microchromosomes/combine_curated_micros.py "
            f"-l {large_hap2_fa} -s {small_curated_hap2_fa} -o {merged_curated_hap2_fa} "
            f"--large-chr {large_hap2_chr} --small-chr {small_curated_hap2_chr} "
            f"--chr-output {merged_curated_hap2_chr}"
        )
        _run(merge_hap2_cmd, ctx.print_only)

    print_done(f"Microchromosome post-curation complete. Final merged FASTAs in: {final_dir}")


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("microchromosome", cls=GritCommand)
@click.pass_context
def microchromosome_cmd(ctx):
    """Run microchromosome second-shot curation (pre)."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_microchromosome_curation(curation_ctx)
    except Exception:
        log.exception("microchromosome failed")
        raise SystemExit(1)


@click.command("microchromosome-post", cls=GritCommand)
@click.pass_context
def microchromosome_post_cmd(ctx):
    """Run microchromosome second-shot curation (post)."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_microchromosome_post_curation(curation_ctx)
    except Exception:
        log.exception("microchromosome-post failed")
        raise SystemExit(1)
