"""Microchromosome second-shot curation: pre-curation step."""

import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _run,
    collect_outputs,
    find_canonical_chr_list,
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

# TEMP: pointing at dz11's branch checkout while add-hap-suffix-handling is
# unmerged — revert to /software/grit/projects/vgp_curation_scripts/... once
# that branch lands.
_SECOND_SHOT_SCRIPT = (
    "/nfs/users/nfs_d/dz11/gitlab/vgp_curation_scripts/birds_microchromosomes/"
    "microchr_second_shot_curation.py"
)

# Directory the curator copies the curated small-merged AGP into, so
# microchromosome-combine can't pick up a pretext-to-asm-generated AGP that
# happens to sit in the same run dir.
CURATED_SMALL_AGP_DIR = "curated_small_agp"

# microchr_second_shot_curation.py writes everything into a {tol_id}/
# subdirectory of the -o dir, and names its per-hap files with the literal
# "hap1"/"hap2" token plus a variable hap-suffix token (e.g.
# "{tol_id}.hap1.1.primary.curated.large.fa") — hence the tolerant *hap1*
# patterns rather than a fixed prefix. The flat pretext_map fallback covers a
# script version that keeps hic/ next to the {tol_id}/ subdir.
_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("hap1_large_fa", "{tol_id}/*hap1*.large.fa", []),
    ("hap2_large_fa", "{tol_id}/*hap2*.large.fa", []),
    ("hap1_large_chr", "{tol_id}/*hap1*.large.chr_list.csv", []),
    ("hap2_large_chr", "{tol_id}/*hap2*.large.chr_list.csv", []),
    ("merged_small_fa", "{tol_id}/*_curated_small_merged.fa", []),
    ("pretext_map", "{tol_id}/hic/pretext_maps_processed/*hr.pretext", []),
    ("pretext_map", "hic/pretext_maps_processed/*hr.pretext", []),
]

# ---------------------------------------------------------------------------
# Public step function
# ---------------------------------------------------------------------------


def run_microchromosome_second_shot(ctx: CurationContext) -> None:
    """
    PRE-curation step of the second-shot microchromosome workflow.

    Typically used for birds (tol_id starts with ``b``) and large genomes
    with many small chromosomes (<20 Mbp).

    Notebook source: ``bird_curation()`` function.

    Steps:
        1. Locate curated hap1 (and hap2, for dual-hap tickets) FASTAs and
           chromosome lists via ``find_canonical_fa``/``find_canonical_chr_list``.
        2. Run ``microchr_second_shot_curation.py`` which splits the assembly
           into large (>20 Mbp) and small (≤20 Mbp) scaffolds and runs HiC
           remapping on the merged small scaffolds. The script blocks
           internally on its own ``bsub -K`` MicroFinder/merge jobs, so its
           progress streams live to this terminal — this step runs
           synchronously (not an async bsub submission) to preserve that.

    Next step: curate the micro pretext map locally, then run
    ``microchromosome-combine`` (``run_microchromosome_combine``).

    Tracked as ``microchromosome_second_shot``.
    """
    log.info("microchromosome-second-shot | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Microchromosome second-shot curation")

    if ctx.dry_run:
        run_dir = ctx.tracker.start(
            "microchromosome_second_shot", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        outputs = write_fake_outputs("microchromosome_second_shot", run_dir, ctx.tol_id)
        (run_dir / CURATED_SMALL_AGP_DIR).mkdir(parents=True, exist_ok=True)
        if is_single_hap(ctx):
            # write_fake_outputs always writes both hap1/hap2 _OUTPUT_SPECS entries;
            # drop the hap2 ones (and delete the files it wrote) so a single-hap
            # dry-run leaves neither a tracked key nor an on-disk file that a later
            # real microchromosome-combine's filesystem glob could mistake for a
            # genuine hap2.
            for key in ("hap2_large_fa", "hap2_large_chr"):
                path = outputs.pop(key, None)
                if path:
                    Path(path).unlink(missing_ok=True)
        ctx.tracker.finish(
            "microchromosome_second_shot",
            run_dir,
            "success",
            outputs=outputs,
            untracked=ctx.untracked,
        )
        print_done(f"[dry-run] Microchromosome second-shot curation complete → {run_dir}")
        return

    # --- find curated fastas and chr lists via the canonical lookup chain ---
    # (rename_and_orient/blast_contaminants output preferred, pretext_to_asm fallback —
    # same resolution fastga/rename-and-orient use, not a hand-rolled glob).
    single_hap = is_single_hap(ctx)
    hap1_fa = find_canonical_fa(ctx, ctx.hap1_prefix)
    hap1_chr = find_canonical_chr_list(ctx, ctx.hap1_prefix)
    has_hap2 = not single_hap
    if has_hap2:
        hap2_fa = find_canonical_fa(ctx, ctx.hap2_prefix)
        hap2_chr = find_canonical_chr_list(ctx, ctx.hap2_prefix)
        hap2_argument = f"-hap2 {hap2_fa} -hap2_chr {hap2_chr}"
    else:
        hap2_argument = ""

    run_dir = (
        ctx.tracker.start(
            "microchromosome_second_shot", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        if ctx.tracker
        else ctx.workdir / "microchromosome_second_shot" / "untracked"
    )

    curated_agp_dir = run_dir / CURATED_SMALL_AGP_DIR
    if not ctx.print_only:
        curated_agp_dir.mkdir(parents=True, exist_ok=True)

    # --- run second-shot script (splits assembly + HiC remapping on smalls) ---
    second_shot_cmd = (
        f"cd {run_dir} && "
        f"{_SECOND_SHOT_SCRIPT} "
        f"-hap1 {hap1_fa} -hap1_chr {hap1_chr} {hap2_argument} "
        f"-hic {ctx.hic_dir} -lr {ctx.long_reads_dir}/fasta -rt {ctx.read_type} "
        f"-o {run_dir}"
    )
    outputs: dict[str, str] = {}
    try:
        _run(second_shot_cmd, ctx.print_only, capture=False)
        if ctx.tracker:
            outputs = collect_outputs(
                _OUTPUT_SPECS, run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
            )
            ctx.tracker.finish(
                "microchromosome_second_shot",
                run_dir,
                "success",
                outputs=outputs or None,
                untracked=ctx.untracked,
            )
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish(
                "microchromosome_second_shot", run_dir, "failed", untracked=ctx.untracked
            )
        raise

    # --- print scp of micro pretext map to local, and of the curated AGP back ---
    local_dir = f"~/curations/work/{ctx.tol_id}/second_shot_microchromosomes"
    pretext_src = outputs.get("pretext_map") or (
        f"{run_dir}/{ctx.tol_id}/hic/pretext_maps_processed/*hr.pretext"
    )
    print_tip(
        f"Download the micro pretext map and curate it locally:\n"
        f"[bold cyan]scp {ctx.farm_host}:{pretext_src} {local_dir}/[/bold cyan]\n"
        f"Then copy the curated small-merged AGP back into its own dir "
        f"(nothing else may go in there):\n"
        f"[bold cyan]scp {local_dir}/{ctx.tol_id}*.agp* "
        f"{ctx.farm_host}:{curated_agp_dir}/[/bold cyan]\n"
        f"Then run: [bold cyan]grit microchromosome-combine -t {ctx.ticket_id}[/bold cyan]"
    )

    print_done(f"Microchromosome second-shot curation submitted. Output → {run_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("microchromosome-second-shot", cls=GritCommand)
@click.pass_context
def microchromosome_second_shot_cmd(ctx):
    """Run microchromosome second-shot curation (pre)."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_microchromosome_second_shot(curation_ctx)
    except Exception:
        log.exception("microchromosome-second-shot failed")
        raise SystemExit(1)
