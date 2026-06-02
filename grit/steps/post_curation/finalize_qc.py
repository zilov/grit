"""Step: copy curated outputs to final destinations and prompt for Jira QC move."""

from __future__ import annotations

import glob
import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run
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
        2. Copy curated FASTA files, chromosome lists, and haplotig files
           to ``{ctx.assembly_curated_dir}/``.
        3. Copy the remapped pretext map to the NFS curated pretext maps directory.
           Destination path uses a two-level prefix structure:
           ``{curated_pretext_maps_nfs}/{tol_id[0]}_*/{tol_id[1]}_*/``
        4. Run kmer_completeness.bash if no merquryk folder exists in
           ``{ctx.assembly_curated_dir}``.

    Prints:
        Step header, each copy command executed, reminder to update Jira.
    """
    log.info("finalize-qc | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Finalize for QC")

    curated_dir = ctx.assembly_curated_dir

    # 1. mkdir
    mkdir_cmd = f"mkdir -p {curated_dir}"
    _run(mkdir_cmd, ctx.print_only)
    log.info("Curated dir: %s", curated_dir)

    # 2. gather curated files
    curated_fa_pattern = str(ctx.workdir / f"{ctx.tol_id}*.curated.fa")
    chr_list_pattern = str(ctx.workdir / f"{ctx.tol_id}*.chromosome.list.csv")
    haplotig_pattern = str(ctx.workdir / f"{ctx.tol_id}*haplotigs*.fa")

    if ctx.print_only:
        for pattern in (curated_fa_pattern, chr_list_pattern, haplotig_pattern):
            _run(f"cp {pattern} {curated_dir}/", ctx.print_only)
    else:
        for pattern in (curated_fa_pattern, chr_list_pattern, haplotig_pattern):
            files = glob.glob(pattern)
            if files:
                cp_cmd = f"cp {' '.join(files)} {curated_dir}/"
                _run(cp_cmd, ctx.print_only)
            else:
                log.warning("No files matched: %s", pattern)

    # 3. copy remapped pretext map to NFS
    remapped_pattern = str(
        ctx.workdir
        / f"{ctx.tol_id}_curationpretext"
        / "pretext_maps_processed"
        / f"{ctx.tol_id}*normal.pretext"
    )

    tol_id = ctx.tol_id
    nfs_base = ctx.curated_pretext_maps_nfs

    if ctx.print_only:
        nfs_dest = f"{nfs_base}/{tol_id[0]}_*/{tol_id[1]}_*/"
        pretext_dest_name = f"{tol_id}.{ctx.release_version}.{ctx.hap1_prefix}.curated.pretext"
    else:
        first_level = glob.glob(str(nfs_base / f"{tol_id[0]}_*/"))
        if first_level:
            second_level = glob.glob(f"{first_level[0]}/{tol_id[1]}_*/")
            nfs_dest = second_level[0] if second_level else first_level[0]
        else:
            nfs_dest = str(nfs_base) + "/"
            log.warning("No NFS subdirectory found for %s* under %s", tol_id[0], nfs_base)

        pretext_dest_name = f"{tol_id}.{ctx.release_version}.{ctx.hap1_prefix}.curated.pretext"

    if ctx.print_only:
        _run(f"cp {remapped_pattern} {nfs_dest}{pretext_dest_name}", ctx.print_only)
    else:
        remapped_files = glob.glob(remapped_pattern)
        if remapped_files:
            cp_map_cmd = f"cp {remapped_files[0]} {nfs_dest}{pretext_dest_name}"
            _run(cp_map_cmd, ctx.print_only)
        else:
            log.warning(
                "Remapped pretext map not found at %s. Copy manually after HiC remapping completes.",
                remapped_pattern,
            )

    # 4. QV if merquryk not yet present
    qv_dir = curated_dir / "merquryk"
    if ctx.print_only or not qv_dir.exists():
        qv_cmd = f"cd {ctx.workdir} && kmer_completeness.bash {ctx.tol_id} {ctx.release_version}"
        console.print("\n[bold]Running QV analysis (merquryk not found):[/bold]")
        _run(qv_cmd, ctx.print_only)

    print_done("All files copied to curated directory")
    console.print(
        "\n[bold yellow]⚠  Remember to move the ticket to 'Curation QC' in Jira![/bold yellow]"
    )


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
