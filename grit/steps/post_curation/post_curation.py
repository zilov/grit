"""Post-curation steps: after manual curation in PretextView.

Each step lives in its own module; this file re-exports them for backward compatibility.
"""

from __future__ import annotations

import rich_click as click

from grit.core.base_command import GritCommand
from grit.steps.post_curation.finalize_qc import finalize_for_qc
from grit.steps.post_curation.haplotig_files import run_haplotig_files
from grit.steps.post_curation.hic_remapping import run_hic_remapping
from grit.steps.post_curation.pretext_to_asm import run_pretext_to_asm
from grit.steps.post_curation.qv import run_qv
from grit.steps.post_curation.validate_files import run_validate_files

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


__all__ = [
    "run_pretext_to_asm",
    "run_haplotig_files",
    "run_hic_remapping",
    "run_qv",
    "run_validate_files",
    "finalize_for_qc",
    "run_post_curation",
]

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_post_curation(ctx):
    """Run all post-curation steps in sequence."""
    run_pretext_to_asm(ctx)
    run_haplotig_files(ctx)
    run_hic_remapping(ctx)
    run_qv(ctx)
    run_validate_files(ctx)
    finalize_for_qc(ctx)


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("post-curation", cls=GritCommand)
@click.pass_context
def post_curation_cmd(ctx):
    """Run all post-curation steps."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    run_post_curation(curation_ctx)
