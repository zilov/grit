"""Run FastGA dot-plot comparison."""

import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _state_update_epilogue,
    _submit_bsub,
    build_bsub_opts,
    find_canonical_fa,
    find_reheadered_reference,
)
from grit.utils.modules import module_cmd
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_PAF_TOP_TARGETS_SCRIPT = _REPO_ROOT / "scripts" / "paf_top_targets_add_top_longest.py"

# Downloadable outputs, picked up by the bsub -Ep epilogue (grit _state-update)
# and surfaced as an scp tip in `grit status` — see build_scp_tip().
_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("idx", "*.idx", []),
    ("paf", "*FastGA.paf", []),
    ("top_targets_summary", "*.top_targets_summary.txt", []),
]


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_fastga(ctx: CurationContext, reference_path: str | None = None) -> None:
    """
    Runs a FastGA dot-plot comparison of the curated assembly vs. a reference.

    Notebook source: ``run_fastga()`` and ``scp_fastga()`` functions.

    Steps:
        1. Determine the primary curated hap1 FASTA in ``ctx.workdir``.
        2. If reference is gzipped and not yet decompressed/reheadered::

               ml grit && gunzip {ref} && \
               reheader {ref.replace('.gz', '')} > {ref_reheader}

        3. Build bsub command::

               bsub -G team135 -n 8 -e e_fastga -o o_fastga \
                   -M 24000 -R'...' \
                   /software/grit/projects/vgp_curation_scripts/FastGA_dot_dgenies.sh \
                   {ref_reheader} {hap1_fa} {run_prefix} {outdir}

        4. Once the PAF is written, run ``paf_top_targets_add_top_longest.py``
           over it (all query contigs, ``--top_longest``) and redirect its
           report to ``{run_prefix}.top_targets_summary.txt`` in ``run_dir``.
        5. Print command and submit via subprocess.

    Downloadable outputs (idx/paf) and the top-targets summary are surfaced
    later — as an scp tip / a ``less`` tip respectively — in ``grit status``,
    once the job's bsub epilogue records them.

    Prints:
        Step header, bsub command.
    """
    log.info("fastga | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run FastGA")

    # --- find canonical hap1 FASTA (rename_and_orient output preferred) ---
    hap1_fa = find_canonical_fa(ctx, ctx.hap1_prefix)
    log.info("Curated hap1 FASTA: %s", hap1_fa)

    from grit.steps.pre_curation.find_reference import reheader_reference

    # --- find reference ---
    if reference_path:
        ref_path = Path(reference_path)
        if not ctx.print_only and not ref_path.exists():
            raise FileNotFoundError(f"Reference not found: {ref_path}")
        log.info("Reference FASTA (explicit): %s", ref_path)
        ref_reheader = reheader_reference(ctx, ref_path)
    else:
        ref_reheader = find_reheadered_reference(ctx)
        log.info("Reference FASTA: %s", ref_reheader)

    ref_prefix = ref_reheader.stem.split(".")[0].removesuffix("_reheader")
    assembly_prefix = hap1_fa.stem.split(".")[0]
    run_prefix = f"{ref_prefix}_vs_{assembly_prefix}"

    # --- submit bsub job ---
    # Each run gets its own tracker run_dir so multiple fastga runs don't overwrite each other
    run_dir = ctx.tracker.start("fastga", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked) if ctx.tracker else ctx.workdir / "fastga" / "untracked"
    fastga_script = "/software/grit/projects/vgp_curation_scripts/FastGA_dot_dgenies.sh"
    summary_file = run_dir / f"{run_prefix}.top_targets_summary.txt"
    inner_cmd = (
        f"cd {run_dir} && "
        f"{module_cmd('GRIT')} && "
        f"{fastga_script} {ref_reheader} {hap1_fa} {run_prefix} {run_dir} && "
        f"paf_file=$(ls {run_dir}/*FastGA.paf | head -n 1) && "
        f'python3 {_PAF_TOP_TARGETS_SCRIPT} "$paf_file" --top_longest > {summary_file}'
    )
    bsub_opts = build_bsub_opts(
        group="team135",
        cores=8,
        memory_mb=24000,
        output="o_fastga",
        error="e_fastga",
        run_dir=run_dir,
    )
    epilogue = _state_update_epilogue(ctx.workdir, "fastga", run_dir) if run_dir else None
    try:
        job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
        if ctx.tracker and run_dir and job_id:
            ctx.tracker.record_job("fastga", run_dir, job_id)
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("fastga", run_dir, "failed")
        raise

    print_done("FastGA submitted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("fastga", cls=GritCommand)
@click.option("--reference", "-r", default=None, help="Path to reference FASTA (overrides auto-search in workdir/reference/).")
@click.pass_context
def fastga_cmd(ctx, reference):
    """Run FastGA dot-plot comparison of curated assembly vs reference."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_fastga(curation_ctx, reference_path=reference)
    except Exception:
        log.exception("fastga failed")
        raise SystemExit(1)
