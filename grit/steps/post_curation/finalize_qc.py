"""Step: copy curated outputs to final destinations and prompt for Jira QC move."""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _run,
    find_canonical_chr_list,
    find_canonical_fa,
    find_canonical_haplotigs,
    find_latest_dir,
    pta_curated_fa_exists,
)
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


def _raise_if_yaml_pta_mismatch(ctx: CurationContext) -> None:
    """
    Raises ValueError when the YAML's declared assembly type doesn't match what
    pretext-to-asm actually produced:

    - YAML declares a single-hap assembly (primary/alternate, paternal/maternal)
      but the curator split into two haplotypes (hap1/hap2) in PretextView —
      pretext-to-asm then names its output files with the literal "hap1"/"hap2"
      tokens instead of the YAML's prefixes, which breaks the single-hap copy
      logic below (only ``ctx.hap1_prefix`` is processed, so the second
      haplotype's assembly is silently dropped).
    - YAML declares a dual-hap assembly (hap1/hap2) but the curator didn't
      split haplotypes, so pretext-to-asm produced a single unprefixed
      ("primary"-style) curated FASTA — ``find_canonical_fa`` would then
      silently resolve both haplotypes to that same file.
    """
    pta_dir = find_latest_dir(ctx, "pretext_to_asm")
    haplotig_keywords = ("all_haplotigs", "additional_haplotigs", "haplotigs")
    has_hap1 = pta_curated_fa_exists(pta_dir, ctx.tol_id, "hap1")
    has_hap2 = pta_curated_fa_exists(pta_dir, ctx.tol_id, "hap2")

    yaml_hint = f" ({ctx.yaml_path})" if ctx.yaml_path else ""

    if ctx.hap1_prefix in ("hap1", "hap2"):
        if has_hap1 or has_hap2:
            return  # YAML dual-hap, pretext-to-asm output dual-hap — matches

        unprefixed = [
            f
            for f in glob.glob(str(pta_dir / f"{ctx.tol_id}.*.primary.curated.fa"))
            if not any(kw in f for kw in haplotig_keywords)
            and "hap1" not in Path(f).name
            and "hap2" not in Path(f).name
        ]
        if unprefixed:
            raise ValueError(
                "YAML and pretext-to-asm assembly types don't match: YAML declares "
                "hap1/hap2, but pretext-to-asm produced a single unprefixed "
                f"(primary/alternate-style) output. Update the YAML{yaml_hint} to "
                "primary/alternate to fix this."
            )
        return  # neither dual-hap nor unprefixed output found — let downstream steps report it

    if has_hap1 and has_hap2:
        raise ValueError(
            "YAML and pretext-to-asm assembly types don't match: YAML declares "
            "primary/alternate, but pretext-to-asm produced hap1/hap2 output. "
            f"Update the YAML{yaml_hint} to hap1/hap2 to fix this."
        )


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

    if not ctx.print_only:
        _raise_if_yaml_pta_mismatch(ctx)

    run_dir = (
        ctx.tracker.start("finalize_qc", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else None
    )

    dest_dir = curated_dir or ctx.assembly_curated_dir

    # primary/alternate (and paternal/maternal) assemblies use version-only dest naming
    # and only copy hap1 files — downstream scripts expect {tol_id}.{version}.primary.curated.fa
    # hap1/hap2 assemblies copy both haplotypes with {tol_id}.{hap}.{version}.primary.curated.fa
    _IS_SINGLE_HAP = ctx.hap1_prefix in ("primary", "paternal")

    def _dest_name(hap_prefix: str, suffix: str) -> str:
        if _IS_SINGLE_HAP:
            return f"{ctx.tol_id}.{ctx.release_version}.{suffix}"
        return f"{ctx.tol_id}.{hap_prefix}.{ctx.release_version}.{suffix}"

    # 1. mkdir
    _run(f"mkdir -p {dest_dir}", ctx.print_only)
    log.info("Curated dir: %s", dest_dir)

    # Which haplotypes to process: primary/alternate → hap1 only; hap1/hap2 → both
    haps_to_process = [ctx.hap1_prefix] if _IS_SINGLE_HAP else [ctx.hap1_prefix, ctx.hap2_prefix]

    # 2a. primary assembly FAs
    assembly_overrides = {ctx.hap1_prefix: hap1_assembly, ctx.hap2_prefix: hap2_assembly}
    for hap_prefix in haps_to_process:
        src = assembly_overrides[hap_prefix]
        if src is None:
            try:
                src = find_canonical_fa(ctx, hap_prefix)
            except FileNotFoundError as e:
                log.warning(str(e))
                continue
        _run(f"cp {src} {dest_dir / _dest_name(hap_prefix, 'primary.curated.fa')}", ctx.print_only)

    # 2b. haplotig FAs — override, find, or touch empty placeholder
    haplotig_overrides = {ctx.hap1_prefix: hap1_haplotigs, ctx.hap2_prefix: hap2_haplotigs}
    for hap_prefix in haps_to_process:
        src = haplotig_overrides[hap_prefix]
        if src is None:
            try:
                src = find_canonical_haplotigs(ctx, hap_prefix)
            except FileNotFoundError:
                src = None
        # GritJiraIssue.get_curated_file_name_for_type() expects "all_haplotigs" only
        # when the curated haplotigs were actually combined, otherwise it looks for
        # "additional_haplotigs" — mirror whatever pretext-to-asm's real output on
        # disk is named rather than trusting the YAML's combine_for_curation flag,
        # which (like assembly type) can disagree with what the curator actually did.
        if src and "additional_haplotigs" in src.name:
            haplotig_suffix = "additional_haplotigs.curated.fa"
        elif src and "all_haplotigs" in src.name:
            haplotig_suffix = "all_haplotigs.curated.fa"
        else:
            haplotig_suffix = (
                "all_haplotigs.curated.fa"
                if ctx.combine_for_curation
                else "additional_haplotigs.curated.fa"
            )
        dest = dest_dir / _dest_name(hap_prefix, haplotig_suffix)
        if src:
            _run(f"cp {src} {dest}", ctx.print_only)
        else:
            _run(f"touch {dest}", ctx.print_only)

    # 2c. chromosome lists
    chr_list_overrides = {ctx.hap1_prefix: hap1_chr_list, ctx.hap2_prefix: hap2_chr_list}
    for hap_prefix in haps_to_process:
        src = chr_list_overrides[hap_prefix]
        if src is None:
            try:
                src = find_canonical_chr_list(ctx, hap_prefix)
            except FileNotFoundError as e:
                log.warning(str(e))
                continue
        _run(
            f"cp {src} {dest_dir / _dest_name(hap_prefix, 'primary.chromosome.list.csv')}",
            ctx.print_only,
        )

    # 3. copy remapped pretext maps to NFS
    tol_id = ctx.tol_id
    nfs_dest = _resolve_nfs_dest(ctx.curated_pretext_maps_nfs, tol_id, ctx.print_only)

    _copy_map(ctx, "hic_remapping", ctx.hap1_prefix, nfs_dest, hap1_map)

    # hap2 map: only for dual-hap assemblies
    hap2_hic_dir = find_latest_dir(ctx, "hic_remapping_hap2")
    hap2_hic_has_output = (
        (hap2_hic_dir != ctx.workdir and hap2_hic_dir.exists() and any(hap2_hic_dir.iterdir()))
        if not ctx.print_only
        else False
    )
    if hap2_map or hap2_hic_has_output:
        _copy_map(ctx, "hic_remapping_hap2", ctx.hap2_prefix, nfs_dest, hap2_map)

    # 4. QV if merquryk not yet present
    qv_dir = dest_dir / "merquryk"
    if not qv_dir.exists():
        from grit.steps.post_curation.qv import run_qv

        run_qv(ctx)

    if ctx.print_only:
        console.print(
            "\n[yellow]print-only: files not copied — commands above show what would run[/yellow]"
        )
    else:
        print_done("All files copied to curated directory")
    console.print(
        "\n[bold yellow]⚠  Please don't forget about Submission Text and attaching "
        "latest savestate to the ticket, curation summary:[/bold yellow]"
    )

    if ctx.tracker and run_dir:
        ctx.tracker.finish(
            "finalize_qc", run_dir, "success", outputs={"curated_dir": str(dest_dir)}
        )

    from grit.utils.output import print_curation_results, print_tip

    print_curation_results(ctx.tracker, ctx.workdir, ctx.tol_id, curated_dir=dest_dir)
    print_tip("Submission notes: https://gist.github.com/zilov/93b1e6c68a6e2553b7c12770d6a0a3ef")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("finalize-qc", cls=GritCommand)
@click.option(
    "--hap1-assembly",
    type=click.Path(),
    default=None,
    help="Override canonical hap1 assembly FASTA.",
)
@click.option(
    "--hap2-assembly",
    type=click.Path(),
    default=None,
    help="Override canonical hap2 assembly FASTA.",
)
@click.option(
    "--hap1-chr-list", type=click.Path(), default=None, help="Override hap1 chromosome list CSV."
)
@click.option(
    "--hap2-chr-list", type=click.Path(), default=None, help="Override hap2 chromosome list CSV."
)
@click.option(
    "--hap1-haplotigs", type=click.Path(), default=None, help="Override hap1 haplotig FASTA."
)
@click.option(
    "--hap2-haplotigs", type=click.Path(), default=None, help="Override hap2 haplotig FASTA."
)
@click.option(
    "--hap1-map", type=click.Path(), default=None, help="Override hap1 remapped pretext map path."
)
@click.option(
    "--hap2-map",
    type=click.Path(),
    default=None,
    help="Override hap2 remapped pretext map path (also triggers hap2 map copy).",
)
@click.option(
    "--curated-dir",
    type=click.Path(),
    default=None,
    help="Override destination curated assembly directory.",
)
@click.pass_context
def finalize_qc_cmd(
    ctx,
    hap1_assembly,
    hap2_assembly,
    hap1_chr_list,
    hap2_chr_list,
    hap1_haplotigs,
    hap2_haplotigs,
    hap1_map,
    hap2_map,
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
