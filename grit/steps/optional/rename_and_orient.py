"""Rename and orient chromosomes to reference."""

from __future__ import annotations

import glob
import logging
import shutil
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _state_update_epilogue,
    _submit_bsub,
    build_bsub_opts,
    find_canonical_fa,
    find_latest_dir,
    write_fake_outputs,
)
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

_DEFAULT_MEM_MB = 60000

_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("hap1_fa", "{tol_id}.{hap1}.*.fa", ["haplotigs"]),
    ("hap1_chr_list", "{tol_id}.{hap1}.*.chromosome.list.csv", []),
]
_OUTPUT_SPECS_HAP2: list[tuple[str, str, list[str]]] = [
    ("hap2_fa", "{tol_id}.{hap2}.*.fa", ["haplotigs"]),
    ("hap2_chr_list", "{tol_id}.{hap2}.*.chromosome.list.csv", []),
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _submit_rename_and_orient_for_hap(
    ctx: CurationContext,
    hap_prefix: str,
    paf_file: Path | None,
    step_name: str,
    *,
    mapping_table: Path | None = None,
    min_coverage: float | None = None,
    plot_alignments: bool = False,
) -> str | None:
    """
    Submit a bsub job running rename-and-orient for one haplotype.

    Uses ``--mapping-table`` when ``mapping_table`` is given (no alignment
    needed), otherwise ``--paf`` with the FastGA alignment.

    Returns the bsub job ID (or None in print_only mode).
    """
    prefix = f"{ctx.tol_id}.{hap_prefix}.primary.renamed"

    # Read whatever is currently canonical for this haplotype.
    input_fa = find_canonical_fa(ctx, hap_prefix)
    log.info("Curated %s FASTA: %s", hap_prefix, input_fa)

    run_dir = (
        ctx.tracker.start(step_name, ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / step_name / "untracked"
    )

    source_arg = f"--mapping-table {mapping_table}" if mapping_table else f"--paf {paf_file}"

    # Resolve the absolute path now, on the submit host, since $HOME is
    # NFS-shared with the compute node and rename-and-orient's own bsub
    # environment carries no module load to put it on PATH.
    rename_and_orient_cmd = shutil.which("rename-and-orient") or "rename-and-orient"

    inner_cmd = (
        f"{rename_and_orient_cmd} "
        f"--fasta {input_fa} "
        f"{source_arg} "
        f"--output-dir {run_dir} "
        f"--output-prefix {prefix}"
    )
    if min_coverage is not None:
        inner_cmd += f" --min-coverage {min_coverage}"
    if plot_alignments:
        if mapping_table:
            # Plots are drawn from PAF alignment blocks, which mapping-table mode never reads.
            log.warning(
                "--plot-alignments ignored for %s: no PAF in mapping-table mode", hap_prefix
            )
        else:
            inner_cmd += " --plot-alignments"

    bsub_opts = build_bsub_opts(
        group="team135",
        cores=4,
        memory_mb=ctx.bsub_ram or _DEFAULT_MEM_MB,
        output="o_rename_and_orient",
        error="e_rename_and_orient",
        run_dir=run_dir,
    )
    epilogue = (
        _state_update_epilogue(ctx.workdir, step_name, run_dir, untracked=ctx.untracked)
        if run_dir
        else None
    )

    console.print(f"\n[yellow]Command ({hap_prefix}):[/yellow] [green]{inner_cmd}[/green]")

    try:
        job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
        if ctx.tracker and run_dir and job_id:
            ctx.tracker.record_job(step_name, run_dir, job_id)
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish(step_name, run_dir, "failed", untracked=ctx.untracked)
        raise

    return job_id


def _dry_run_rename_and_orient_for_hap(ctx: CurationContext, step_name: str) -> dict[str, str]:
    """Write a placeholder renamed FASTA directly into this hap's tracked run_dir."""
    run_dir = ctx.tracker.start(step_name, ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
    outputs = write_fake_outputs(
        step_name, run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
    )
    ctx.tracker.finish(step_name, run_dir, "success", outputs=outputs, untracked=ctx.untracked)
    return outputs


# ---------------------------------------------------------------------------
# Public step function
# ---------------------------------------------------------------------------


def run_rename_and_orient(
    ctx: CurationContext,
    *,
    run_hap2: bool = False,
    mapping_table: Path | None = None,
    min_coverage: float | None = None,
    plot_alignments: bool = False,
) -> None:
    """
    Renames and orients chromosomes in the curated FASTA based on FastGA PAF alignment.

    Submits hap1 as a bsub job (60 GB, 4 cores). Pass ``run_hap2=True`` to
    also submit hap2 — but only if the hap1 mapping table already exists
    (i.e. hap1 has completed). If not, a message is printed asking to re-run
    with ``--hap2`` after hap1 finishes.

    Pass ``mapping_table`` to reuse a pre-built mapping TSV for every haplotype
    instead of a FastGA PAF — no ``grit fastga`` run is needed then.

    Output files land in each run's own tracked run_dir under
    ``{workdir}/rename_and_orient/`` (hap1) or ``{workdir}/rename_and_orient_hap2/`` (hap2).
    """
    log.info("rename-and-orient | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Rename and orient to reference")

    if ctx.dry_run:
        outputs = _dry_run_rename_and_orient_for_hap(ctx, "rename_and_orient")
        if run_hap2:
            print_step_header(ctx.ticket_id, ctx.tol_id, f"Rename and orient ({ctx.hap2_prefix})")
            _dry_run_rename_and_orient_for_hap(ctx, "rename_and_orient_hap2")
        print_done(f"[dry-run] Renamed FASTA → {outputs.get('hap1_fa', ctx.workdir)}")
        return

    paf_file: Path | None = None
    if mapping_table is not None:
        mapping_table = mapping_table.expanduser()
        if not ctx.print_only and not mapping_table.exists():
            raise FileNotFoundError(f"Mapping table not found: {mapping_table}")
        log.info("Mapping table: %s (skipping FastGA PAF)", mapping_table)
    else:
        # --- find FastGA PAF ---
        fastga_dir = find_latest_dir(ctx, "fastga")
        paf_matches = glob.glob(str(fastga_dir / "*FastGA.paf"))
        if not paf_matches:
            raise FileNotFoundError(
                f"No FastGA PAF found in {fastga_dir}\nRun 'grit fastga -t {ctx.ticket_id}' first."
            )
        paf_file = Path(sorted(paf_matches)[-1])
        log.info("FastGA PAF: %s", paf_file)

    _submit_rename_and_orient_for_hap(
        ctx,
        ctx.hap1_prefix,
        paf_file,
        "rename_and_orient",
        mapping_table=mapping_table,
        min_coverage=min_coverage,
        plot_alignments=plot_alignments,
    )

    if run_hap2:
        print_step_header(ctx.ticket_id, ctx.tol_id, f"Rename and orient ({ctx.hap2_prefix})")
        # With an explicit mapping table there is nothing to wait for — hap2
        # reuses the same table as hap1 instead of the one hap1 produces.
        mapping_tsv = mapping_table
        if mapping_tsv is None:
            hap1_run_dir = find_latest_dir(ctx, "rename_and_orient")
            hap1_prefix = f"{ctx.tol_id}.{ctx.hap1_prefix}.primary.renamed"
            mapping_tsv = hap1_run_dir / f"{hap1_prefix}.mapping.tsv"

            if not ctx.print_only and not mapping_tsv.exists():
                console.print(
                    f"\n[yellow]hap1 mapping table not found yet:[/yellow] {mapping_tsv}\n"
                    f"Re-run with [bold]--hap2[/bold] after hap1 completes."
                )
                return

        _submit_rename_and_orient_for_hap(
            ctx,
            ctx.hap2_prefix,
            paf_file,
            "rename_and_orient_hap2",
            mapping_table=mapping_tsv,
            min_coverage=min_coverage,
        )

    print_done(f"Job(s) submitted — output → {ctx.workdir / 'rename_and_orient*'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("rename-and-orient", cls=GritCommand, bsub_ram_default=_DEFAULT_MEM_MB)
@click.option(
    "--hap2",
    "run_hap2",
    is_flag=True,
    default=False,
    help="Also rename and orient hap2 using the mapping table from hap1 run.",
)
@click.option(
    "--mapping-table",
    "-mt",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Pre-built mapping TSV to rename/orient with, instead of a FastGA PAF "
    "(no 'grit fastga' run needed). Used for every haplotype.",
)
@click.option(
    "--min-coverage",
    "-c",
    type=click.FloatRange(0.0, 1.0),
    default=None,
    help="Minimum coverage threshold for renaming (0.0-1.0)  [rename-and-orient default: 0.5]",
)
@click.option(
    "--plot-alignments",
    "-P",
    is_flag=True,
    default=False,
    help="Generate scatter plots of PAF alignment blocks per chromosome (PAF mode only).",
)
@click.pass_context
def rename_and_orient_cmd(ctx, run_hap2, mapping_table, min_coverage, plot_alignments):
    """Rename and orient chromosomes in curated FASTA based on FastGA PAF alignment."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_rename_and_orient(
            curation_ctx,
            run_hap2=run_hap2,
            mapping_table=mapping_table,
            min_coverage=min_coverage,
            plot_alignments=plot_alignments,
        )
    except Exception:
        log.exception("rename-and-orient failed")
        raise SystemExit(1)
