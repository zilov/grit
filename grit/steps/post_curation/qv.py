"""Step: submit QV and k-mer completeness analysis via bsub."""

from __future__ import annotations

import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run
from grit.utils.modules import module_cmd
from grit.utils.output import print_done, print_step_header

log = logging.getLogger(__name__)

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
    Next step hint: ``validate_curated_files(ctx)``
    """
    log.info("qv | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "QV analysis")

    run_dir = ctx.tracker.start("qv", ctx.ticket_id, ctx.tol_id, invalidated=ctx.invalidated) if ctx.tracker else None

    cmd = f"{module_cmd('GRIT')} && cd {ctx.workdir} && kmer_completeness.bash {ctx.tol_id} {ctx.release_version}"
    _run(cmd, ctx.print_only)

    if ctx.tracker and run_dir:
        outputs = None if ctx.print_only else (_find_qv_outputs(ctx) or None)
        ctx.tracker.finish("qv", run_dir, "success", outputs=outputs)

    print_done("QV analysis done")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("qv", cls=GritCommand)
@click.pass_context
def qv_cmd(ctx):
    """Submit QV and k-mer completeness analysis via bsub."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_qv(curation_ctx)
    except Exception:
        log.exception("qv failed")
        raise SystemExit(1)
