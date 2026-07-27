"""Step: run post-processing pipeline (contamination screen + submission prep)."""

from __future__ import annotations

import logging
import subprocess

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import require_workdir
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

_POST_PROC_CONF = "/software/grit/projects/contamination_screen/conf/contamination_screen.conf"
_MODULES_INIT = "/etc/profile.d/modules.sh"

# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_post_processing(ctx: CurationContext) -> None:
    """
    Runs the post-processing Snakemake pipeline for the curated assembly.

    Sources the contamination screen config, changes into the curated assembly
    directory, and runs ``post_process_rc {ticket_id}``.

    Streams stdout/stderr directly to the terminal.
    """
    log.info("post-processing | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Post-processing")

    require_workdir(ctx)

    run_dir = ctx.tracker.start("post_processing", ctx.ticket_id, ctx.tol_id, invalidated=ctx.invalidated) if ctx.tracker else None

    script_lines = [
        f". {_MODULES_INIT}",
        "module purge",
        f"source {_POST_PROC_CONF}",
        # contamination_screen.conf prepends tola_production venv to PATH,
        # but its python3 is not accessible; strip it so the conda snakemake is used instead
        r"export PATH=$(echo \"$PATH\" | tr ':' '\n' | grep -v 'tola_production/.venv' | tr '\n' ':' | sed 's/:$//')",
        "shopt -s expand_aliases",
        f"cd {ctx.assembly_curated_dir}",
        f"post_process_rc {ctx.ticket_id}",
    ]
    console.print("\n[yellow]Commands:[/yellow]")
    for line in script_lines:
        console.print(f"  [green]{line}[/green]")

    if not ctx.print_only:
        script = "\n".join(script_lines)
        try:
            subprocess.run(["bash"], input=script, text=True, check=True)
            if ctx.tracker and run_dir:
                ctx.tracker.finish("post_processing", run_dir, "success")
            from grit.core.registry import RegistryManager
            RegistryManager().mark_done(ctx.ticket_id)
        except subprocess.CalledProcessError:
            if ctx.tracker and run_dir:
                ctx.tracker.finish("post_processing", run_dir, "failed")
            raise

    print_done("Post-processing complete.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("post-processing", cls=GritCommand)
@click.pass_context
def post_processing_cmd(ctx):
    """Run post-processing pipeline (contamination screen + submission prep)."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_post_processing(curation_ctx)
    except Exception:
        log.exception("post-processing failed")
        raise SystemExit(1)


@click.command("pp", cls=GritCommand)
@click.pass_context
def pp_cmd(ctx):
    """Alias for post-processing."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_post_processing(curation_ctx)
    except Exception:
        log.exception("post-processing failed")
        raise SystemExit(1)
