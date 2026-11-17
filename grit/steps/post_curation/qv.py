"""Step: run QV and k-mer completeness analysis (blocks until its MerquryFK job finishes)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run
from grit.utils.modules import module_cmd
from grit.utils.output import print_done, print_step_header

log = logging.getLogger(__name__)

_KMER_COMPLETENESS_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "kmer_completeness.sh"

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_qv_outputs(ctx: CurationContext, run_dir: Path) -> dict[str, str]:
    """Return the run's MerquryFK .qv / .completeness.stats files that exist."""
    outputs: dict[str, str] = {}
    qv_file = run_dir / f"{ctx.tol_id}.qv"
    if qv_file.exists():
        outputs["qv"] = str(qv_file)
    completeness_file = run_dir / f"{ctx.tol_id}.completeness.stats"
    if completeness_file.exists():
        outputs["completeness_stats"] = str(completeness_file)
    return outputs


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_qv(ctx: CurationContext) -> None:
    """Run MerquryFK in ``workdir/qv/<ts>/``, then copy its results to ``curated/merquryk``."""
    log.info("qv | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "QV analysis")

    run_dir = (
        ctx.tracker.start("qv", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / "qv"
    )
    qv_dir = ctx.assembly_curated_dir / "merquryk"

    if ctx.dry_run:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / f"{ctx.tol_id}.qv").write_text(
            "Assembly\tNo Support\tTotal\tError %\tQV\n"
            f"{ctx.tol_id}.{ctx.hap1_prefix}\t1204\t412345678\t0.0003\t65.4\n"
            f"{ctx.tol_id}.{ctx.hap2_prefix}\t1350\t405678123\t0.0003\t64.9\n"
            "Both\t2554\t818023801\t0.0003\t65.1\n"
        )
        (run_dir / f"{ctx.tol_id}.completeness.stats").write_text(
            "Assembly\tRegion\tFound\tTotal\t% Covered\n"
            f"{ctx.tol_id}.{ctx.hap1_prefix}\tall\t402123456\t425678901\t94.47\n"
            f"{ctx.tol_id}.{ctx.hap2_prefix}\tall\t398765432\t425678901\t93.68\n"
            "Both\tall\t421234567\t425678901\t98.96\n"
        )
        qv_dir.mkdir(parents=True, exist_ok=True)
        for f in run_dir.glob(f"{ctx.tol_id}.*"):
            shutil.copy(f, qv_dir)
        if ctx.tracker:
            outputs = _find_qv_outputs(ctx, run_dir) or None
            ctx.tracker.finish("qv", run_dir, "success", outputs=outputs, untracked=ctx.untracked)
        print_done(f"[dry-run] QV analysis → {run_dir}, copied to {qv_dir}")
        return

    script_log = run_dir / "kmer_completeness.log"
    cmd = (
        f"{module_cmd('GRIT')} && mkdir -p {run_dir} && cd {run_dir} && "
        f"bash {_KMER_COMPLETENESS_SCRIPT} {ctx.tol_id} {ctx.release_version} "
        f"{ctx.assembly_curated_dir} {ctx.assembly_draft_dir} > {script_log} 2>&1"
    )
    try:
        # judged by the files, not the exit status: MerquryFK can exit 0 without its outputs
        _run(cmd, ctx.print_only)
        outputs = None if ctx.print_only else _find_qv_outputs(ctx, run_dir)
        if outputs is not None and set(outputs) != {"qv", "completeness_stats"}:
            raise RuntimeError(
                f"kmer_completeness.sh finished without writing {ctx.tol_id}.qv and "
                f"{ctx.tol_id}.completeness.stats to {run_dir}; see {script_log}, merqury.*"
            )
        _run(
            f"mkdir -p {qv_dir} && cp {run_dir}/{ctx.tol_id}.* {run_dir}/merqury.* {qv_dir}/",
            ctx.print_only,
        )
    except Exception:
        log.error("qv failed; logs in %s", run_dir)
        if ctx.tracker:
            ctx.tracker.finish("qv", run_dir, "failed", untracked=ctx.untracked)
        raise

    if ctx.tracker:
        ctx.tracker.finish("qv", run_dir, "success", outputs=outputs, untracked=ctx.untracked)

    print_done(f"QV analysis → {run_dir}, copied to {qv_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("qv", cls=GritCommand)
@click.pass_context
def qv_cmd(ctx):
    """Run QV and k-mer completeness analysis; waits for the MerquryFK job."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_qv(curation_ctx)
    except Exception:
        log.exception("qv failed")
        raise SystemExit(1)
