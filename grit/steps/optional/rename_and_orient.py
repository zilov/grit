"""Rename and orient chromosomes to reference."""

from __future__ import annotations

import glob
import logging
import sys
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
from grit.utils.modules import module_cmd
from grit.utils.output import console, print_done, print_step_header

log = logging.getLogger(__name__)

_RENAME_AND_ORIENT_CMD = str(Path(sys.executable).parent / "rename-and-orient")
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
    paf_file: Path,
    step_name: str,
    *,
    mapping_table: Path | None = None,
) -> str | None:
    """
    Submit a bsub job running rename-and-orient for one haplotype.

    For hap1: uses ``--paf`` for alignment.
    For hap2: pass ``mapping_table`` (the .mapping.tsv from the hap1 run) to
    use ``--mapping-table`` instead of re-aligning.

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

    inner_cmd = (
        f"{module_cmd('GRIT')} && "
        f"{_RENAME_AND_ORIENT_CMD} "
        f"--fasta {input_fa} "
        f"{source_arg} "
        f"--output-dir {run_dir} "
        f"--output-prefix {prefix}"
    )

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


def run_rename_and_orient(ctx: CurationContext, *, run_hap2: bool = False) -> None:
    """
    Renames and orients chromosomes in the curated FASTA based on FastGA PAF alignment.

    Submits hap1 as a bsub job (60 GB, 4 cores). Pass ``run_hap2=True`` to
    also submit hap2 — but only if the hap1 mapping table already exists
    (i.e. hap1 has completed). If not, a message is printed asking to re-run
    with ``--hap2`` after hap1 finishes.

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

    # --- find FastGA PAF ---
    fastga_dir = find_latest_dir(ctx, "fastga")
    paf_matches = glob.glob(str(fastga_dir / "*FastGA.paf"))
    if not paf_matches:
        raise FileNotFoundError(
            f"No FastGA PAF found in {fastga_dir}\nRun 'grit fastga -t {ctx.ticket_id}' first."
        )
    paf_file = Path(sorted(paf_matches)[-1])
    log.info("FastGA PAF: %s", paf_file)

    _submit_rename_and_orient_for_hap(ctx, ctx.hap1_prefix, paf_file, "rename_and_orient")

    if run_hap2:
        print_step_header(ctx.ticket_id, ctx.tol_id, f"Rename and orient ({ctx.hap2_prefix})")
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
@click.pass_context
def rename_and_orient_cmd(ctx, run_hap2):
    """Rename and orient chromosomes in curated FASTA based on FastGA PAF alignment."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_rename_and_orient(curation_ctx, run_hap2=run_hap2)
    except Exception:
        log.exception("rename-and-orient failed")
        raise SystemExit(1)
