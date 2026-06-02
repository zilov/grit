"""Step: convert curated AGP + original.fa into a curated FASTA via pretext-to-asm."""

from __future__ import annotations

import glob
import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run
from grit.utils.modules import module_cmd
from grit.utils.output import print_done, print_info, print_next_step, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_pretext_to_asm(ctx: CurationContext) -> None:
    """
    Converts the curated AGP + original.fa into a curated FASTA via pretext-to-asm.

    Notebook source: ``pre_and_post_curation()`` — ``generate_fasta_from_agp`` section.

    Steps:
        1. Verify ``{ctx.workdir}/original.fa`` exists (or warn in print_only mode).
        2. Verify ``{ctx.workdir}/{ctx.tol_id}*.agp*`` glob matches at least one file.
        3. Build and execute the command::

               module load grit && pretext-to-asm \
                   -a {ctx.workdir}/original.fa \
                   -p {agp_path} \
                   -o {ctx.workdir}/{ctx.tol_id}.fa

    Prints:
        Step header, AGP path found, command executed.
    Next step hint: ``ensure_haplotig_files(ctx)``
    """
    log.info("pretext-to-asm | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Pretext to ASM")

    original_fa = ctx.workdir / "original.fa"
    out_fa = ctx.workdir / f"{ctx.tol_id}.fa"

    if not ctx.print_only and not original_fa.exists():
        raise FileNotFoundError(
            f"original.fa not found at {original_fa}. Run setup_curation first."
        )

    agp_pattern = str(ctx.workdir / f"{ctx.tol_id}*.agp*")
    if ctx.print_only:
        agp_path = agp_pattern
        print_info("AGP (pattern)", agp_path)
    else:
        agp_files = glob.glob(agp_pattern)
        if not agp_files:
            raise FileNotFoundError(
                f"No AGP file found at {agp_pattern}. Copy AGP from local machine first.\n"
                f"  scp ~/curations/{ctx.tol_id}/{ctx.tol_id}*.agp* "
                f"{ctx.farm_host}:{ctx.workdir}/"
            )
        agp_path = agp_files[0]
        print_info("AGP", agp_path)

    cmd = (
        f"{module_cmd('PRETEXT_TO_ASM')} && pretext-to-asm"
        f" -a {original_fa}"
        f" -p {agp_path}"
        f" -o {out_fa}"
    )
    _run(cmd, ctx.print_only)
    print_done(f"Curated FASTA → {out_fa}")
    print_next_step("ensure_haplotig_files(ctx)")


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
