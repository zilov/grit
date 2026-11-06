"""Step: run post-processing pipeline (contamination screen + submission prep)."""

from __future__ import annotations

import logging
import subprocess

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import is_single_hap, require_workdir
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

_POST_PROC_CONF = "/software/grit/projects/contamination_screen/conf/contamination_screen.conf"


def _refuse_hap2_chr_list_against_jira(ctx: CurationContext) -> None:
    """Raise when Jira's chromosome list count disagrees with hap2's curated list."""
    if is_single_hap(ctx) or ctx.chromosome_list_files not in (1, 2):
        return
    hap2 = ctx.assembly_curated_dir / (
        f"{ctx.tol_id}.{ctx.hap2_prefix}.{ctx.release_version}.primary.chromosome.list.csv"
    )
    if not hap2.exists():
        return
    if ctx.chromosome_list_files == 2 and hap2.stat().st_size == 0:
        raise click.UsageError(
            f"Jira 'Chromosome list files' is 2, but {hap2.name} is empty, so hap2 would be "
            "published at scaffold level. To publish hap2 at chromosome level, refill it:\n"
            f"  grit finalize-qc -t {ctx.ticket_id} --hap2-level chromosome\n"
            "or set 'Chromosome list files' to 1 if hap2 really is scaffold level."
        )
    if ctx.chromosome_list_files == 1 and hap2.stat().st_size > 0:
        raise click.UsageError(
            f"Jira 'Chromosome list files' is 1, but {hap2.name} is not empty, so hap2 would be "
            "published at chromosome level. To publish hap2 as scaffold, empty it:\n"
            f"  truncate -s 0 {hap2}\n"
            "or set 'Chromosome list files' to 2 if hap2 really is chromosome level."
        )


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
    _refuse_hap2_chr_list_against_jira(ctx)

    run_dir = (
        ctx.tracker.start("post_processing", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else None
    )

    if ctx.dry_run:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("post_processing", run_dir, "success", untracked=ctx.untracked)
        print_done("[dry-run] Post-processing complete.")
        return

    script_lines = [
        f"source {_POST_PROC_CONF}",
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
                ctx.tracker.finish("post_processing", run_dir, "success", untracked=ctx.untracked)
            from grit.core.registry import RegistryManager

            RegistryManager().mark_done(ctx.ticket_id)
        except subprocess.CalledProcessError:
            if ctx.tracker and run_dir:
                ctx.tracker.finish("post_processing", run_dir, "failed", untracked=ctx.untracked)
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
    except click.UsageError:
        raise
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
    except click.UsageError:
        raise
    except Exception:
        log.exception("post-processing failed")
        raise SystemExit(1)
