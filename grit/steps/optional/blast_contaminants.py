"""Blast scaffolds for contaminant detection using deconBlast."""

from __future__ import annotations

import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _clean_species_name, _run, find_canonical_fa
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
    Run blast contaminants search in shrapnel scaffolds, once per haplotype.

    This step identifies potential contaminants in the curated assembly by blasting
    scaffolds against a database and filtering based on taxonomic lineage. It reads
    whatever is currently canonical for this haplotype and writes a distinctly-named
    decontaminated FASTA into its own run_dir — the original curated FASTA is never
    modified or moved, so re-running or invalidating this step cannot lose data.

    Requires:
        - Curated FASTA file(s) from ``pretext_to_asm`` in the workdir.
        - Access to ~mh6/decon_blastBTK and related scripts.

    Prints:
        Step header, file paths, commands executed.
    """
    log.info("blast-contaminants | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Blast contaminants search")

    run_dir = (
        ctx.tracker.start("blast_contaminants", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else None
    )

    is_single_hap = ctx.hap1_prefix in ("primary", "paternal")
    haps_to_process = [ctx.hap1_prefix] if is_single_hap else [ctx.hap1_prefix, ctx.hap2_prefix]

    try:
        outputs: dict[str, str] = {}
        for hap_prefix in haps_to_process:
            dest = _blast_contaminants_for_hap(ctx, hap_prefix, run_dir)
            outputs[f"{hap_prefix}_fa"] = str(dest)
        if ctx.tracker and run_dir:
            ctx.tracker.finish("blast_contaminants", run_dir, "success", outputs=outputs or None)
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("blast_contaminants", run_dir, "failed")
        raise

    print_done("Contaminant blasting completed")


def _blast_contaminants_for_hap(
    ctx: CurationContext, hap_prefix: str, run_dir: Path | None
) -> Path:
    """Blast one haplotype's curated FASTA and return the decontaminated output path."""
    # Get target phylum from species lineage
    cleaned_species = _clean_species_name(ctx.species)
    log.info("[%s] Species: %s", hap_prefix, cleaned_species)

    lineage_cmd = f"{LINEAGE_SCRIPT} {cleaned_species}"
    our_lineage = _run(lineage_cmd, ctx.print_only).strip()
    log.info("[%s] Species lineage: %s", hap_prefix, our_lineage)

    # Parse phylum (typically 4th element: Eukaryota; Metazoa; ...; Phylum; ...)
    lineage_parts = [part.strip() for part in our_lineage.split(";")]
    target_phylum = lineage_parts[3] if len(lineage_parts) > 3 else "Unknown"
    log.info("[%s] Target phylum: %s", hap_prefix, target_phylum)

    # 1. Find this haplotype's currently canonical FASTA — whatever step most
    #    recently produced it (pretext_to_asm, microchromosome_combine, a previous
    #    rename_and_orient/blast_contaminants, or a recurate run).
    curated_fasta = find_canonical_fa(ctx, hap_prefix)
    log.info("[%s] Curated FASTA: %s", hap_prefix, curated_fasta)

    # 2. Create blast.me file
    blast_me = ctx.workdir / f"blast_{hap_prefix}.me"
    log.info("[%s] Blast input file: %s", hap_prefix, blast_me)

    header_cmd = f"echo 'header' > {blast_me}"
    _run(header_cmd, ctx.print_only)

    # Extract scaffold IDs (assuming SCAFFOLD_X or HAP_SCAFFOLD_X format)
    extract_cmd = (
        f"perl -nE 'say \"true,$1\" if /([HAP_\\d]*SCAFFOLD_\\d+)/i' {curated_fasta} >> {blast_me}"
    )
    _run(extract_cmd, ctx.print_only)

    if not ctx.print_only:
        lines = blast_me.read_text().splitlines()
        has_scaffold_lines = len(lines) > 1
        if not has_scaffold_lines:
            log.warning(
                "[%s] No scaffold IDs extracted from %s — its headers don't look like "
                "pretext_to_asm SCAFFOLD names, so no contaminant scaffolds could be "
                "identified. This will produce a copy of the input with no scaffolds "
                "removed.",
                hap_prefix,
                curated_fasta,
            )

    # 3. Run decon_blastBTK
    blast_out_dir = ctx.workdir / f"blast_out_dir_{hap_prefix}"
    blast_cmd = f"~mh6/decon_blastBTK -b {blast_me} -f {curated_fasta} -o {blast_out_dir}"
    _run(blast_cmd, ctx.print_only)
    log.info("[%s] Blast output dir: %s", hap_prefix, blast_out_dir)

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
    log.info("[%s] Taxonomy file: %s", hap_prefix, taxonomy_txt)

    # 5. Create contaminated.bed (filter non-target phylum hits)
    contaminated_bed = ctx.workdir / f"{ctx.tol_id}.{hap_prefix}.contaminated.bed"
    bed_cmd = (
        f"grep -v {target_phylum} {taxonomy_txt} | "
        "perl -anE 'say \"$F[0]\\t0\\t10000\\tREMOVE\"' "
        f">> {contaminated_bed}"
    )
    _run(bed_cmd, ctx.print_only)
    log.info("[%s] Contaminated BED: %s", hap_prefix, contaminated_bed)

    # 6. Remove contamination — writes {curated_fasta}.cleaned.fa next to the
    #    (untouched) original; the original pretext_to_asm output is never renamed
    #    or moved, so it stays intact regardless of how this step turns out.
    remove_cmd = f"~mh6/remove_contamination_bed -f {curated_fasta} -c {contaminated_bed}"
    _run(remove_cmd, ctx.print_only)

    cleaned_fasta = curated_fasta.with_suffix(".cleaned.fa")
    dest = (
        run_dir or ctx.workdir
    ) / f"{ctx.tol_id}.{hap_prefix}.{ctx.release_version}.decontaminated.fa"

    if not ctx.print_only:
        if cleaned_fasta.exists():
            _run(f"mv {cleaned_fasta} {dest}", ctx.print_only)
        else:
            log.warning("[%s] Cleaned FASTA not found: %s", hap_prefix, cleaned_fasta)
    else:
        log.info("[%s] Would move: %s -> %s", hap_prefix, cleaned_fasta, dest)

    return dest


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
