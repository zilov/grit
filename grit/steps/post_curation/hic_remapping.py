"""Step: submit the HiC remapping pipeline (sanger-tol/curationpretext) via bsub."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import (
    _state_update_epilogue,
    _submit_bsub,
    build_bsub_opts,
    find_canonical_fa,
    find_canonical_map,
    refuse_hap2_on_single_hap,
)
from grit.utils.modules import module_cmd
from grit.utils.output import console, print_done, print_step_header, print_tip

log = logging.getLogger(__name__)

# Same head-job resources curationpretext.sh requests; nextflow submits the real work itself.
_HEAD_JOB_MEM_MB = 1200
_CURATIONPRETEXT_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "curationpretext.sh"

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


def _in_flight_run(ctx: CurationContext, step_name: str) -> tuple[Path, str | None] | None:
    """Return (run_dir, job_id) of *step_name*'s newest run if its latest record is ``started``."""
    runs = [r for r in ctx.tracker.history(step_name) if r.get("run_dir")]
    started = [r for r in runs if r.get("status") == "started"]
    if not started:
        return None
    run_dir = started[-1]["run_dir"]
    records = [r for r in runs if r["run_dir"] == run_dir]
    if records[-1].get("status") != "started":
        return None
    return Path(run_dir), next((r["job_id"] for r in records if r.get("job_id")), None)


def _fasta_newer(ctx: CurationContext, hap_prefix: str, pretext: Path) -> bool:
    """True when *hap_prefix*'s canonical FASTA is newer than *pretext* (False if there is none)."""
    try:
        return find_canonical_fa(ctx, hap_prefix).stat().st_mtime > pretext.stat().st_mtime
    except FileNotFoundError:
        return False


def _up_to_date_map(ctx: CurationContext, hap_prefix: str) -> Path | None:
    """Return *hap_prefix*'s canonical remapped map if it is newer than its canonical FASTA."""
    try:
        pretext = find_canonical_map(ctx, hap_prefix)
        fasta = find_canonical_fa(ctx, hap_prefix)
    except FileNotFoundError:
        return None
    return pretext if pretext.stat().st_mtime > fasta.stat().st_mtime else None


def _skip_hap(
    ctx: CurationContext, hap_prefix: str, step_name: str, *, check_up_to_date: bool = True
) -> bool:
    """Report and return True when *hap_prefix*'s remap is in flight or already up to date."""
    if ctx.tracker and (in_flight := _in_flight_run(ctx, step_name)):
        run_dir, job_id = in_flight
        # an in-flight run whose map already predates the canonical FASTA is remapping stale input
        maps = list(run_dir.glob(f"pretext_maps_processed/{ctx.tol_id}*.pretext"))
        if maps and _fasta_newer(ctx, hap_prefix, min(maps, key=lambda m: m.stat().st_mtime)):
            log.info("Canonical FASTA is newer than in-flight %s's map — resubmitting", step_name)
            return False
        print_tip(
            f"HiC remapping for [bold]{hap_prefix}[/bold] is still in progress"
            f"{f' (job {job_id})' if job_id else ''} — not resubmitting:\n  {run_dir}"
        )
        return True
    pretext = _up_to_date_map(ctx, hap_prefix) if check_up_to_date else None
    if pretext:
        log.info("HiC map for %s is newer than its canonical FASTA — skipping", hap_prefix)
        print_done(f"{hap_prefix} Hi-C map is up to date with the canonical FASTA → {pretext}")
        return True
    return False


def _submit_hic_remapping(
    ctx: CurationContext,
    hap_prefix: str,
    step_name: str,
    *,
    assembly: Path | None = None,
    check_up_to_date: bool = True,
) -> None:
    """Submit one curationpretext run for *hap_prefix*, tracked under *step_name*."""

    if _skip_hap(ctx, hap_prefix, step_name, check_up_to_date=check_up_to_date):
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

    pipeline_args = (
        "--map_order unsorted"
        f" --input {input_fa}"
        f" --sample {sample}"
        f" --cram {ctx.hic_dir}"
        f" --reads {ctx.long_reads_dir}/fasta"
        f" --read_type {ctx.read_type}"
        f" --outdir {run_dir}"
        " --split_telomere true"
    )
    if ctx.teloseq:
        pipeline_args += f" {ctx.teloseq}"
    if ctx.email:
        pipeline_args += f" -N {ctx.email}"
    pipeline_args += " -resume"

    inner_cmd = (
        f"cd {run_dir} && {module_cmd('CURATIONPRETEXT')} && "
        f"bash {_CURATIONPRETEXT_SCRIPT} {pipeline_args}"
    )
    bsub_opts = build_bsub_opts(
        queue="oversubscribed",
        memory_mb=_HEAD_JOB_MEM_MB,
        output="curationpretext_%J.log",
        run_dir=run_dir,
    )
    epilogue = _state_update_epilogue(ctx.workdir, step_name, run_dir, untracked=ctx.untracked)

    try:
        job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)
        if ctx.tracker and job_id:
            ctx.tracker.record_job(step_name, run_dir, job_id)
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish(step_name, run_dir, "failed", untracked=ctx.untracked)
        raise

    remapped_pattern = str(run_dir / "pretext_maps_processed" / f"{sample}*normal.pretext")
    scp_cmd = (
        f"scp {ctx.farm_host}:{remapped_pattern} ~/curations/{ctx.tol_id}/{sample}_remapped.pretext"
    )
    console.print("\n[bold]After remapping, copy the map to your local machine:[/bold]")
    console.print(f"  [green]{scp_cmd}[/green]")


def _dry_run_hic_remapping_for_hap(
    ctx: CurationContext, hap_prefix: str, step_name: str, *, check_up_to_date: bool = True
) -> dict[str, str]:
    """Write placeholder remapped pretext maps, named as curationpretext names them."""
    if _skip_hap(ctx, hap_prefix, step_name, check_up_to_date=check_up_to_date):
        return {}
    run_dir = ctx.tracker.start(step_name, ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
    key, hap = (
        ("hap2", ctx.hap2_prefix) if step_name.endswith("_hap2") else ("hap1", ctx.hap1_prefix)
    )
    maps_dir = run_dir / "pretext_maps_processed"
    maps_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, str] = {}
    for suffix, out_key in (("hr", f"{key}_pretext"), ("normal", f"{key}_normal_pretext")):
        path = maps_dir / f"{ctx.tol_id}.{hap}_{suffix}.pretext"
        path.write_bytes(b"fake pretext\n")
        outputs[out_key] = str(path)
    ctx.tracker.finish(step_name, run_dir, "success", outputs=outputs, untracked=ctx.untracked)
    return outputs


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
    fresh_fasta: bool = False,
) -> None:
    """
    Runs the HiC remapping pipeline (sanger-tol/curationpretext).

    Submits hap1 when ``run_hap1=True`` (default) and hap2 too when
    ``run_hap2=True`` (tracked separately as ``hic_remapping_hap2``). A
    haplotype is skipped while its run is in flight or when its canonical map
    is newer than its canonical FASTA.

    ``hic_dir``, ``hifi_dir``, ``ont_dir`` override the values from the ticket
    YAML. If ``ont_dir`` is supplied, ``--read_type ont`` is used automatically.
    ``fresh_fasta=True`` (a chain that just rebuilt the FASTA) skips the up-to-date check.
    """
    check = not fresh_fasta
    if run_hap2:
        refuse_hap2_on_single_hap(ctx)

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

    if ctx.dry_run:
        if run_hap1:
            outputs = _dry_run_hic_remapping_for_hap(
                ctx, ctx.hap1_prefix, "hic_remapping", check_up_to_date=check
            )
            if outputs:
                print_done(f"[dry-run] Remapped pretext map → {outputs['hap1_normal_pretext']}")
        if run_hap2:
            print_step_header(ctx.ticket_id, ctx.tol_id, f"HiC remapping ({ctx.hap2_prefix})")
            outputs = _dry_run_hic_remapping_for_hap(
                ctx, ctx.hap2_prefix, "hic_remapping_hap2", check_up_to_date=check
            )
            if outputs:
                print_done(f"[dry-run] Remapped pretext map → {outputs['hap2_normal_pretext']}")
        return

    if run_hap1:
        _submit_hic_remapping(
            ctx, ctx.hap1_prefix, "hic_remapping", assembly=assembly, check_up_to_date=check
        )

    if run_hap2:
        print_step_header(ctx.ticket_id, ctx.tol_id, f"HiC remapping ({ctx.hap2_prefix})")
        _submit_hic_remapping(ctx, ctx.hap2_prefix, "hic_remapping_hap2", check_up_to_date=check)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("hic-remapping", cls=GritCommand)
@click.option(
    "--hap2",
    "run_hap2",
    is_flag=True,
    default=False,
    help="Run hap2 as well as hap1 (hap1 is skipped if its map is newer than its canonical FASTA).",
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
            run_hap2=run_hap2,
            hic_dir=Path(hic_dir) if hic_dir else None,
            hifi_dir=Path(hifi_dir) if hifi_dir else None,
            ont_dir=Path(ont_dir) if ont_dir else None,
            assembly=Path(assembly) if assembly else None,
        )
    except Exception:
        log.exception("hic-remapping failed")
        raise SystemExit(1)
