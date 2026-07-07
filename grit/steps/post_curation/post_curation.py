"""Post-curation steps: after manual curation in PretextView.

Each step lives in its own module; this file re-exports them for backward compatibility.
"""

from __future__ import annotations

import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.steps.post_curation.haplotig_files import run_haplotig_files
from grit.steps.post_curation.hic_remapping import run_hic_remapping
from grit.steps.post_curation.pretext_to_asm import run_pretext_to_asm

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


__all__ = [
    "run_pretext_to_asm",
    "run_haplotig_files",
    "run_hic_remapping",
    "run_post_curation",
]

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_post_curation(ctx, *, run_hap2: bool = False):
    """Run all post-curation steps in sequence."""
    log.info("post-curation | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    run_pretext_to_asm(ctx)
    run_haplotig_files(ctx)
    run_hic_remapping(ctx, run_hap2=run_hap2)


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("post-curation", cls=GritCommand)
@click.option("--hap2", "run_hap2", is_flag=True, default=False,
              help="Also submit HiC remapping for hap2.")
@click.pass_context
def post_curation_cmd(ctx, run_hap2):
    """Run all post-curation steps."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_post_curation(curation_ctx, run_hap2=run_hap2)
    except Exception:
        log.exception("post-curation failed")
        raise SystemExit(1)
