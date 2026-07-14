"""Step: submit QV and k-mer completeness analysis via bsub."""

from __future__ import annotations

import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _state_update_epilogue, _submit_bsub, build_bsub_opts
from grit.utils.output import print_done, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_qv(ctx: CurationContext) -> None:
    """
    Submits QV and k-mer completeness analysis via bsub.

    Notebook source: ``pre_and_post_curation()`` — ``run_qv_analysis`` section.

    Steps:
        1. Build and submit::

               cd {ctx.workdir} && kmer_completeness.bash {ctx.tol_id} {ctx.release_version}

    Prints:
        Step header, bsub command, job ID.
    Next step hint: ``validate_curated_files(ctx)``
    """
    log.info("qv | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "QV analysis")

    run_dir = ctx.tracker.start("qv", ctx.ticket_id, ctx.tol_id, invalidated=ctx.invalidated) if ctx.tracker else None

    inner_cmd = f"cd {ctx.workdir} && kmer_completeness.bash {ctx.tol_id} {ctx.release_version}"
    bsub_opts = build_bsub_opts(memory_mb=8000, output=str(ctx.workdir / "qv.log"))
    epilogue = _state_update_epilogue(ctx.workdir, "qv", run_dir) if run_dir else None
    job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)

    if ctx.tracker and run_dir and job_id:
        ctx.tracker.record_job("qv", run_dir, job_id)

    print_done("QV job submitted")


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
