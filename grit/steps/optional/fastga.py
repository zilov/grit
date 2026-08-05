"""Run FastGA dot-plot comparison."""

import glob
import logging
from pathlib import Path

import rich_click as click
from rich.table import Table

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _state_update_epilogue,
    _submit_bsub,
    build_bsub_opts,
    find_canonical_fa,
    find_latest_dir,
    find_reheadered_reference,
)
from grit.utils.modules import module_cmd
from grit.utils.output import (
    console,
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_PAF_TOP_TARGETS_SCRIPT = _REPO_ROOT / "scripts" / "paf_top_targets_add_top_longest.py"

# Downloadable outputs, picked up by the bsub -Ep epilogue (grit _state-update)
# and surfaced as an scp tip in `grit status` — see build_scp_tip().
_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("idx", "*.idx", []),
    ("paf", "*FastGA.paf", []),
    ("top_targets_summary", "*.top_targets_summary.txt", []),
]


def _parse_top_longest_table(summary_file: Path) -> list[tuple[str, str, str]]:
    """Extract the super/top_longest_ref_chr/len rows between the TOP_LONGEST_TABLE markers."""
    lines = summary_file.read_text().splitlines()
    try:
        start = lines.index("##TOP_LONGEST_TABLE##") + 2  # skip marker + header row
        end = lines.index("##END_TOP_LONGEST_TABLE##")
    except ValueError:
        return []
    return [tuple(line.split("\t")) for line in lines[start:end] if line.strip()]


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_fastga(ctx: CurationContext, reference_path: str | None = None) -> None:
    """Submits the FastGA dot-plot alignment (which also writes the top-targets summary)."""
    log.info("fastga | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run FastGA")

    # --- find canonical hap1 FASTA (rename_and_orient output preferred) ---
    hap1_fa = find_canonical_fa(ctx, ctx.hap1_prefix)
    log.info("Curated hap1 FASTA: %s", hap1_fa)

    from grit.steps.pre_curation.find_reference import reheader_reference

    # --- find reference ---
    if reference_path:
        ref_path = Path(reference_path)
        if not ctx.print_only and not ref_path.exists():
            raise FileNotFoundError(f"Reference not found: {ref_path}")
        log.info("Reference FASTA (explicit): %s", ref_path)
        ref_reheader = reheader_reference(ctx, ref_path)
    else:
        ref_reheader = find_reheadered_reference(ctx)
        log.info("Reference FASTA: %s", ref_reheader)

    ref_prefix = ref_reheader.stem.split(".")[0].removesuffix("_reheader")
    assembly_prefix = hap1_fa.stem.split(".")[0]
    run_prefix = f"{ref_prefix}_vs_{assembly_prefix}"

    # --- submit bsub job ---
    # Each run gets its own tracker run_dir so multiple fastga runs don't overwrite each other.
    run_dir = ctx.tracker.start("fastga", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked) if ctx.tracker else ctx.workdir / "fastga" / "untracked"
    fastga_script = _REPO_ROOT / "scripts" / "FastGA_dot_dgenies_stats.sh"

    inner_cmd = (
        f"cd {run_dir} && "
        f"{module_cmd('GRIT')} && "
        f"bash {fastga_script} {ref_reheader} {hap1_fa} {run_prefix} {run_dir} {_PAF_TOP_TARGETS_SCRIPT}"
    )
    bsub_opts = build_bsub_opts(
        group="team135",
        cores=8,
        memory_mb=ctx.bsub_ram or 24000,
        output="o_fastga",
        error="e_fastga",
        run_dir=run_dir,
    )
    epilogue = _state_update_epilogue(ctx.workdir, "fastga", run_dir) if run_dir else None

    try:
        job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
        if ctx.tracker and run_dir and job_id:
            ctx.tracker.record_job("fastga", run_dir, job_id)
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("fastga", run_dir, "failed")
        raise

    print_done("FastGA submitted.")


def run_fastga_stats(ctx: CurationContext) -> None:
    """Prints the per-query top-longest reference target table from the latest fastga run."""
    log.info("fastga-stats | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "FastGA top-longest targets")

    fastga_dir = find_latest_dir(ctx, "fastga")
    matches = glob.glob(str(fastga_dir / "*.top_targets_summary.txt"))
    if not matches:
        raise FileNotFoundError(
            f"No top_targets_summary found in {fastga_dir}\n"
            f"Run 'grit fastga -t {ctx.ticket_id}' first."
        )
    summary_file = Path(sorted(matches)[-1])

    rows = _parse_top_longest_table(summary_file)
    if not rows:
        log.warning("No TOP_LONGEST_TABLE section found in %s", summary_file)
        return

    table = Table(title="Top-longest reference target per query", header_style="bold cyan")
    table.add_column("super")
    table.add_column("top_longest_ref_chr")
    table.add_column("len", justify="right")
    for super_name, ref_chr, length in rows:
        table.add_row(super_name, ref_chr, f"{int(length):,}")
    console.print(table)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("fastga", cls=GritCommand, bsub_ram_default=24000)
@click.option("--reference", "-r", default=None, help="Path to reference FASTA (overrides auto-search in workdir/reference/).")
@click.pass_context
def fastga_cmd(ctx, reference):
    """Run FastGA dot-plot comparison of curated assembly vs reference."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_fastga(curation_ctx, reference_path=reference)
    except Exception:
        log.exception("fastga failed")
        raise SystemExit(1)


@click.command("fastga-stats", cls=GritCommand)
@click.pass_context
def fastga_stats_cmd(ctx):
    """Print the per-query top-longest reference target table from the latest fastga run."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_fastga_stats(curation_ctx)
    except Exception:
        log.exception("fastga-stats failed")
        raise SystemExit(1)
