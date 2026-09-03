"""Pre-curation steps: workspace setup before manual curation."""

import glob
import gzip
import logging
import re
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

_SCAFFOLD_HEADER_RE = re.compile(r"^>(HAP\d+_)?SCAFFOLD_\d+")

# ---------------------------------------------------------------------------
# Decontaminated FASTA resolution
# ---------------------------------------------------------------------------


def _resolve_hap1_fasta(ctx: CurationContext) -> str:
    """
    Globs for the decontaminated hap1 FASTA in ``ctx.assembly_draft_dir``.

    Falls back to a bare ``*.decontaminated.fa*`` pattern if the
    ``hap1_prefix``-qualified pattern finds nothing.

    Raises:
        FileNotFoundError: if neither pattern matches.
    """
    hap1_pattern = str(
        ctx.assembly_draft_dir / f"{ctx.tol_id}*{ctx.hap1_prefix}.decontaminated.fa*"
    )
    hap1_files = glob.glob(hap1_pattern)
    if not hap1_files:
        hap1_files = glob.glob(str(ctx.assembly_draft_dir / f"{ctx.tol_id}*.decontaminated.fa*"))
    if not hap1_files:
        raise FileNotFoundError(f"No decontaminated hap1 FASTA found at: {hap1_pattern}")
    return _sort_by_mtime(hap1_files)[0]


def _resolve_hap2_fasta(ctx: CurationContext) -> str:
    """
    Globs for the decontaminated hap2 FASTA in ``ctx.assembly_draft_dir``.

    Falls back to a literal ``*haplotigs.decontaminated.fa*`` pattern — some
    primary assemblies use "haplotigs" rather than the YAML-derived
    ``hap2_prefix`` (e.g. "alternate") in their filenames.

    Returns:
        The resolved path, or "" if neither pattern matches (single-hap assembly).
    """
    hap2_pattern = str(
        ctx.assembly_draft_dir / f"{ctx.tol_id}*{ctx.hap2_prefix}.decontaminated.fa*"
    )
    hap2_files = glob.glob(hap2_pattern)
    if not hap2_files:
        hap2_files = glob.glob(
            str(ctx.assembly_draft_dir / f"{ctx.tol_id}*haplotigs.decontaminated.fa*")
        )
    if not hap2_files:
        return ""
    return _sort_by_mtime(hap2_files)[0]


def _peek_first_fasta_header(fasta_path: str) -> str:
    """Returns the first ``>``-prefixed header line of a (possibly gzipped) FASTA."""
    opener = gzip.open if str(fasta_path).endswith(".gz") else open
    with opener(fasta_path, "rt") as fh:
        for line in fh:
            if line.startswith(">"):
                return line.strip()
    return ""


def _validate_scaffold_headers(fasta_path: str) -> None:
    """
    Raises ValueError if the first header of *fasta_path* isn't SCAFFOLD_N / HAP<N>_SCAFFOLD_N.

    Catches decontamination pipelines that didn't rename contigs to the
    curation-ready convention before setup_curation concatenates them into
    original.fa.
    """
    header = _peek_first_fasta_header(fasta_path)
    if not _SCAFFOLD_HEADER_RE.match(header):
        raise ValueError(
            f"{fasta_path} has unexpected header {header!r} — expected "
            f"SCAFFOLD_N / HAP<N>_SCAFFOLD_N. Upstream decontamination likely "
            f"didn't rename contigs; fix upstream before re-running setup."
        )


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

           Decontaminated files are resolved via :func:`_resolve_hap1_fasta` /
           :func:`_resolve_hap2_fasta`. If multiple files match, the newest
           (by mtime) is chosen. Each file's first header is validated
           against the SCAFFOLD_N / HAP<N>_SCAFFOLD_N convention before concatenation.

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

    # assembly_draft_dir already points to the versioned subdir,
    # e.g. .../assembly/draft/uoEpiScra1.20241115
    if ctx.print_only:
        # Resolve for real (read-only glob) so print-only reflects what a real
        # run would pick, including the "haplotigs" fallback for hap2.
        try:
            decont_hap1 = _resolve_hap1_fasta(ctx)
        except FileNotFoundError as exc:
            decont_hap1 = f"<{exc}>"
        decont_hap2 = _resolve_hap2_fasta(ctx) or "<no hap2 FASTA found>"
        log.info("hap1 FASTA: %s", decont_hap1)
        log.info("hap2 FASTA: %s", decont_hap2)
    else:
        decont_hap1 = _resolve_hap1_fasta(ctx)
        _validate_scaffold_headers(decont_hap1)

        decont_hap2 = _resolve_hap2_fasta(ctx)
        if decont_hap2:
            _validate_scaffold_headers(decont_hap2)
        else:
            log.warning("Alternate haplotype FASTA not found — creating single-hap original.fa")

    zcat_cmd = f"zcat {decont_hap1} {decont_hap2} > {original_fa}"
    _run(zcat_cmd, ctx.print_only)

    if not ctx.print_only:
        print_done(f"original.fa → {original_fa}")


def _find_pretext_maps(ctx: CurationContext) -> tuple[Path, Path]:
    """
    Resolves pretext maps for *hr* and *normal* (required) and *ultra* (optional)
    in ``ctx.pretext_maps_nfs``.

    Prefers maps whose filename contains the current ticket ID (e.g. RC-4645).
    Falls back to all tol_id matches if none contain the ticket ID.

    Returns:
        List of resolved Path objects: [hr_src, normal_src] plus ultra_src if found.

    Raises:
        FileNotFoundError: if no match is found for hr or normal.
    """
    ticket_id = ctx.ticket_id

    def _ticket_filter(files: list[str]) -> list[str]:
        """Return only files containing the ticket ID; fall back to all if none match."""
        filtered = [f for f in files if ticket_id in Path(f).name]
        return filtered if filtered else files

    hr_files = _ticket_filter(glob.glob(str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*hr.pretext")))
    normal_files = _ticket_filter(
        glob.glob(str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*normal.pretext"))
    )
    ultra_files = _ticket_filter(
        glob.glob(str(ctx.pretext_maps_nfs / f"{ctx.tol_id}*ultra.pretext"))
    )

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

    if ctx.dry_run:
        from grit.core.registry import RegistryManager, dry_run_root

        ctx.workdir.mkdir(parents=True, exist_ok=True)
        RegistryManager(registry_dir=dry_run_root()).add_ticket(
            ctx.ticket_id,
            ctx.tol_id,
            ctx.species,
            ctx.workdir,
            hap1_prefix=ctx.hap1_prefix,
            hap2_prefix=ctx.hap2_prefix,
        )
        run_dir = ctx.tracker.start(
            "setup_curation", ctx.ticket_id, ctx.tol_id, create_dir=False, untracked=ctx.untracked
        )
        (ctx.workdir / "original.fa").write_bytes(b">fake\nACGT\n")
        ctx.tracker.finish("setup_curation", run_dir, "success", untracked=ctx.untracked)
        print_done(f"[dry-run] ticket registered, workdir → {ctx.workdir}")
        return

    # Record in global registry
    if not ctx.print_only:
        from grit.core.registry import RegistryManager

        RegistryManager().add_ticket(
            ctx.ticket_id,
            ctx.tol_id,
            ctx.species,
            ctx.workdir,
            hap1_prefix=ctx.hap1_prefix,
            hap2_prefix=ctx.hap2_prefix,
        )

    # Track execution
    if ctx.tracker:
        run_dir = ctx.tracker.start(
            "setup_curation", ctx.ticket_id, ctx.tol_id, create_dir=False, untracked=ctx.untracked
        )

    print_curation_summary(ctx)
    try:
        setup_curation(ctx)
        print_pretext_scp_commands(ctx)
        if ctx.tracker and not ctx.print_only:
            ctx.tracker.finish("setup_curation", run_dir, "success", untracked=ctx.untracked)
    except Exception:
        if ctx.tracker and not ctx.print_only:
            ctx.tracker.finish("setup_curation", run_dir, "failed", untracked=ctx.untracked)
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
