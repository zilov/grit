"""Step: convert curated AGP + original.fa into a curated FASTA via pretext-to-asm."""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, agp_newer_than_curated_fa, collect_outputs
from grit.utils.modules import module_cmd
from grit.utils.output import print_done, print_step_header

log = logging.getLogger(__name__)

_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("hap1_fa", "{tol_id}.{hap1}.*.curated.fa", ["all_haplotigs", "additional_haplotigs"]),
    ("hap2_fa", "{tol_id}.{hap2}.*.curated.fa", ["all_haplotigs", "additional_haplotigs"]),
    ("hap1_haplotigs", "{tol_id}.{hap1}.*.all_haplotigs.curated.fa", []),
    ("hap2_haplotigs", "{tol_id}.{hap2}.*.all_haplotigs.curated.fa", []),
    ("hap1_chr_list", "{tol_id}.{hap1}.*.chromosome.list.csv", []),
    ("hap2_chr_list", "{tol_id}.{hap2}.*.chromosome.list.csv", []),
    # fallback: primary assembly naming (tried only if hap1_fa not found above)
    (
        "hap1_fa",
        "{tol_id}.*.primary.curated.fa",
        ["hap1", "hap2", "all_haplotigs", "additional_haplotigs"],
    ),
]

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def _run_pretext_to_asm_core(
    ctx: CurationContext,
    step_name: str,
    original_fa: Path,
    original_fa_missing_msg: str,
    agp_search_dir: Path,
    out_fa_name: str,
    output_specs: list[tuple[str, str, list[str]]],
) -> Path:
    """
    Runs pretext-to-asm for one (original_fa, agp) pair under a tracked step.

    Looks for ``{tol_id}*.agp*`` in *agp_search_dir*, runs pretext-to-asm, and
    records outputs via *output_specs* under *step_name*. Returns the run_dir
    (which may be a prior run's dir if the step was skipped as already done).

    Shared by ``run_pretext_to_asm`` (main assembly) and
    ``run_microchromosome_combine`` (micro-assembly small chromosomes).
    """
    # Check for existing successful run; re-run if AGP is newer than curated FASTA
    if not ctx.print_only and ctx.tracker:
        prev_dir = ctx.tracker.latest_run_dir(step_name)
        if prev_dir and list(prev_dir.glob(f"{ctx.tol_id}*.curated.fa")):
            if agp_newer_than_curated_fa(agp_search_dir, ctx.tol_id, prev_dir):
                log.info("AGP is newer than curated FASTA — re-running %s", step_name)
            else:
                log.info("Curated FASTA already exists — skipping: %s", prev_dir)
                print_done(f"Already done → {prev_dir}")
                return prev_dir

    # Start tracking
    run_dir = (
        ctx.tracker.start(step_name, ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / step_name / "untracked"
    )
    out_fa = run_dir / out_fa_name

    if not ctx.print_only and not original_fa.exists():
        if ctx.tracker:
            ctx.tracker.finish(step_name, run_dir, "failed")
        raise FileNotFoundError(original_fa_missing_msg)

    # AGP is uploaded by the user to agp_search_dir
    agp_pattern = str(agp_search_dir / f"{ctx.tol_id}*.agp*")
    if ctx.print_only:
        agp_path = agp_pattern
        log.info("AGP (pattern): %s", agp_path)
        log.info("Output → %s", out_fa)
    else:
        agp_files = glob.glob(agp_pattern)
        if not agp_files:
            if ctx.tracker:
                ctx.tracker.finish(step_name, run_dir, "failed")
            raise FileNotFoundError(
                f"No AGP file found at {agp_pattern}. Copy AGP from local machine first.\n"
                f"  scp ~/curations/work/{ctx.tol_id}/{ctx.tol_id}*.agp* "
                f"{ctx.farm_host}:{agp_search_dir}/"
            )
        agp_path = agp_files[0]
        log.info("AGP: %s", agp_path)

    cmd = (
        f"{module_cmd('PRETEXT_TO_ASM')} && pretext-to-asm"
        f" -a {original_fa}"
        f" -p {agp_path}"
        f" -o {out_fa}"
    )
    try:
        _run(cmd, ctx.print_only, capture=False)
        if ctx.tracker:
            outputs = collect_outputs(
                output_specs, run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
            )
            ctx.tracker.finish(step_name, run_dir, "success", outputs=outputs or None)
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish(step_name, run_dir, "failed")
        raise

    print_done(f"Curated FASTA → {out_fa}")
    return run_dir


def run_pretext_to_asm(ctx: CurationContext) -> None:
    """
    Converts the curated AGP + original.fa into a curated FASTA via pretext-to-asm.

    Output FASTA goes into a timestamped run directory:
    ``{workdir}/pretext_to_asm/<timestamp>/{tol_id}.fa``

    Notebook source: ``pre_and_post_curation()`` — ``generate_fasta_from_agp`` section.

    Steps:
        1. Verify ``{ctx.workdir}/original.fa`` exists (or warn in print_only mode).
        2. Verify ``{ctx.workdir}/{ctx.tol_id}*.agp*`` glob matches at least one file.
        3. Build and execute::

               module load grit && pretext-to-asm \
                   -a {workdir}/original.fa \
                   -p {agp_path} \
                   -o {run_dir}/{tol_id}.fa

    Prints:
        Step header, AGP path found, command executed.
    Next step hint: ``ensure_haplotig_files(ctx)``
    """
    log.info("pretext-to-asm | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Pretext to ASM")

    original_fa = ctx.workdir / "original.fa"
    _run_pretext_to_asm_core(
        ctx,
        "pretext_to_asm",
        original_fa,
        f"original.fa not found at {original_fa}. Run setup_curation first.",
        ctx.workdir,
        f"{ctx.tol_id}.fa",
        _OUTPUT_SPECS,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("pretext-to-asm", cls=GritCommand)
@click.pass_context
def pretext_to_asm_cmd(ctx):
    """Convert curated AGP + original.fa into curated FASTA via pretext-to-asm."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_pretext_to_asm(curation_ctx)
    except Exception:
        log.exception("pretext-to-asm failed")
        raise SystemExit(1)
