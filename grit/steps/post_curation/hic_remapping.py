"""Step: submit the HiC remapping pipeline (sanger-tol/curationpretext) via bsub."""

from __future__ import annotations

import dataclasses
import logging
import re
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, find_canonical_fa
from grit.utils.modules import module_cmd
from grit.utils.output import console, print_done, print_step_header, print_tip

log = logging.getLogger(__name__)

_OUTPUT_SPECS: list[tuple[str, str, list[str]]] = [
    ("hap1_pretext", "pretext_maps_processed/{tol_id}*hr.pretext", []),
    ("hap1_normal_pretext", "pretext_maps_processed/{tol_id}*normal.pretext", []),
]
_OUTPUT_SPECS_HAP2: list[tuple[str, str, list[str]]] = [
    ("hap2_pretext", "pretext_maps_processed/{tol_id}*hr.pretext", []),
    ("hap2_normal_pretext", "pretext_maps_processed/{tol_id}*normal.pretext", []),
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _submit_hic_remapping(
    ctx: CurationContext,
    hap_prefix: str,
    step_name: str,
    *,
    assembly: Path | None = None,
) -> None:
    """Submit one curationpretext run for *hap_prefix*, tracked under *step_name*."""

    # Check for existing successful run; re-run only if the hap-specific canonical FA is newer
    if ctx.tracker:
        prev_dir = ctx.tracker.latest_run_dir(step_name)
        hr_pretexts = (
            list(prev_dir.glob(f"pretext_maps_processed/{ctx.tol_id}*hr.pretext"))
            if prev_dir
            else []
        )
        if hr_pretexts:
            pretext_mtime = min(f.stat().st_mtime for f in hr_pretexts)
            fa_newer = False
            try:
                canonical_fa = find_canonical_fa(ctx, hap_prefix)
                fa_newer = canonical_fa.stat().st_mtime > pretext_mtime
            except FileNotFoundError:
                pass
            if fa_newer:
                log.info("Curated FASTA is newer than remapped pretext — re-running %s", step_name)
            elif ctx.print_only:
                print_tip(
                    f"Remapped pretext map already exists for [bold]{hap_prefix}[/bold] "
                    f"and is up to date — will be skipped on actual run:\n"
                    f"  {hr_pretexts[0]}"
                )
                return
            else:
                log.info("HiC remapping already done — skipping: %s", prev_dir)
                last = ctx.tracker.history(step_name)
                if last and last[-1].get("status") == "started":
                    from grit.utils.helpers import _get_step_specs, collect_outputs

                    specs = _get_step_specs(step_name)
                    outputs = (
                        collect_outputs(
                            specs, prev_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
                        )
                        if specs
                        else None
                    )
                    ctx.tracker.finish(step_name, prev_dir, "success", outputs=outputs or None)
                print_done(f"Already done → {prev_dir}")
                return

    run_dir = (
        ctx.tracker.start(
            step_name, ctx.ticket_id, ctx.tol_id, suffix=hap_prefix, untracked=ctx.untracked
        )
        if ctx.tracker
        else ctx.workdir / step_name / "untracked"
    )

    input_fa = assembly if assembly else find_canonical_fa(ctx, hap_prefix)
    log.info("Input FASTA: %s", input_fa)

    sample = f"{ctx.tol_id}.{hap_prefix}"

    hic_cmd = (
        f"cd {run_dir} && "
        f"{module_cmd('CURATIONPRETEXT')} && "
        f"curationpretext.sh -profile sanger,singularity"
        f" --map_order unsorted"
        f" --input {input_fa}"
        f" --sample {sample}"
        f" --cram {ctx.hic_dir}"
        f" --reads {ctx.long_reads_dir}/fasta"
        f" --read_type {ctx.read_type}"
        f" --outdir {run_dir}"
        f" --split_telomere true"
    )
    if ctx.teloseq:
        hic_cmd += f" {ctx.teloseq}"
    hic_cmd += " -resume"

    try:
        output = _run(hic_cmd, ctx.print_only)
        if ctx.tracker and run_dir and output and "Job <" in output:
            m = re.search(r"Job <(\d+)>", output)
            if m:
                ctx.tracker.record_job(step_name, run_dir, m.group(1))
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish(step_name, run_dir, "failed")
        raise

    remapped_pattern = str(run_dir / "pretext_maps_processed" / f"{sample}*normal.pretext")
    scp_cmd = (
        f"scp {ctx.farm_host}:{remapped_pattern} ~/curations/{ctx.tol_id}/{sample}_remapped.pretext"
    )
    console.print("\n[bold]After remapping, copy the map to your local machine:[/bold]")
    console.print(f"  [green]{scp_cmd}[/green]")


# ---------------------------------------------------------------------------
# Public step function
# ---------------------------------------------------------------------------


def run_hic_remapping(
    ctx: CurationContext,
    *,
    run_hap1: bool = True,
    run_hap2: bool = False,
    hic_dir: Path | None = None,
    hifi_dir: Path | None = None,
    ont_dir: Path | None = None,
    assembly: Path | None = None,
) -> None:
    """
    Runs the HiC remapping pipeline (sanger-tol/curationpretext).

    Submits hap1 when ``run_hap1=True`` (default) and/or hap2 when
    ``run_hap2=True`` (tracked separately as ``hic_remapping_hap2``). Pass
    ``run_hap1=False, run_hap2=True`` to submit hap2 only.

    ``hic_dir``, ``hifi_dir``, ``ont_dir`` override the values from the ticket
    YAML. If ``ont_dir`` is supplied, ``--read_type ont`` is used automatically.
    """
    # Apply CLI overrides to a fresh context copy (frozen dataclass)
    overrides: dict = {}
    if hic_dir:
        overrides["hic_dir"] = hic_dir
    if ont_dir:
        overrides["long_reads_dir"] = ont_dir
        overrides["read_type"] = "ont"
    elif hifi_dir:
        overrides["long_reads_dir"] = hifi_dir
        overrides["read_type"] = "hifi"
    if overrides:
        ctx = dataclasses.replace(ctx, **overrides)

    log.info("hic-remapping | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    if overrides:
        log.info("Path overrides: %s", {k: str(v) for k, v in overrides.items()})
    print_step_header(ctx.ticket_id, ctx.tol_id, "HiC remapping")

    if run_hap1:
        _submit_hic_remapping(ctx, ctx.hap1_prefix, "hic_remapping", assembly=assembly)

    if run_hap2:
        print_step_header(ctx.ticket_id, ctx.tol_id, f"HiC remapping ({ctx.hap2_prefix})")
        _submit_hic_remapping(ctx, ctx.hap2_prefix, "hic_remapping_hap2")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("hic-remapping", cls=GritCommand)
@click.option(
    "--hap2",
    "run_hap2",
    is_flag=True,
    default=False,
    help="Submit HiC remapping for hap2 instead of hap1.",
)
@click.option(
    "--hic-dir",
    "hic_dir",
    type=click.Path(),
    default=None,
    help="Override HiC reads directory from ticket YAML.",
)
@click.option(
    "--hifi-dir",
    "hifi_dir",
    type=click.Path(),
    default=None,
    help="Override HiFi reads directory from ticket YAML.",
)
@click.option(
    "--ont-dir",
    "ont_dir",
    type=click.Path(),
    default=None,
    help="Override ONT reads directory from ticket YAML (sets --read_type ont).",
)
@click.option(
    "--assembly",
    "assembly",
    type=click.Path(),
    default=None,
    help="Use this FASTA instead of the canonical assembly resolved from workdir.",
)
@click.pass_context
def hic_remapping_cmd(ctx, run_hap2, hic_dir, hifi_dir, ont_dir, assembly):
    """Submit HiC remapping pipeline."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_hic_remapping(
            curation_ctx,
            run_hap1=not run_hap2,
            run_hap2=run_hap2,
            hic_dir=Path(hic_dir) if hic_dir else None,
            hifi_dir=Path(hifi_dir) if hifi_dir else None,
            ont_dir=Path(ont_dir) if ont_dir else None,
            assembly=Path(assembly) if assembly else None,
        )
    except Exception:
        log.exception("hic-remapping failed")
        raise SystemExit(1)
