"""Blast scaffolds for contaminant detection using deconBlast."""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _clean_species_name, _run, find_latest_dir
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to lineage script
LINEAGE_SCRIPT = "/software/grit/projects/vgp_curation_scripts/get_lineage_from_species.rb"


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_blast_contaminants(ctx: CurationContext) -> None:
    """
    Run blast contaminants search in shrapnel scaffolds.

    This step identifies potential contaminants in the curated assembly by blasting
    scaffolds against a database and filtering based on taxonomic lineage.

    Steps:
        1. Find the curated FASTA file in workdir (e.g., {tol_id}*.curated.fa).
        2. Create blast.me input file with scaffold IDs.
        3. Run decon_blastBTK to perform BLAST searches.
        4. Extract taxonomic information from BLAST results.
        5. Identify non-target contaminants (e.g., non-mollusc hits).
        6. Create contaminated.bed file with contaminant regions.
        7. Remove contaminants from the curated FASTA.

    Requires:
        - Curated FASTA file in workdir.
        - Access to ~mh6/decon_blastBTK and related scripts.

    Prints:
        Step header, file paths, commands executed.
    """
    log.info("blast-contaminants | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Blast contaminants search")

    run_dir = ctx.tracker.start("blast_contaminants", ctx.ticket_id, ctx.tol_id, invalidated=ctx.invalidated) if ctx.tracker else None
    try:
        _blast_contaminants_body(ctx)
        if ctx.tracker and run_dir:
            ctx.tracker.finish("blast_contaminants", run_dir, "success")
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("blast_contaminants", run_dir, "failed")
        raise


def _blast_contaminants_body(ctx: CurationContext) -> None:
    # Get target phylum from species lineage
    cleaned_species = _clean_species_name(ctx.species)
    log.info("Species: %s", cleaned_species)

    lineage_cmd = f"{LINEAGE_SCRIPT} {cleaned_species}"
    our_lineage = _run(lineage_cmd, ctx.print_only).strip()
    log.info("Species lineage: %s", our_lineage)

    # Parse phylum (typically 4th element: Eukaryota; Metazoa; ...; Phylum; ...)
    lineage_parts = [part.strip() for part in our_lineage.split(";")]
    target_phylum = lineage_parts[3] if len(lineage_parts) > 3 else "Unknown"
    log.info("Target phylum: %s", target_phylum)

    # 1. Find curated FASTA
    # haplotig-files writes *.curated.fa into the pretext_to_asm run dir, not workdir root
    base_dir = find_latest_dir(ctx, "pretext_to_asm")
    curated_fa_pattern = str(base_dir / f"{ctx.tol_id}*.curated.fa")
    curated_fa_files = glob.glob(curated_fa_pattern)
    if not curated_fa_files:
        raise FileNotFoundError(f"No curated FASTA found: {curated_fa_pattern}")
    curated_fasta = Path(curated_fa_files[0])
    log.info("Curated FASTA: %s", curated_fasta)

    # 2. Create blast.me file
    blast_me = ctx.workdir / "blast.me"
    log.info("Blast input file: %s", blast_me)

    # Create header
    header_cmd = f"echo 'header' > {blast_me}"
    _run(header_cmd, ctx.print_only)

    # Extract scaffold IDs (assuming SCAFFOLD_X or HAP_SCAFFOLD_X format)
    extract_cmd = (
        f"perl -nE 'say \"true,$1\" if /([HAP_\\d]*SCAFFOLD_\\d+)/i' {curated_fasta} >> {blast_me}"
    )
    _run(extract_cmd, ctx.print_only)

    # 3. Run decon_blastBTK
    blast_out_dir = ctx.workdir / "blast_out_dir"
    blast_cmd = f"~mh6/decon_blastBTK -b {blast_me} -f {curated_fasta} -o {blast_out_dir}"
    _run(blast_cmd, ctx.print_only)
    log.info("Blast output dir: %s", blast_out_dir)

    # 4. Extract taxonomic information
    taxonomy_txt = blast_out_dir / "taxonomy.txt"
    cd_cmd = f"cd {blast_out_dir}"
    _run(cd_cmd, ctx.print_only)

    taxonomy_cmd = (
        "head -1 *out | "
        "grep -i -e ^SCAFFOLD -e ^HAP | "
        "perl -nE '"
        "s/PREDICTED:|MAG:|TPA_\\w+://; "
        "@F=split; "
        "chomp; "
        "@F[14]=~s/,//g; "
        '$F[14].=" ".$F[15] if $F[14] eq "sp."; '
        'print "$_\t"; '
        'say `{LINEAGE_SCRIPT} "$F[13] $F[14]"`;\' '
        f"> {taxonomy_txt}"
    )
    _run(taxonomy_cmd, ctx.print_only)
    log.info("Taxonomy file: %s", taxonomy_txt)

    # 5. Create contaminated.bed (filter non-target phylum hits)
    contaminated_bed = ctx.workdir / f"{ctx.tol_id}.contaminated.bed"
    bed_cmd = (
        f"grep -v {target_phylum} {taxonomy_txt} | "
        "perl -anE 'say \"$F[0]\\t0\\t10000\\tREMOVE\"' "
        f">> {contaminated_bed}"
    )
    _run(bed_cmd, ctx.print_only)
    log.info("Contaminated BED: %s", contaminated_bed)

    # 6. Remove contamination from FASTA
    backup_fasta = curated_fasta.with_suffix(".original.fa")
    mv_backup_cmd = f"mv {curated_fasta} {backup_fasta}"
    _run(mv_backup_cmd, ctx.print_only)

    remove_cmd = f"~mh6/remove_contamination_bed -f {backup_fasta} -c {contaminated_bed}"
    _run(remove_cmd, ctx.print_only)

    # The script likely produces curated_fasta_cleaned, rename it back
    cleaned_fasta = backup_fasta.with_suffix(".cleaned.fa")
    if not ctx.print_only:
        if cleaned_fasta.exists():
            mv_clean_cmd = f"mv {cleaned_fasta} {curated_fasta}"
            _run(mv_clean_cmd, ctx.print_only)
        else:
            log.warning("Cleaned FASTA not found: %s", cleaned_fasta)
    else:
        log.info("Would rename: %s -> %s", cleaned_fasta, curated_fasta)

    print_done("Contaminant blasting completed")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("blast-contaminants", cls=GritCommand)
@click.pass_context
def blast_contaminants_cmd(ctx):
    """Run blast contaminants search in shrapnel scaffolds."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_blast_contaminants(curation_ctx)
    except Exception:
        log.exception("blast-contaminants failed")
        raise SystemExit(1)
