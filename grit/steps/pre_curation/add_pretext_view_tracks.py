"""Optional tracks for pretext map: bedgraph, gap, and telomere tracks."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _find_pretext_map_in_workdir, _run
from grit.utils.modules import module_cmd
from grit.utils.output import (
    print_done,
    print_info,
    print_next_step,
    print_step_header,
    print_warning,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HAP_BEDGRAPH_SCRIPT = "/nfs/users/nfs_d/dz11/hap_bedgraph.py"


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def add_bedgraph_track(ctx: CurationContext, bedgraph_path: str) -> None:
    """
    Adds an arbitrary bedgraph track to the pretext map.

    Steps:
        1. Verify ``bedgraph_path`` exists (skipped in print_only mode).
        2. Derive a track name from the bedgraph filename stem.
        3. Build and run::

               module purge && module load pretextgraph/0.0.7--h4ac6f70_0 && \\
               cat {bedgraph_path} | \\
               PretextGraph -i {pretext_map_path} -n {track_name}

    Prints:
        Step header, track name, command executed.
    """
    log.info("add-bedgraph-track | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Add bedgraph track")

    bg_path = Path(bedgraph_path)
    if not ctx.print_only and not bg_path.exists():
        raise FileNotFoundError(f"Bedgraph file not found: {bg_path}")

    track_name = bg_path.stem
    print_info("Bedgraph file", str(bg_path))
    print_info("Track name", track_name)

    pretext_map = _find_pretext_map_in_workdir(ctx)
    ml = module_cmd("PRETEXTGRAPH")

    cmd = f"{ml} && cat {bg_path} | PretextGraph -i {pretext_map} -n {track_name}"
    _run(cmd, ctx.print_only)
    print_done(f"Bedgraph track '{track_name}' added.")


def add_gap_track(ctx: CurationContext) -> None:
    """
    Adds a gap track to the pretext map using hap_bedgraph.py + PretextGraph.

    Prerequisite: the pretext map has already been copied to ``ctx.workdir``.

    Steps:
        1. Locate the HR pretext map in workdir.
        2. Build and run::

               module purge && module load pretextgraph/0.0.7--h4ac6f70_0 && \\
               python3 /nfs/users/nfs_d/dz11/hap_bedgraph.py \\
                   {ctx.workdir}/original.fa | \\
               PretextGraph -i {pretext_map_path} -n gap

    Prints:
        Step header, command executed.
    Next step hint: ``add_telo_track(ctx)``
    """
    log.info("add-gap-track | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Add gap track")

    pretext_map = _find_pretext_map_in_workdir(ctx)
    original_fa = ctx.workdir / "original.fa"
    ml = module_cmd("PRETEXTGRAPH")

    cmd = (
        f"{ml} && "
        f"python3 {_HAP_BEDGRAPH_SCRIPT} {original_fa} | "
        f"PretextGraph -i {pretext_map} -n gap"
    )
    _run(cmd, ctx.print_only)
    print_done("Gap track added.")
    print_next_step("add_telo_track(ctx)")


def add_telo_track(ctx: CurationContext) -> None:
    """
    Adds a telomere track to the pretext map if telo_*.bed.gz is available.

    Steps:
        1. Glob for telomere BED file from TreeVAL output.
        2. If not found: print warning and return.
        3. Build and run::

               module purge && module load pretextgraph/0.0.7--h4ac6f70_0 && \\
               zcat {telo_bed_gz} | \\
               awk '{ print $1\\t$2\\t$3\\t($3-$2) }' | \\
               PretextGraph -i {pretext_map_path} -n telomere

    Prints:
        Step header, telo file found (or warning if absent), command executed.
    """
    log.info("add-telo-track | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Add telo track")

    telo_pattern = str(
        ctx.assembly_draft_dir / "treeval" / "*" / "tv_output1" / "treeval_upload" / "telo_*.bed.gz"
    )

    if ctx.print_only:
        print_info("Telo pattern", telo_pattern)
    else:
        telo_files = glob.glob(telo_pattern)
        if not telo_files:
            print_warning(f"No telo BED file found at: {telo_pattern} — skipping telo track.")
            return
        telo_bed_gz = Path(sorted(telo_files)[-1])
        print_info("Telo file", str(telo_bed_gz))

    pretext_map = _find_pretext_map_in_workdir(ctx)
    ml = module_cmd("PRETEXTGRAPH")

    telo_arg = telo_pattern if ctx.print_only else str(telo_bed_gz)
    cmd = (
        f"{ml} && "
        f"zcat {telo_arg} | "
        r"awk '{ print $1\"\t\"$2\"\t\"$3\"\t\"($3-$2) }' | "
        f"PretextGraph -i {pretext_map} -n telomere"
    )
    _run(cmd, ctx.print_only)
    print_done("Telo track added.")


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("add-bedgraph-track", cls=GritCommand)
@click.option(
    "--file",
    "bedgraph_path",
    required=True,
    type=click.Path(exists=True),
    help="Path to bedgraph file",
)
@click.pass_context
def add_bedgraph_track_cmd(ctx, bedgraph_path):
    """Add bedgraph track to pretext map."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        add_bedgraph_track(curation_ctx, bedgraph_path)
    except Exception:
        log.exception("add-bedgraph-track failed")
        raise SystemExit(1)


@click.command("add-gap-track", cls=GritCommand)
@click.pass_context
def add_gap_track_cmd(ctx):
    """Add gap track to pretext map."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        add_gap_track(curation_ctx)
    except Exception:
        log.exception("add-gap-track failed")
        raise SystemExit(1)


@click.command("add-telo-track", cls=GritCommand)
@click.pass_context
def add_telo_track_cmd(ctx):
    """Add telomere track to pretext map."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        add_telo_track(curation_ctx)
    except Exception:
        log.exception("add-telo-track failed")
        raise SystemExit(1)
