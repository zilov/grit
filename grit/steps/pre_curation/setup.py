"""Pre-curation steps: workspace setup before manual curation."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _pick_highest_version, _run, _sort_by_mtime
from grit.utils.output import (
    console,
    print_done,
    print_step_header,
    print_tip,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def setup_curation(ctx: CurationContext) -> None:
    """
    Creates the working directory and copies original.fa from the draft assembly.

    Notebook source: ``pre_and_post_curation()`` — pre-curation section.

    Steps:
        1. ``mkdir -p {ctx.workdir}``
        2. Decompress and concatenate hap1 + hap2 decontaminated FASTA::

               zcat {decont_hap1} [{decont_hap2}] > {ctx.workdir}/original.fa

           Decontaminated files are found via glob in ``ctx.assembly_draft_dir``:
           ``{assembly_draft_dir}/{tol_id}*{hap1_prefix}.decontaminated.fa*``
           (``assembly_draft_dir`` already points to the versioned subdir)
           If two files exist, the newest (by mtime) is chosen.

    Args:
        ctx: CurationContext for the ticket.

    Prints:
        Command string executed and the path of the resulting original.fa.
    """
    log.info("setup-curation | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Setup curation")

    # 1. Create workdir
    mkdir_cmd = f"mkdir -p {ctx.workdir}"
    _run(mkdir_cmd, ctx.print_only)
    log.info("Workdir: %s", ctx.workdir)

    original_fa = ctx.workdir / "original.fa"

    if not ctx.print_only and original_fa.exists():
        log.info("original.fa already exists, skipping copy: %s", original_fa)
        return

    # Glob for decontaminated hap1 FASTA
    # assembly_draft_dir already points to the versioned subdir,
    # e.g. .../assembly/draft/uoEpiScra1.20241115
    hap1_pattern = f"{ctx.assembly_draft_dir}/{ctx.tol_id}*{ctx.hap1_prefix}.decontaminated.fa*"
    hap2_pattern = f"{ctx.assembly_draft_dir}/{ctx.tol_id}*{ctx.hap2_prefix}.decontaminated.fa*"

    if ctx.print_only:
        # In print-only mode show expected paths without checking the filesystem
        decont_hap1 = hap1_pattern
        decont_hap2 = hap2_pattern
        log.info("hap1 FASTA (pattern): %s", decont_hap1)
        log.info("hap2 FASTA (pattern): %s", decont_hap2)
    else:
        hap1_files = glob.glob(hap1_pattern)
        if not hap1_files:
            hap1_files = glob.glob(f"{ctx.assembly_draft_dir}/{ctx.tol_id}*.decontaminated.fa*")
        if not hap1_files:
            raise FileNotFoundError(f"No decontaminated hap1 FASTA found at: {hap1_pattern}")
        decont_hap1 = _sort_by_mtime(hap1_files)[0]

        hap2_files = glob.glob(hap2_pattern)
        if hap2_files:
            decont_hap2 = _sort_by_mtime(hap2_files)[0]
        else:
            decont_hap2 = ""
            log.warning("Alternate haplotype FASTA not found — creating single-hap original.fa")

    zcat_cmd = f"zcat {decont_hap1} {decont_hap2} > {original_fa}"
    _run(zcat_cmd, ctx.print_only)

    if not ctx.print_only:
        print_done(f"original.fa → {original_fa}")


def _find_pretext_maps(ctx: CurationContext) -> tuple[Path, Path]:
    """
    Resolves pretext maps for *hr* and *normal* (required) and *ultra* (optional)
    in ``ctx.pretext_maps_nfs``.

    Returns:
        List of resolved Path objects: [hr_src, normal_src] plus ultra_src if found.

    Raises:
        FileNotFoundError: if no match is found for hr or normal.
    """
    hr_pattern = str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*hr.pretext")
    normal_pattern = str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*normal.pretext")
    ultra_pattern = str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*ultra.pretext")

    hr_files = glob.glob(hr_pattern)
    normal_files = glob.glob(normal_pattern)
    ultra_files = glob.glob(ultra_pattern)

    if not hr_files:
        raise FileNotFoundError(
            f"No hi-res pretext map found for {ctx.tol_id} in {ctx.pretext_maps_nfs}"
        )
    if not normal_files:
        raise FileNotFoundError(
            f"No normal pretext map found for {ctx.tol_id} in {ctx.pretext_maps_nfs}"
        )

    hr_src = Path(_pick_highest_version(hr_files))
    normal_src = Path(_pick_highest_version(normal_files))

    log.info("HR map: %s", hr_src.name)
    log.info("Normal map: %s", normal_src.name)

    sources = [hr_src, normal_src]
    if ultra_files:
        ultra_src = Path(_pick_highest_version(ultra_files))
        log.info("Ultra map: %s", ultra_src.name)
        sources.append(ultra_src)

    return sources


def copy_pretext_maps(ctx: CurationContext) -> None:
    """
    Copies pretext maps from NFS to workdir.

    Steps:
        1. Resolve maps via :func:`_find_pretext_maps`.
        2. ``cp {hr_pretext} {ctx.workdir}/``
           ``cp {normal_pretext} {ctx.workdir}/``
    """
    log.info("copy-pretext-maps | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Copy pretext maps")

    if ctx.print_only:
        try:
            src_paths = [str(s) for s in _find_pretext_maps(ctx)]
        except FileNotFoundError:
            log.warning("Pretext maps not found on NFS — showing glob patterns instead")
            src_paths = [
                str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*{suffix}.pretext")
                for suffix in ("hr", "normal", "ultra")
            ]
        for src in src_paths:
            console.print(f"\n[yellow]Command:[/yellow] [green]cp {src} {ctx.workdir}/[/green]")
        return

    for src in _find_pretext_maps(ctx):
        cp_cmd = f"cp {src} {ctx.workdir}/"
        console.print(f"\n[yellow]Command:[/yellow] [green]{cp_cmd}[/green]")
        _run(cp_cmd, ctx.print_only)

    print_done(f"Copied to {ctx.workdir}/")


def print_pretext_scp_commands(ctx: CurationContext) -> None:
    """
    Finds pretext maps on NFS and prints scp commands for the curator's local machine.

    The curator runs these commands on their laptop to download the maps directly
    from NFS — no intermediate copy to workdir is required.
    """
    log.info("print-pretext-scp | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Pretext map scp commands")

    try:
        sources = [str(s) for s in _find_pretext_maps(ctx)]
    except FileNotFoundError:
        log.warning("Pretext maps not found on NFS — showing glob patterns instead")
        sources = [
            str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*{suffix}.pretext")
            for suffix in ("hr", "normal", "ultra")
        ]

    console.print("\n[bold]To open in PretextView, run on your local machine:[/bold]")
    console.print(f"  [green]mkdir -p ~/curations/work/{ctx.tol_id}/[/green]")
    for src in sources:
        scp = f"scp {ctx.farm_host}:{src} ~/curations/work/{ctx.tol_id}/"
        console.print(f"  [green]{scp}[/green]")


def print_curation_summary(ctx: CurationContext) -> None:
    """
    Prints a human-readable summary of the curation ticket.

    Notebook source: ``pre_and_post_curation()`` — initial print statements.

    Output includes:
        - Ticket ID and ToL ID
        - Species name
        - Assembly type (hap1/hap2, primary/alternate, paternal/maternal)
        - combine_for_curation flag
        - HiC directory
        - Long-reads directory and read type
        - Draft assembly directory
        - Working directory
        - Teloseq setting (if any)
        - Expected karyotype and sex (from YAML, if present)
    """
    log.info("curation-summary | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Curation summary")

    log.info("Ticket: %s", ctx.ticket_id)
    log.info("ToL ID: %s", ctx.tol_id)
    log.info("Species: %s", ctx.species)
    log.info(
        "Assembly type: %s/%s (combine_for_curation=%s)",
        ctx.hap1_prefix,
        ctx.hap2_prefix,
        ctx.combine_for_curation,
    )
    log.info("HiC dir: %s", ctx.hic_dir)
    log.info("Long reads dir: %s", ctx.long_reads_dir)
    log.info("Read type: %s", ctx.read_type)
    log.info("Draft assembly: %s", ctx.assembly_draft_dir)
    log.info("Workdir: %s", ctx.workdir)

    if ctx.teloseq:
        log.info("Teloseq: %s", ctx.teloseq)

    # Optional fields from YAML
    yaml = ctx.yaml_data
    karyotype = yaml.get("karyotype") or yaml.get("expected_karyotype") or ""
    sex = yaml.get("sex") or yaml.get("expected_sex") or ""
    if karyotype:
        log.info("Karyotype: %s", karyotype)
    if sex:
        log.info("Sex: %s", sex)


_INSECT_PREFIXES = ("ic", "il", "id")


def run_setup(ctx: CurationContext) -> None:
    """
    Sets up the curation workspace: creates workdir, copies original.fa,
    and prints scp commands for pretext maps.
    """
    log.info("setup | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)

    # Record in global registry
    if not ctx.print_only:
        from grit.core.registry import RegistryManager
        RegistryManager().add_ticket(
            ctx.ticket_id, ctx.tol_id, ctx.species, ctx.workdir
        )

    # Track execution
    if ctx.tracker:
        run_dir = ctx.tracker.start("setup_curation", ctx.ticket_id, ctx.tol_id)

    print_curation_summary(ctx)
    try:
        setup_curation(ctx)
        print_pretext_scp_commands(ctx)
        if ctx.tracker and not ctx.print_only:
            ctx.tracker.finish("setup_curation", run_dir, "success")
    except Exception:
        if ctx.tracker and not ctx.print_only:
            ctx.tracker.finish("setup_curation", run_dir, "failed")
        raise

    if any(ctx.tol_id.lower().startswith(p) for p in _INSECT_PREFIXES):
        print_tip(
            f"If you see sex chromosomes on the map, run: "
            f"[bold cyan]grit sex-matcher -t {ctx.ticket_id}[/bold cyan]"
        )


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("setup", cls=GritCommand)
@click.pass_context
def setup_cmd(ctx):
    """Setup curation workspace."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_setup(curation_ctx)
    except Exception:
        log.exception("setup failed")
        raise SystemExit(1)
