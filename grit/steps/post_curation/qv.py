"""Step: run QV and k-mer completeness analysis (blocks until its MerquryFK job finishes)."""

from __future__ import annotations

import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run
from grit.utils.modules import module_cmd
from grit.utils.output import print_done, print_step_header

log = logging.getLogger(__name__)

_QV_OUTPUT_KEYS = ("qv", "completeness_stats")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_qv_outputs(ctx: CurationContext) -> dict[str, str]:
    """
    Check for the two files kmer_completeness.bash writes into
    ``{ctx.assembly_curated_dir}/merquryk/`` — always that dir regardless of
    the ``cd {ctx.workdir}`` the command runs from (the script locates its
    output dir from tol_id itself, not from cwd).
    """
    qv_dir = ctx.assembly_curated_dir / "merquryk"
    outputs: dict[str, str] = {}
    qv_file = qv_dir / f"{ctx.tol_id}.qv"
    if qv_file.exists():
        outputs["qv"] = str(qv_file)
    completeness_file = qv_dir / f"{ctx.tol_id}.completeness.stats"
    if completeness_file.exists():
        outputs["completeness_stats"] = str(completeness_file)
    return outputs


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_qv(ctx: CurationContext) -> None:
    """
    Runs QV and k-mer completeness analysis inline.

    Notebook source: ``pre_and_post_curation()`` — ``run_qv_analysis`` section.

    Steps:
        1. Build and run::

               . /etc/profile.d/modules.sh && module purge && module load grit
               cd {ctx.workdir} && kmer_completeness.bash {ctx.tol_id} {ctx.release_version}

    Prints:
        Step header, command, done message.
    Next step hint: ``finalize_for_qc(ctx)``
    """
    log.info("qv | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "QV analysis")

    if ctx.dry_run:
        run_dir = (
            ctx.tracker.start("qv", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
            if ctx.tracker
            else None
        )
        qv_dir = ctx.assembly_curated_dir / "merquryk"
        qv_dir.mkdir(parents=True, exist_ok=True)
        (qv_dir / f"{ctx.tol_id}.qv").write_text("fake\n")
        (qv_dir / f"{ctx.tol_id}.completeness.stats").write_text("fake\n")
        if ctx.tracker and run_dir:
            outputs = _find_qv_outputs(ctx) or None
            ctx.tracker.finish("qv", run_dir, "success", outputs=outputs, untracked=ctx.untracked)
        print_done(f"[dry-run] QV analysis → {qv_dir}")
        return

    run_dir = (
        ctx.tracker.start("qv", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else None
    )

    cmd = (
        f"{module_cmd('GRIT')} && cd {ctx.workdir} && "
        f"kmer_completeness.bash {ctx.tol_id} {ctx.release_version}"
    )
    try:
        # the wrapper blocks on its MerquryFK job (bsub -K) but exits 0 even when it fails
        _run(cmd, ctx.print_only)
        outputs = None if ctx.print_only else _find_qv_outputs(ctx)
        if outputs is not None and set(outputs) != set(_QV_OUTPUT_KEYS):
            raise RuntimeError(
                "kmer_completeness.bash finished without writing "
                f"{ctx.tol_id}.qv and {ctx.tol_id}.completeness.stats to "
                f"{ctx.assembly_curated_dir / 'merquryk'}; see merqury.out there"
            )
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("qv", run_dir, "failed", untracked=ctx.untracked)
        raise

    if ctx.tracker and run_dir:
        ctx.tracker.finish("qv", run_dir, "success", outputs=outputs, untracked=ctx.untracked)

    print_done("QV analysis done")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("qv", cls=GritCommand)
@click.pass_context
def qv_cmd(ctx):
    """Run QV and k-mer completeness analysis; waits for the MerquryFK job."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_qv(curation_ctx)
    except Exception:
        log.exception("qv failed")
        raise SystemExit(1)
