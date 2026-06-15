"""Step: convert curated AGP + original.fa into a curated FASTA via pretext-to-asm."""

from __future__ import annotations

import glob
import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run
from grit.utils.modules import module_cmd
from grit.utils.output import print_done, print_next_step, print_step_header

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


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

    # Check for existing successful run; re-run if AGP is newer than curated FASTA
    if not ctx.print_only and ctx.tracker:
        prev_dir = ctx.tracker.latest_run_dir("pretext_to_asm")
        curated_fas = list(prev_dir.glob(f"{ctx.tol_id}*.curated.fa")) if prev_dir else []
        if curated_fas:
            agp_files = glob.glob(str(ctx.workdir / f"{ctx.tol_id}*.pretext.agp_1"))
            if not agp_files:
                agp_files = glob.glob(str(ctx.workdir / f"{ctx.tol_id}*.agp*"))
            curated_mtime = min(f.stat().st_mtime for f in curated_fas)
            agp_newer = agp_files and max(
                Path(f).stat().st_mtime for f in agp_files
            ) > curated_mtime
            if agp_newer:
                log.info("AGP is newer than curated FASTA — re-running pretext_to_asm")
            else:
                log.info("Curated FASTA already exists — skipping: %s", prev_dir)
                print_done(f"Already done → {prev_dir}")
                return

    # Start tracking
    run_dir = ctx.tracker.start("pretext_to_asm", ctx.ticket_id, ctx.tol_id) if ctx.tracker else ctx.workdir / "pretext_to_asm" / "untracked"
    out_fa = run_dir / f"{ctx.tol_id}.fa"
    original_fa = ctx.workdir / "original.fa"

    if not ctx.print_only and not original_fa.exists():
        if ctx.tracker:
            ctx.tracker.finish("pretext_to_asm", run_dir, "failed")
        raise FileNotFoundError(
            f"original.fa not found at {original_fa}. Run setup_curation first."
        )

    # AGP is uploaded by the user to workdir
    agp_pattern = str(ctx.workdir / f"{ctx.tol_id}*.agp*")
    if ctx.print_only:
        agp_path = agp_pattern
        log.info("AGP (pattern): %s", agp_path)
        log.info("Output → %s", out_fa)
    else:
        agp_files = glob.glob(agp_pattern)
        if not agp_files:
            if ctx.tracker:
                ctx.tracker.finish("pretext_to_asm", run_dir, "failed")
            raise FileNotFoundError(
                f"No AGP file found at {agp_pattern}. Copy AGP from local machine first.\n"
                f"  scp ~/curations/work/{ctx.tol_id}/{ctx.tol_id}*.agp* "
                f"{ctx.farm_host}:{ctx.workdir}/"
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
            ctx.tracker.finish("pretext_to_asm", run_dir, "success")
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish("pretext_to_asm", run_dir, "failed")
        raise

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
