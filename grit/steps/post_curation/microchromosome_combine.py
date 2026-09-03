"""Microchromosome second-shot curation: combine (post-curation) step."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core
from grit.utils.helpers import (
    _run,
    collect_outputs,
    find_latest_dir,
    is_single_hap,
    write_fake_outputs,
)
from grit.utils.output import print_done, print_step_header

log = logging.getLogger(__name__)

# TEMP: pointing at dz11's branch checkout while add-hap-suffix-handling is
# unmerged — revert to /software/grit/projects/vgp_curation_scripts/... once
# that branch lands.
_COMBINE_CURATED_MICROS_SCRIPT = (
    "/nfs/users/nfs_d/dz11/gitlab/vgp_curation_scripts/birds_microchromosomes/"
    "combine_curated_micros.py"
)

# microchr_second_shot_curation.py's own CLI always takes "-hap1"/"-hap2"
# regardless of the ticket's YAML key (hap1/hap2 vs primary/alternate), and
# names every file it produces with the literal "hap1"/"hap2" token — so all
# micro-workflow-internal glob patterns below use that literal token, not
# ctx.hap1_prefix/ctx.hap2_prefix. find_canonical_fa/find_canonical_chr_list
# already know to look up "hap1_fa"/"hap2_fa" tracker keys as an alias for
# primary/alternate tickets, so this doesn't break single-hap lookups.
#
# Outputs of the pretext-to-asm run over the curated micro-assembly AGP.
# Confirm exact naming against a real pretext-to-asm run once available —
# derived from the {tol_id}_small.fa prefix passed as -o.
_MICRO_PTA_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("hap1_fa", "{tol_id}_small.hap1.*.curated.fa", []),
    ("hap2_fa", "{tol_id}_small.hap2.*.curated.fa", []),
    ("hap1_chr_list", "{tol_id}_small.hap1.*.chromosome.list.csv", []),
    ("hap2_chr_list", "{tol_id}_small.hap2.*.chromosome.list.csv", []),
]

_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("hap1_fa", "{tol_id}.hap1.fa", []),
    ("hap2_fa", "{tol_id}.hap2.fa", []),
    ("hap1_chr_list", "{tol_id}.hap1.chromosome.list.csv", []),
    ("hap2_chr_list", "{tol_id}.hap2.chromosome.list.csv", []),
]

# ---------------------------------------------------------------------------
# Public step function
# ---------------------------------------------------------------------------


def run_microchromosome_combine(ctx: CurationContext) -> None:
    """
    POST-curation step of the second-shot microchromosome workflow.

    Run after the micro pretext map has been curated locally and the
    resulting AGP has been copied back to the ``microchromosome-second-shot``
    run dir.

    Steps:
        1. Locate the ``microchromosome-second-shot`` run dir and its merged
           small FASTA.
        2. Run ``pretext-to-asm`` on the merged small FASTA using the
           curated micro AGP (tracked as ``pretext_to_asm_micro``), producing
           per-hap curated small fasta/chromosome-lists.
        3. Combine each haplotype's curated small fasta/chr-list with the
           corresponding large fasta/chr-list (produced by the pre step) via
           ``combine_curated_micros.py``.

    The merged output becomes the canonical assembly for downstream steps
    (fastga, rename-and-orient, finalize-qc) via ``find_canonical_fa``/
    ``find_canonical_chr_list``.

    Tracked as ``microchromosome_combine``.
    """
    log.info("microchromosome-combine | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Microchromosome combine")

    if ctx.dry_run:
        run_dir = ctx.tracker.start(
            "microchromosome_combine", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        outputs = write_fake_outputs("microchromosome_combine", run_dir, ctx.tol_id)
        if is_single_hap(ctx):
            # microchromosome-second-shot's own tooling always names dual-hap
            # outputs with the literal "hap1"/"hap2" token regardless of YAML
            # key — but a single-hap (primary/alternate) assembly never has a
            # genuine second haplotype to combine, so drop the hap2 stub AND
            # delete the file itself, matching what a real run would produce.
            for key in ("hap2_fa", "hap2_chr_list"):
                path = outputs.pop(key, None)
                if path:
                    Path(path).unlink(missing_ok=True)
        ctx.tracker.finish(
            "microchromosome_combine", run_dir, "success", outputs=outputs, untracked=ctx.untracked
        )
        dest = outputs.get("hap1_fa", run_dir)
        print_done(f"[dry-run] Microchromosome combine complete. Final merged FASTAs → {dest}")
        return

    second_shot_dir = find_latest_dir(ctx, "microchromosome_second_shot")

    # --- find merged small FASTA produced by the pre step ---
    merged_small_matches = glob.glob(str(second_shot_dir / "*_curated_small_merged.fa"))
    if ctx.print_only:
        merged_small_fa = (
            Path(sorted(merged_small_matches)[-1])
            if merged_small_matches
            else second_shot_dir / f"{ctx.tol_id}_curated_small_merged.fa"
        )
    elif not merged_small_matches:
        raise FileNotFoundError(
            f"No merged small FASTA found in {second_shot_dir}.\n"
            f"Run 'grit microchromosome-second-shot -t {ctx.ticket_id}' first."
        )
    else:
        merged_small_fa = Path(sorted(merged_small_matches)[-1])
    log.info("Merged small FASTA: %s", merged_small_fa)

    # --- run pretext-to-asm on the curated micro AGP ---
    pta_micro_run_dir = _run_pretext_to_asm_core(
        ctx,
        "pretext_to_asm_micro",
        merged_small_fa,
        f"Merged small FASTA not found at {merged_small_fa}. "
        "Run microchromosome-second-shot first.",
        second_shot_dir,
        f"{ctx.tol_id}_small.fa",
        _MICRO_PTA_OUTPUT_SPECS,
    )
    small_outputs = collect_outputs(_MICRO_PTA_OUTPUT_SPECS, pta_micro_run_dir, ctx.tol_id)

    # --- find large fastas/chr lists produced by the pre step ---
    large_glob_specs: list[tuple[str, str, list[str]]] = [
        ("hap1_large_fa", "*.hap1.large.fa", []),
        ("hap2_large_fa", "*.hap2.large.fa", []),
        ("hap1_large_chr", "*.hap1.large.chr_list.csv", []),
        ("hap2_large_chr", "*.hap2.large.chr_list.csv", []),
    ]
    large_outputs = collect_outputs(large_glob_specs, second_shot_dir, ctx.tol_id)

    has_hap2 = (
        bool(large_outputs.get("hap2_large_fa"))
        if not ctx.print_only
        else bool(large_outputs.get("hap2_large_fa") or ctx.hap2_prefix in ("hap2", "maternal"))
    )

    run_dir = (
        ctx.tracker.start(
            "microchromosome_combine", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        if ctx.tracker
        else ctx.workdir / "microchromosome_combine" / "untracked"
    )

    def _combine_hap(hap_token: str) -> None:
        large_fa = large_outputs.get(f"{hap_token}_large_fa") or str(
            second_shot_dir / f"{ctx.tol_id}.{hap_token}.large.fa"
        )
        large_chr = large_outputs.get(f"{hap_token}_large_chr") or str(
            second_shot_dir / f"{ctx.tol_id}.{hap_token}.large.chr_list.csv"
        )
        small_fa = small_outputs.get(f"{hap_token}_fa") or str(
            pta_micro_run_dir / f"{ctx.tol_id}_small.{hap_token}.curated.fa"
        )
        small_chr = small_outputs.get(f"{hap_token}_chr_list") or str(
            pta_micro_run_dir / f"{ctx.tol_id}_small.{hap_token}.chromosome.list.csv"
        )
        merged_fa = run_dir / f"{ctx.tol_id}.{hap_token}.fa"
        merged_chr = run_dir / f"{ctx.tol_id}.{hap_token}.chromosome.list.csv"

        merge_cmd = (
            f"{_COMBINE_CURATED_MICROS_SCRIPT} "
            f"-l {large_fa} -s {small_fa} -o {merged_fa} "
            f"--large-chr {large_chr} --small-chr {small_chr} "
            f"--chr-output {merged_chr}"
        )
        _run(merge_cmd, ctx.print_only)

    try:
        _combine_hap("hap1")
        if has_hap2:
            _combine_hap("hap2")
        if ctx.tracker:
            outputs = collect_outputs(_OUTPUT_SPECS, run_dir, ctx.tol_id)
            ctx.tracker.finish(
                "microchromosome_combine",
                run_dir,
                "success",
                outputs=outputs or None,
                untracked=ctx.untracked,
            )
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish(
                "microchromosome_combine", run_dir, "failed", untracked=ctx.untracked
            )
        raise

    print_done(f"Microchromosome combine complete. Final merged FASTAs in: {run_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("microchromosome-combine", cls=GritCommand)
@click.pass_context
def microchromosome_combine_cmd(ctx):
    """Run microchromosome second-shot curation combine (post)."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_microchromosome_combine(curation_ctx)
    except Exception:
        log.exception("microchromosome-combine failed")
        raise SystemExit(1)
