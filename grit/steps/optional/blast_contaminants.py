"""Blast scaffolds for contaminant detection using decon_fasta."""

from __future__ import annotations

import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _clean_species_name,
    _run,
    find_canonical_fa,
    is_single_hap,
    write_fake_outputs,
)
from grit.utils.output import (
    print_done,
    print_step_header,
    print_tip,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to lineage script
LINEAGE_SCRIPT = "/software/grit/projects/vgp_curation_scripts/get_lineage_from_species.rb"
# Blasts scaffolds (headers matching .*SCAFFOLD_\d+.*) and writes a taxonomy.txt
# with lineage per blast hit into the given --outdir.
DECON_SCRIPT = "~mh6/git_checkouts/reblast/bin/decon_fasta"

_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("hap1_fa", "{hap1}/{tol_id}.{hap1}.*.decontaminated.fa", []),
    ("hap2_fa", "{hap2}/{tol_id}.{hap2}.*.decontaminated.fa", []),
]


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_blast_contaminants(ctx: CurationContext) -> None:
    """
    Run blast contaminants search in shrapnel scaffolds, once per haplotype.

    This step identifies potential contaminants in the curated assembly by blasting
    scaffolds against a database and filtering based on taxonomic lineage. It reads
    whatever is currently canonical for this haplotype and writes a distinctly-named
    decontaminated FASTA into its own ``run_dir/<hap_prefix>/`` subdirectory, alongside
    that haplotype's ``decon_fasta`` output and ``contaminated.bed`` — the original
    curated FASTA is never modified or moved, so re-running or invalidating this step
    cannot lose data.

    Requires:
        - A resolvable canonical FASTA for each haplotype — run ``pretext-to-asm`` first.
        - Access to ``decon_fasta`` and related scripts.

    If no non-target-phylum hits are found, no scaffolds are removed: no
    decontaminated FASTA is written and the haplotype's canonical output is
    left untouched.

    Prints:
        Step header, file paths, commands executed.
    """
    log.info("blast-contaminants | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Blast contaminants search")

    if ctx.dry_run:
        run_dir = ctx.tracker.start(
            "blast_contaminants", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        outputs = write_fake_outputs(
            "blast_contaminants",
            run_dir,
            ctx.tol_id,
            hap1=ctx.hap1_prefix,
            hap2=ctx.hap2_prefix,
        )
        if is_single_hap(ctx):
            # write_fake_outputs always writes both _OUTPUT_SPECS entries (keyed
            # "hap1_fa"/"hap2_fa" regardless of assembly_type); drop the hap2 key
            # AND delete the file itself, so a single-hap dry-run's tracked outputs
            # and on-disk state both match what a real run would actually produce.
            path = outputs.pop("hap2_fa", None)
            if path:
                Path(path).unlink(missing_ok=True)
        ctx.tracker.finish(
            "blast_contaminants", run_dir, "success", outputs=outputs, untracked=ctx.untracked
        )
        dest = outputs.get("hap1_fa", run_dir)
        print_done(f"[dry-run] Decontaminated FASTA → {dest}")
        return

    run_dir = (
        ctx.tracker.start("blast_contaminants", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else None
    )

    haps_to_process = (
        [ctx.hap1_prefix] if is_single_hap(ctx) else [ctx.hap1_prefix, ctx.hap2_prefix]
    )

    try:
        outputs: dict[str, str] = {}
        for hap_prefix in haps_to_process:
            dest = _blast_contaminants_for_hap(ctx, hap_prefix, run_dir)
            if dest is not None:
                outputs[f"{hap_prefix}_fa"] = str(dest)
        if ctx.tracker and run_dir:
            ctx.tracker.finish(
                "blast_contaminants",
                run_dir,
                "success",
                outputs=outputs or None,
                untracked=ctx.untracked,
            )
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("blast_contaminants", run_dir, "failed", untracked=ctx.untracked)
        raise

    print_done("Contaminant blasting completed")


def _blast_contaminants_for_hap(
    ctx: CurationContext, hap_prefix: str, run_dir: Path | None
) -> Path | None:
    """
    Blast one haplotype's curated FASTA and return the decontaminated output path,
    or ``None`` if no non-target-phylum hits were found (canonical is left untouched).
    """
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

    # All of this haplotype's outputs — decon_fasta's own out_dir, the bed
    # filter, and the final decontaminated FASTA — live together under one
    # per-haplotype subdirectory of the run_dir.
    hap_dir = (run_dir or ctx.workdir) / hap_prefix
    _run(f"mkdir -p {hap_dir}", ctx.print_only)

    # 2. Blast scaffolds and write per-hit lineage — decon_fasta finds SCAFFOLD_N
    #    headers itself, so no separate blast.me extraction step is needed.
    blast_out_dir = hap_dir / "blast_out_dir"
    decon_cmd = f"{DECON_SCRIPT} --fasta {curated_fasta} --outdir {blast_out_dir}"
    _run(decon_cmd, ctx.print_only)
    log.info("[%s] Blast output dir: %s", hap_prefix, blast_out_dir)

    taxonomy_txt = blast_out_dir / "taxonomy.txt"
    log.info("[%s] Taxonomy file: %s", hap_prefix, taxonomy_txt)

    # 3. Create contaminated.bed (filter non-target phylum hits)
    contaminated_bed = hap_dir / f"{ctx.tol_id}.{hap_prefix}.contaminated.bed"
    bed_cmd = (
        f"grep -v {target_phylum} {taxonomy_txt} | "
        "perl -anE 'say \"$F[0]\\t0\\t10000\\tREMOVE\"' "
        f">> {contaminated_bed}"
    )
    _run(bed_cmd, ctx.print_only)
    log.info("[%s] Contaminated BED: %s", hap_prefix, contaminated_bed)

    if not ctx.print_only and contaminated_bed.stat().st_size == 0:
        print_tip(f"[{hap_prefix}] No contaminants found — canonical FASTA left unchanged.")
        return None

    # 4. Remove contamination — remove_contamination_bed writes its output next
    #    to the (untouched) original as ``<curated_fasta.name>_cleaned``; the
    #    original pretext_to_asm output is never renamed or moved, so it stays
    #    intact regardless of how this step turns out.
    remove_cmd = f"~mh6/remove_contamination_bed -f {curated_fasta} -c {contaminated_bed}"
    _run(remove_cmd, ctx.print_only)

    cleaned_fasta = curated_fasta.with_name(curated_fasta.name + "_cleaned")
    dest = hap_dir / f"{ctx.tol_id}.{hap_prefix}.{ctx.release_version}.decontaminated.fa"

    if not ctx.print_only:
        if not cleaned_fasta.exists():
            raise RuntimeError(
                f"[{hap_prefix}] remove_contamination_bed did not produce the expected "
                f"cleaned FASTA: {cleaned_fasta}"
            )
        _run(f"mv {cleaned_fasta} {dest}", ctx.print_only)
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
