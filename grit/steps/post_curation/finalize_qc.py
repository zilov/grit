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
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_nfs_dest(nfs_base: Path, tol_id: str, print_only: bool) -> Path:
    """Resolve the two-level NFS destination directory for pretext maps."""
    first_level = glob.glob(str(nfs_base / f"{tol_id[0]}_*/"))
    if first_level:
        second_level = glob.glob(str(Path(first_level[0]) / f"{tol_id[1]}_*/"))
        return Path(second_level[0] if second_level else first_level[0])
    if not print_only:
        log.warning("No NFS subdirectory found for %s* under %s", tol_id[0], nfs_base)
    return nfs_base / f"{tol_id[0]}_?" / f"{tol_id[1]}_?"


def _copy_map(
    ctx: CurationContext,
    step_name: str,
    hap_prefix: str,
    nfs_dest: Path,
    override: Path | None,
) -> None:
    """Resolve and copy one remapped pretext map to NFS."""
    tol_id = ctx.tol_id
    dest_name = f"{tol_id}.{ctx.release_version}.{hap_prefix}.curated.pretext"

    if override:
        _run(f"cp {override} {nfs_dest / dest_name}", ctx.print_only)
        return

    hic_dir = find_latest_dir(ctx, step_name)
    pattern = str(hic_dir / "pretext_maps_processed" / f"{tol_id}*normal.pretext")
    matches = glob.glob(pattern)
    if matches:
        _run(f"cp {matches[0]} {nfs_dest / dest_name}", ctx.print_only)
    elif ctx.print_only:
        _run(f"cp {pattern} {nfs_dest / dest_name}", ctx.print_only)
    else:
        log.warning(
            "Remapped pretext map not found at %s. Copy manually after HiC remapping completes.",
            pattern,
        )


# ---------------------------------------------------------------------------
# Public step function
# ---------------------------------------------------------------------------


def finalize_for_qc(
    ctx: CurationContext,
    *,
    hap1_assembly: Path | None = None,
    hap2_assembly: Path | None = None,
    hap1_chr_list: Path | None = None,
    hap2_chr_list: Path | None = None,
    hap1_haplotigs: Path | None = None,
    hap2_haplotigs: Path | None = None,
    hap1_map: Path | None = None,
    hap2_map: Path | None = None,
    curated_dir: Path | None = None,
) -> None:
    """
    Copies all curated outputs to their final destinations and prompts
    the curator to move the ticket to Curation QC.

    Notebook source: ``pre_and_post_curation()`` — ``final_commands`` section.

    Steps:
        1. Create curated assembly directory: ``mkdir {ctx.assembly_curated_dir}``
        2. Copy canonical assembly FAs and chromosome lists per haplotype
           (rename_and_orient output if available, otherwise pretext_to_asm),
           plus haplotig FAs from pretext_to_asm, to ``{ctx.assembly_curated_dir}/``.
        3. Copy remapped pretext maps (hap1 from hic_remapping, hap2 from
           hic_remapping_hap2 if present) to NFS.
           Destination path uses a two-level prefix structure:
           ``{curated_pretext_maps_nfs}/{tol_id[0]}_*/{tol_id[1]}_*/``
        4. Run kmer_completeness.bash if no merquryk folder exists in
           ``{ctx.assembly_curated_dir}``.

    All file arguments (``hap1_assembly``, ``hap2_assembly``, etc.) override
    the automatically resolved paths. ``curated_dir`` overrides
    ``ctx.assembly_curated_dir``.
    """
    log.info("finalize-qc | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Finalize for QC")

    run_dir = ctx.tracker.start("finalize_qc", ctx.ticket_id, ctx.tol_id) if ctx.tracker else None

    pta_dir = find_latest_dir(ctx, "pretext_to_asm")
    dest_dir = curated_dir or ctx.assembly_curated_dir

    # 1. mkdir
    _run(f"mkdir -p {dest_dir}", ctx.print_only)
    log.info("Curated dir: %s", dest_dir)

    # 2a. primary assembly FAs per hap — override or find_canonical_fa
    # Always copy to canonical curated name: {tol_id}.{hap_prefix}.{version}.primary.curated.fa
    assembly_overrides = {ctx.hap1_prefix: hap1_assembly, ctx.hap2_prefix: hap2_assembly}
    for hap_prefix, override in assembly_overrides.items():
        dest_name = f"{ctx.tol_id}.{hap_prefix}.{ctx.release_version}.primary.curated.fa"
        src = override
        if src is None:
            try:
                src = find_canonical_fa(ctx, hap_prefix)
            except FileNotFoundError as e:
                log.warning(str(e))
                continue
        _run(f"cp {src} {dest_dir / dest_name}", ctx.print_only)

    # 2b. haplotig FAs per hap — override, glob from pretext_to_asm, or create empty placeholder
    haplotig_overrides = {ctx.hap1_prefix: hap1_haplotigs, ctx.hap2_prefix: hap2_haplotigs}
    for hap_prefix, override in haplotig_overrides.items():
        if override:
            _run(f"cp {override} {dest_dir}/", ctx.print_only)
        else:
            files = glob.glob(str(pta_dir / f"{ctx.tol_id}*{hap_prefix}*all_haplotigs*.curated.fa"))
            if files:
                _run(f"cp {' '.join(files)} {dest_dir}/", ctx.print_only)
            else:
                empty_name = f"{ctx.tol_id}.{hap_prefix}.{ctx.release_version}.all_haplotigs.curated.fa"
                _run(f"touch {dest_dir / empty_name}", ctx.print_only)

    # 2c. chromosome lists per hap — override or find_canonical_chr_list
    # Always copy to canonical curated name: {tol_id}.{hap_prefix}.{version}.chromosome.list.csv
    chr_list_overrides = {ctx.hap1_prefix: hap1_chr_list, ctx.hap2_prefix: hap2_chr_list}
    for hap_prefix, override in chr_list_overrides.items():
        dest_name = f"{ctx.tol_id}.{hap_prefix}.{ctx.release_version}.primary.chromosome.list.csv"
        src = override
        if src is None:
            try:
                src = find_canonical_chr_list(ctx, hap_prefix)
            except FileNotFoundError as e:
                log.warning(str(e))
                continue
        _run(f"cp {src} {dest_dir / dest_name}", ctx.print_only)

    # 3. copy remapped pretext maps to NFS
    tol_id = ctx.tol_id
    nfs_dest = _resolve_nfs_dest(ctx.curated_pretext_maps_nfs, tol_id, ctx.print_only)

    _copy_map(ctx, "hic_remapping", ctx.hap1_prefix, nfs_dest, hap1_map)

    # hap2 map: copy if an override is given or if a hic_remapping_hap2 run dir exists
    hap2_hic_dir = find_latest_dir(ctx, "hic_remapping_hap2")
    hap2_hic_has_output = (
        hap2_hic_dir != ctx.workdir
        and hap2_hic_dir.exists()
        and any(hap2_hic_dir.iterdir())
    ) if not ctx.print_only else False
    if hap2_map or hap2_hic_has_output:
        _copy_map(ctx, "hic_remapping_hap2", ctx.hap2_prefix, nfs_dest, hap2_map)

    # 4. QV if merquryk not yet present
    qv_dir = dest_dir / "merquryk"
    if not qv_dir.exists():
        qv_cmd = f"cd {ctx.workdir} && kmer_completeness.bash {ctx.tol_id} {ctx.release_version}"
        console.print("\n[bold]Running QV analysis (merquryk not found):[/bold]")
        _run(qv_cmd, ctx.print_only)

    if ctx.print_only:
        console.print("\n[yellow]print-only: files not copied — commands above show what would run[/yellow]")
    else:
        print_done("All files copied to curated directory")
    console.print(
        "\n[bold yellow]⚠  Please don't forget about Submission Text and attaching latest savestate to the ticket, curation summary:[/bold yellow]"
    )

    if ctx.tracker and run_dir:
        ctx.tracker.finish("finalize_qc", run_dir, "success")

    from grit.utils.output import print_curation_results, print_tip
    print_curation_results(ctx.tracker, ctx.workdir, ctx.tol_id, curated_dir=dest_dir)
    print_tip("Submission notes: https://gist.github.com/zilov/93b1e6c68a6e2553b7c12770d6a0a3ef")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("finalize-qc", cls=GritCommand)
@click.option("--hap1-assembly", type=click.Path(), default=None,
              help="Override canonical hap1 assembly FASTA.")
@click.option("--hap2-assembly", type=click.Path(), default=None,
              help="Override canonical hap2 assembly FASTA.")
@click.option("--hap1-chr-list", type=click.Path(), default=None,
              help="Override hap1 chromosome list CSV.")
@click.option("--hap2-chr-list", type=click.Path(), default=None,
              help="Override hap2 chromosome list CSV.")
@click.option("--hap1-haplotigs", type=click.Path(), default=None,
              help="Override hap1 haplotig FASTA.")
@click.option("--hap2-haplotigs", type=click.Path(), default=None,
              help="Override hap2 haplotig FASTA.")
@click.option("--hap1-map", type=click.Path(), default=None,
              help="Override hap1 remapped pretext map path.")
@click.option("--hap2-map", type=click.Path(), default=None,
              help="Override hap2 remapped pretext map path (also triggers hap2 map copy).")
@click.option("--curated-dir", type=click.Path(), default=None,
              help="Override destination curated assembly directory.")
@click.pass_context
def finalize_qc_cmd(
    ctx,
    hap1_assembly, hap2_assembly,
    hap1_chr_list, hap2_chr_list,
    hap1_haplotigs, hap2_haplotigs,
    hap1_map, hap2_map,
    curated_dir,
):
    """Finalize curation and prepare for QC."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        finalize_for_qc(
            curation_ctx,
            hap1_assembly=Path(hap1_assembly) if hap1_assembly else None,
            hap2_assembly=Path(hap2_assembly) if hap2_assembly else None,
            hap1_chr_list=Path(hap1_chr_list) if hap1_chr_list else None,
            hap2_chr_list=Path(hap2_chr_list) if hap2_chr_list else None,
            hap1_haplotigs=Path(hap1_haplotigs) if hap1_haplotigs else None,
            hap2_haplotigs=Path(hap2_haplotigs) if hap2_haplotigs else None,
            hap1_map=Path(hap1_map) if hap1_map else None,
            hap2_map=Path(hap2_map) if hap2_map else None,
            curated_dir=Path(curated_dir) if curated_dir else None,
        )
    except Exception:
        log.exception("finalize-qc failed")
        raise SystemExit(1)
