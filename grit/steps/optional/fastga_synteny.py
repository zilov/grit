"""Run a circos-style synteny plot from an existing FastGA PAF alignment."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _state_update_epilogue,
    _submit_bsub,
    build_bsub_opts,
    find_latest_dir,
    write_fake_outputs,
)
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Path to the bundled plotting script
_FASTGA_SYNTENY_SCRIPT = _SCRIPTS_DIR / "fastga_synteny_format_and_plot.py"

DEFAULT_MIN_ALIGN_LEN = 10_000

# Downloadable outputs, picked up by the bsub -Ep epilogue (grit _state-update)
# and surfaced as an scp tip in `grit status` — see build_scp_tip().
_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("png", "*.png", []),
    ("alignment_summary", "*.alignment_summary.tsv", []),
]


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_fastga_synteny(ctx: CurationContext, min_align_len: int = DEFAULT_MIN_ALIGN_LEN) -> None:
    """
    Plots a circos-style synteny diagram from an existing FastGA PAF alignment.

    Steps:
        1. Find the FastGA PAF (latest 'fastga' run — same lookup as rename-and-orient).
        2. Submit a bsub job that runs fastga_synteny_format_and_plot.py via
           `uv run --script`, dropping alignment blocks shorter than
           *min_align_len* bp.

    Prints:
        Step header, bsub command.
    """
    log.info("fastga-synteny | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run FastGA synteny plot")

    if ctx.dry_run:
        run_dir = ctx.tracker.start(
            "fastga_synteny", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        outputs = write_fake_outputs("fastga_synteny", run_dir, ctx.tol_id)
        ctx.tracker.finish("fastga_synteny", run_dir, "success", outputs=outputs)
        print_done(f"[dry-run] FastGA synteny plot → {outputs.get('png', run_dir)}")
        return

    # --- find FastGA PAF ---
    fastga_dir = find_latest_dir(ctx, "fastga")
    paf_matches = glob.glob(str(fastga_dir / "*FastGA.paf"))
    if not paf_matches:
        raise FileNotFoundError(
            f"No FastGA PAF found in {fastga_dir}\nRun 'grit fastga -t {ctx.ticket_id}' first."
        )
    paf_file = Path(sorted(paf_matches)[-1])
    log.info("FastGA PAF: %s", paf_file)

    # --- submit synteny plot job ---
    # Each run gets its own run_dir so multiple fastga-synteny runs don't overwrite each other
    run_dir = (
        ctx.tracker.start("fastga_synteny", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / "fastga_synteny" / "untracked"
    )
    inner_cmd = (
        f"uv run --script {_FASTGA_SYNTENY_SCRIPT} "
        f"-paf {paf_file} -min-len {min_align_len} -p {run_dir}"
    )
    bsub_opts = build_bsub_opts(
        cores=4,
        memory_mb=16000,
        output="o_fastga_synt",
        run_dir=run_dir,
    )
    epilogue = _state_update_epilogue(ctx.workdir, "fastga_synteny", run_dir) if run_dir else None
    job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
    if ctx.tracker and run_dir and job_id:
        ctx.tracker.record_job("fastga_synteny", run_dir, job_id)

    print_done("FastGA synteny submitted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("fastga-synteny", cls=GritCommand)
@click.option(
    "--min-align-len",
    default=DEFAULT_MIN_ALIGN_LEN,
    type=int,
    show_default=True,
    help="Minimum alignment block length (bp) to include in the plot.",
)
@click.pass_context
def fastga_synteny_cmd(ctx, min_align_len):
    """Plot a circos-style synteny diagram from an existing FastGA PAF alignment."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_fastga_synteny(curation_ctx, min_align_len=min_align_len)
    except Exception:
        log.exception("fastga-synteny failed")
        raise SystemExit(1)
