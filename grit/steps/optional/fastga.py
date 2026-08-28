"""Run FastGA dot-plot comparison."""

import glob
import logging
from pathlib import Path

import rich_click as click
from rich.table import Table

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _run,
    _state_update_epilogue,
    _submit_bsub,
    build_bsub_opts,
    collect_outputs,
    find_canonical_fa,
    find_latest_dir,
    find_reheadered_reference,
    write_fake_outputs,
)
from grit.utils.modules import module_cmd
from grit.utils.output import (
    console,
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

_SCRIPTS_DIR = Path(__file__).parent.parent.parent / "scripts"
_PAF_TOP_TARGETS_SCRIPT = _SCRIPTS_DIR / "paf_top_targets_by_coverage.py"

# Downloadable outputs, picked up by the bsub -Ep epilogue (grit _state-update)
# and surfaced as an scp tip in `grit status` — see build_scp_tip().
# "idx" is a "multi" spec: FastGA_dot_dgenies_stats.sh writes one .idx per
# genome (ref and query), and both must reach the scp tip — see
# collect_outputs()/MULTI_OUTPUT_SEP in grit/utils/helpers.py.
_OUTPUT_SPECS: list[tuple[str, str, list[str]] | tuple[str, str, list[str], bool]] = [
    ("idx", "*.idx", [], True),
    ("paf", "*FastGA.paf", []),
]

# Outputs for the separate "fastga_stats" step (`grit fastga-stats`) — computed
# synchronously by run_fastga_stats from fastga's PAF, not part of the fastga
# bsub job.
_OUTPUT_SPECS_STATS: list[tuple[str, str, list[str]]] = [
    ("top1_targets", "*.top1_targets.tsv", []),
    ("top_targets_summary", "*.top_targets_summary.txt", []),
]


def _is_super(name: str) -> bool:
    """True for curated chromosome-level scaffolds (SUPER_*), false for unloc/contig-level ones."""
    return name.startswith("SUPER_")


def _read_top1_table(top1_file: Path) -> list[tuple[str, str, str, str]]:
    """Read the curated_fa_chr/ref_fa_chr/aligned_length/prc_of_ref_length rows from --top1-out."""
    lines = top1_file.read_text().splitlines()[1:]
    return [tuple(line.split("\t")) for line in lines if line.strip()]


def _print_top1_table(top1_file: Path) -> None:
    """Render *top1_file*'s SUPER_* rows as a Rich table."""
    rows = [row for row in _read_top1_table(top1_file) if _is_super(row[0])]
    if not rows:
        log.warning("No SUPER_* rows found in %s", top1_file)
        return

    table = Table(
        title="Best reference target per super scaffold (by non-overlapping coverage)",
        header_style="bold cyan",
    )
    table.add_column("super")
    table.add_column("ref_chr")
    table.add_column("aligned_length", justify="right")
    table.add_column("prc_of_ref_length", justify="right")
    for super_name, ref_chr, length, pct in rows:
        table.add_row(super_name, ref_chr, f"{int(length):,}", f"{float(pct):.2f}%")
    console.print(table)


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_fastga(ctx: CurationContext, reference_path: str | None = None) -> None:
    """Submits the FastGA dot-plot alignment bsub job."""
    log.info("fastga | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run FastGA")

    if ctx.dry_run:
        run_dir = ctx.tracker.start("fastga", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        outputs = write_fake_outputs("fastga", run_dir, ctx.tol_id)
        ctx.tracker.finish("fastga", run_dir, "success", outputs=outputs, untracked=ctx.untracked)
        print_done(f"[dry-run] FastGA → {outputs.get('paf', run_dir)}")
        return

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
    run_dir = (
        ctx.tracker.start("fastga", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / "fastga" / "untracked"
    )
    fastga_script = _SCRIPTS_DIR / "FastGA_dot_dgenies_stats.sh"

    inner_cmd = (
        f"cd {run_dir} && "
        f"{module_cmd('GRIT')} && "
        f"bash {fastga_script} {ref_reheader} {hap1_fa} {run_prefix} {run_dir}"
    )
    bsub_opts = build_bsub_opts(
        group="team135",
        cores=8,
        memory_mb=ctx.bsub_ram or 24000,
        output="o_fastga",
        error="e_fastga",
        run_dir=run_dir,
    )
    epilogue = (
        _state_update_epilogue(ctx.workdir, "fastga", run_dir, untracked=ctx.untracked)
        if run_dir
        else None
    )

    try:
        job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
        if ctx.tracker and run_dir and job_id:
            ctx.tracker.record_job("fastga", run_dir, job_id)
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("fastga", run_dir, "failed", untracked=ctx.untracked)
        raise

    print_done("FastGA submitted.")


def run_fastga_stats(ctx: CurationContext) -> None:
    """Computes (from the latest fastga run's PAF) and prints the best reference
    target per super scaffold, by non-overlapping coverage."""
    log.info("fastga-stats | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "FastGA best targets by coverage")

    if ctx.dry_run:
        run_dir = ctx.tracker.start(
            "fastga_stats", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked
        )
        outputs = write_fake_outputs(
            "fastga_stats",
            run_dir,
            ctx.tol_id,
            content={
                "top1_targets": (
                    b"curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\n"
                    b"SUPER_1\tchr1\t1000000\t100.00\n"
                )
            },
        )
        ctx.tracker.finish(
            "fastga_stats", run_dir, "success", outputs=outputs, untracked=ctx.untracked
        )
        _print_top1_table(Path(outputs["top1_targets"]))
        return

    fastga_dir = find_latest_dir(ctx, "fastga")
    paf_matches = glob.glob(str(fastga_dir / "*FastGA.paf"))
    if not paf_matches:
        raise FileNotFoundError(
            f"No FastGA PAF file found in {fastga_dir}\nRun 'grit fastga -t {ctx.ticket_id}' first."
        )
    paf_file = Path(sorted(paf_matches)[-1])
    prefix = paf_file.name.removesuffix("_FastGA.paf")

    run_dir = (
        ctx.tracker.start("fastga_stats", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / "fastga_stats" / "untracked"
    )
    top1_file = run_dir / f"{prefix}.top1_targets.tsv"
    summary_file = run_dir / f"{prefix}.top_targets_summary.txt"

    if not ctx.print_only:
        run_dir.mkdir(parents=True, exist_ok=True)

    cmd = (
        f"{module_cmd('GRIT')} && "
        f"python3 {_PAF_TOP_TARGETS_SCRIPT} {paf_file} --top1-out {top1_file} "
        f"--top_longest > {summary_file}"
    )
    _run(cmd, ctx.print_only)
    if ctx.print_only:
        return

    outputs = collect_outputs(_OUTPUT_SPECS_STATS, run_dir, ctx.tol_id)
    if ctx.tracker and run_dir:
        ctx.tracker.finish(
            "fastga_stats", run_dir, "success", outputs=outputs, untracked=ctx.untracked
        )

    _print_top1_table(top1_file)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("fastga", cls=GritCommand, bsub_ram_default=24000)
@click.option(
    "--reference",
    "-r",
    default=None,
    help="Path to reference FASTA (overrides auto-search in workdir/reference/).",
)
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
    """Compute and print the per-query best-target-by-coverage table from the
    latest fastga run's PAF."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_fastga_stats(curation_ctx)
    except Exception:
        log.exception("fastga-stats failed")
        raise SystemExit(1)
