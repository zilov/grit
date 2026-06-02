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
    print_info,
    print_next_step,
    print_step_header,
    print_warning,
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
    print_info("Workdir", str(ctx.workdir))

    original_fa = ctx.workdir / "original.fa"

    # Glob for decontaminated hap1 FASTA
    # assembly_draft_dir already points to the versioned subdir,
    # e.g. .../assembly/draft/uoEpiScra1.20241115
    hap1_pattern = f"{ctx.assembly_draft_dir}/{ctx.tol_id}*{ctx.hap1_prefix}.decontaminated.fa*"
    hap2_pattern = f"{ctx.assembly_draft_dir}/{ctx.tol_id}*{ctx.hap2_prefix}.decontaminated.fa*"

    if ctx.print_only:
        # In print-only mode show expected paths without checking the filesystem
        decont_hap1 = hap1_pattern
        decont_hap2 = hap2_pattern
        print_info("hap1 FASTA (pattern)", decont_hap1)
        print_info("hap2 FASTA (pattern)", decont_hap2)
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
            print_warning("Alternate haplotype FASTA not found — creating single-hap original.fa")

    zcat_cmd = f"zcat {decont_hap1} {decont_hap2} > {original_fa}"
    console.print(f"\n[yellow]Command:[/yellow] [green]{zcat_cmd}[/green]")
    _run(zcat_cmd, ctx.print_only)

    print_done(f"original.fa → {original_fa}")


def copy_pretext_maps(ctx: CurationContext) -> None:
    """
    Finds pretext maps on NFS and copies them to workdir for editing.
    Prints scp commands for the curator's local machine.

    Notebook source: ``pre_and_post_curation()`` — pretext map handling.

    Steps:
        1. Glob for maps in ``ctx.pretext_maps_nfs``:
           - ``{tol_id}*hr.pretext``  (high-resolution)
           - ``{tol_id}*normal.pretext``
        2. If multiple files match, select the one with the highest version index
           (or the file containing "RC" in its name).
        3. ``cp {hr_pretext} {ctx.workdir}/``
           ``cp {normal_pretext} {ctx.workdir}/``
        4. Print scp commands for the curator to copy maps to their local machine::

               scp {ctx.farm_host}:{ctx.workdir}/{filename} ~/curations/{ctx.tol_id}/

    Prints:
        Step header, map filenames chosen, copy status, and scp commands.
    Next step hint: ``add_gap_track(ctx)``
    """
    log.info("copy-pretext-maps | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Copy pretext maps")

    hr_pattern = str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*hr.pretext")
    normal_pattern = str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*normal.pretext")

    if ctx.print_only:
        print_info("HR map (pattern)", hr_pattern)
        print_info("Normal map (pattern)", normal_pattern)
        console.print("\n[bold]To open in PretextView, run on your local machine:[/bold]")
        for pattern in (hr_pattern, normal_pattern):
            scp = f"scp {ctx.farm_host}:{ctx.workdir}/<matched_file> ~/curations/{ctx.tol_id}/"
            console.print(f"  [green]{scp}[/green]")
        print_next_step("add_gap_track(ctx)")
        return

    hr_files = glob.glob(hr_pattern)
    normal_files = glob.glob(normal_pattern)

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

    print_info("HR map", hr_src.name)
    print_info("Normal map", normal_src.name)
    print_info("Maps found", f"{len(hr_files)} hr, {len(normal_files)} normal")

    for src in (hr_src, normal_src):
        cp_cmd = f"cp {src} {ctx.workdir}/"
        console.print(f"\n[yellow]Command:[/yellow] [green]{cp_cmd}[/green]")
        _run(cp_cmd, ctx.print_only)

    print_done(f"Copied to {ctx.workdir}/")

    console.print("\n[bold]To open in PretextView, run on your local machine:[/bold]")
    for src in (hr_src, normal_src):
        dest_name = src.name
        scp = f"scp {ctx.farm_host}:{ctx.workdir}/{dest_name} ~/curations/{ctx.tol_id}/"
        console.print(f"  [green]{scp}[/green]")

    print_next_step("add_gap_track(ctx)")


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

    print_info("Ticket", ctx.ticket_id)
    print_info("ToL ID", ctx.tol_id)
    print_info("Species", ctx.species)
    print_info(
        "Assembly type",
        f"{ctx.hap1_prefix}/{ctx.hap2_prefix}  (combine_for_curation={ctx.combine_for_curation})",
    )
    print_info("HiC dir", str(ctx.hic_dir))
    print_info("Long reads dir", str(ctx.long_reads_dir))
    print_info("Read type", ctx.read_type)
    print_info("Draft assembly", str(ctx.assembly_draft_dir))
    print_info("Workdir", str(ctx.workdir))

    if ctx.teloseq:
        print_info("Teloseq", ctx.teloseq)

    # Optional fields from YAML
    yaml = ctx.yaml_data
    karyotype = yaml.get("karyotype") or yaml.get("expected_karyotype") or ""
    sex = yaml.get("sex") or yaml.get("expected_sex") or ""
    if karyotype:
        print_info("Karyotype", str(karyotype))
    if sex:
        print_info("Sex", str(sex))


def run_setup(ctx: CurationContext) -> None:
    """
    Sets up the curation workspace: creates workdir, copies original.fa,
    pretext maps, and prints summary.
    """
    log.info("setup | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_curation_summary(ctx)
    setup_curation(ctx)
    copy_pretext_maps(ctx)


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
