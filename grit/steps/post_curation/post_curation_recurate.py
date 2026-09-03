"""Composite step: pretext-to-asm-recurate followed by hic-remapping, for one haplotype."""

from __future__ import annotations

import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.steps.post_curation.hic_remapping import run_hic_remapping
from grit.steps.post_curation.pretext_to_asm_recurate import run_pretext_to_asm_recurate

log = logging.getLogger(__name__)


def run_post_curation_recurate(ctx, *, run_hap2: bool = False) -> None:
    """
    Run pretext-to-asm-recurate followed by hic-remapping for one haplotype.

    Recurates hap1 by default; pass ``run_hap2=True`` to recurate hap2
    instead — not in addition, unlike ``run_post_curation``'s ``--hap2``.
    """
    log.info("post-curation-recurate | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    hap_prefix = ctx.hap2_prefix if run_hap2 else ctx.hap1_prefix
    step_name = "pretext_to_asm_recurate_hap2" if run_hap2 else "pretext_to_asm_recurate"
    run_pretext_to_asm_recurate(ctx, hap_prefix, step_name)
    run_hic_remapping(ctx, run_hap1=not run_hap2, run_hap2=run_hap2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("post-curation-recurate", cls=GritCommand)
@click.option(
    "--hap2",
    "run_hap2",
    is_flag=True,
    default=False,
    help="Recurate hap2 instead of hap1.",
)
@click.pass_context
def post_curation_recurate_cmd(ctx, run_hap2):
    """Run pretext-to-asm-recurate + hic-remapping for one haplotype."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_post_curation_recurate(curation_ctx, run_hap2=run_hap2)
    except Exception:
        log.exception("post-curation-recurate failed")
        raise SystemExit(1)
