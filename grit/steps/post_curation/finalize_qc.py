"""Step: copy curated outputs to final destinations and prompt for Jira QC move."""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, find_canonical_chr_list, find_canonical_fa, find_latest_dir
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def finalize_for_qc(ctx: CurationContext) -> None:
    """
    Copies all curated outputs to their final destinations and prompts
    the curator to move the ticket to Curation QC.

    Notebook source: ``pre_and_post_curation()`` — ``final_commands`` section.

    Steps:
        1. Create curated assembly directory: ``mkdir {ctx.assembly_curated_dir}``
        2. Copy canonical assembly FAs and chromosome lists per haplotype
           (rename_and_orient output if available, otherwise pretext_to_asm),
           plus haplotig FAs from pretext_to_asm, to ``{ctx.assembly_curated_dir}/``.
        3. Copy the remapped pretext map from the hic_remapping run_dir to NFS.
           Destination path uses a two-level prefix structure:
           ``{curated_pretext_maps_nfs}/{tol_id[0]}_*/{tol_id[1]}_*/``
        4. Run kmer_completeness.bash if no merquryk folder exists in
           ``{ctx.assembly_curated_dir}``.
        5. Mark ticket as done in the global registry.

    Prints:
        Step header, each copy command executed, reminder to update Jira.
    """
    log.info("finalize-qc | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Finalize for QC")

    run_dir = ctx.tracker.start("finalize_qc", ctx.ticket_id, ctx.tol_id) if ctx.tracker else None

    # Resolve run dirs for curated files
    pta_dir = find_latest_dir(ctx, "pretext_to_asm")
    hic_dir = find_latest_dir(ctx, "hic_remapping")

    curated_dir = ctx.assembly_curated_dir

    # 1. mkdir
    mkdir_cmd = f"mkdir -p {curated_dir}"
    _run(mkdir_cmd, ctx.print_only)
    log.info("Curated dir: %s", curated_dir)

    # 2. primary assembly FAs — prefer rename_and_orient output (canonical), fallback to pretext_to_asm
    for hap_prefix in (ctx.hap1_prefix, ctx.hap2_prefix):
        try:
            fa = find_canonical_fa(ctx, hap_prefix)
            _run(f"cp {fa} {curated_dir}/", ctx.print_only)
        except FileNotFoundError as e:
            log.warning(str(e))

    # haplotig FAs — always from pretext_to_asm (rename_and_orient doesn't process these)
    haplotig_files = glob.glob(str(pta_dir / f"{ctx.tol_id}*all_haplotigs*.curated.fa"))
    if haplotig_files:
        _run(f"cp {' '.join(haplotig_files)} {curated_dir}/", ctx.print_only)

    # chromosome lists — prefer rename_and_orient, fallback to pretext_to_asm per hap
    for hap_prefix in (ctx.hap1_prefix, ctx.hap2_prefix):
        try:
            csv = find_canonical_chr_list(ctx, hap_prefix)
            _run(f"cp {csv} {curated_dir}/", ctx.print_only)
        except FileNotFoundError as e:
            log.warning(str(e))

    # 3. copy remapped pretext map from hic_remapping run_dir to NFS
    remapped_pattern = str(hic_dir / "pretext_maps_processed" / f"{ctx.tol_id}*normal.pretext")

    tol_id = ctx.tol_id
    nfs_base = ctx.curated_pretext_maps_nfs

    pretext_dest_name = f"{tol_id}.{ctx.release_version}.{ctx.hap1_prefix}.curated.pretext"

    first_level = glob.glob(str(nfs_base / f"{tol_id[0]}_*/"))
    if first_level:
        second_level = glob.glob(str(Path(first_level[0]) / f"{tol_id[1]}_*/"))
        nfs_dest = Path(second_level[0] if second_level else first_level[0])
    else:
        nfs_dest = nfs_base / f"{tol_id[0]}_?" / f"{tol_id[1]}_?"
        if not ctx.print_only:
            log.warning("No NFS subdirectory found for %s* under %s", tol_id[0], nfs_base)

    remapped_files = glob.glob(remapped_pattern)
    if remapped_files:
        _run(f"cp {remapped_files[0]} {nfs_dest / pretext_dest_name}", ctx.print_only)
    else:
        if not ctx.print_only:
            log.warning(
                "Remapped pretext map not found at %s. Copy manually after HiC remapping completes.",
                remapped_pattern,
            )
        else:
            _run(f"cp {remapped_pattern} {nfs_dest / pretext_dest_name}", ctx.print_only)

    # 4. QV if merquryk not yet present
    qv_dir = curated_dir / "merquryk"
    if ctx.print_only or not qv_dir.exists():
        qv_cmd = f"cd {ctx.workdir} && kmer_completeness.bash {ctx.tol_id} {ctx.release_version}"
        console.print("\n[bold]Running QV analysis (merquryk not found):[/bold]")
        _run(qv_cmd, ctx.print_only)

    print_done("All files copied to curated directory")
    console.print(
        "\n[bold yellow]⚠  Please don't forget about Submission Text and attaching latest savestate to the ticket, curation summary:[/bold yellow]"
    )

    if ctx.tracker and run_dir:
        ctx.tracker.finish("finalize_qc", run_dir, "success")

    from grit.utils.output import print_curation_results, print_tip
    print_curation_results(ctx.tracker, ctx.workdir, ctx.tol_id, curated_dir=ctx.assembly_curated_dir)
    print_tip("Submission notes: https://gist.github.com/zilov/93b1e6c68a6e2553b7c12770d6a0a3ef")


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("finalize-qc", cls=GritCommand)
@click.pass_context
def finalize_qc_cmd(ctx):
    """Finalize curation and prepare for QC."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        finalize_for_qc(curation_ctx)
    except Exception:
        log.exception("finalize-qc failed")
        raise SystemExit(1)
