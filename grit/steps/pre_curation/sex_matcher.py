"""Optional pre-curation step: run sex_matcher."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _state_update_epilogue, _submit_bsub, build_bsub_opts, require_workdir
from grit.utils.modules import module_cmd
from grit.utils.output import (
    console,
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# tol_id prefixes that typically require sex-matching (insects and similar)
_INSECT_PREFIXES = ("ic", "il", "id")

# Absolute path to the sex_matcher shell script on the farm
_SEX_MATCHER_SCRIPT = "/software/grit/projects/vgp_curation_scripts/sex_matcher.sh"


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_sex_matcher(ctx: CurationContext) -> None:
    """
    Runs sex_matcher (``sex`` command) in the workdir and prints the BUSCO summary.

    Applicable for insects and similar clades (tol_id starting with ``ic``, ``il``,
    ``id``).  Aborts with an error if the tol_id does not match a known insect prefix.

    Notebook source: ``pre_and_post_curation()`` — sex-matcher section.

    Steps:
        1. Print a reminder if the tol_id does not start with a known insect prefix.
        2. Create symlink ``sex_matcher/{timestamp}/original.fa → workdir/original.fa``
           so that sex_matcher.sh finds the assembly in its working directory.
        3. Submit via bsub::

               bsub -q normal -n 32 -G team135 -e {workdir}/sex_matcher.err -o {workdir}/sex_matcher.out \\
                    -M 80000 -R'select[mem>80000] rusage[mem=80000] span[hosts=1]' \\
                    "cd {run_dir} && /software/grit/projects/vgp_curation_scripts/sex_matcher.sh"

        4. Execute the command (unless print_only).
        4. Glob for ``Best_match*`` output files in ``ctx.workdir``.
        5. If found, call ``_print_sex_summary()`` to display the first 10 lines
           of the BUSCO table.

    Prints:
        Step header, sex command, BUSCO summary table (if available).
    """
    log.info("sex-matcher | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run sex-matcher")

    tol_id_lower = ctx.tol_id.lower()
    if not any(tol_id_lower.startswith(p) for p in _INSECT_PREFIXES):
        log.error(
            "tol_id '%s' does not start with a known insect prefix (%s). "
            "Sex-matcher is only for insects — aborting.",
            ctx.tol_id,
            ", ".join(_INSECT_PREFIXES),
        )
        raise SystemExit(1)

    require_workdir(ctx)

    run_dir = ctx.tracker.start("sex_matcher", ctx.ticket_id, ctx.tol_id) if ctx.tracker else None
    work_dir = run_dir if run_dir else ctx.workdir

    if not ctx.print_only and run_dir:
        symlink = run_dir / "original.fa"
        if not symlink.exists():
            symlink.symlink_to(ctx.workdir / "original.fa")
    else:
        log.info("ln -s %s/original.fa %s/original.fa", ctx.workdir, work_dir)

    bsub_opts = build_bsub_opts(
        memory_mb=80000,
        cores=32,
        group="team135",
        output=str(ctx.workdir / "sex_matcher.out"),
        error=str(ctx.workdir / "sex_matcher.err"),
    )
    inner_cmd = f"{module_cmd('GRIT')} && cd {work_dir} && {_SEX_MATCHER_SCRIPT}"
    epilogue = _state_update_epilogue(ctx.workdir, "sex_matcher", run_dir) if run_dir else None
    job_id = _submit_bsub(inner_cmd, bsub_opts, ctx.print_only, epilogue_cmd=epilogue)

    if ctx.tracker and run_dir and job_id:
        ctx.tracker.record_job("sex_matcher", run_dir, job_id)

    if not ctx.print_only:
        # Look for the Best_match* output file produced by sex_matcher
        matches = glob.glob(str(ctx.workdir / "Best_match*"))
        if matches:
            best_match = Path(sorted(matches)[0])
            log.info("Best match file: %s", best_match)
            _print_sex_summary(best_match)
        else:
            log.warning(
                "No Best_match* file found in %s. "
                "Sex-matcher may not have produced output yet — "
                "re-run after the job completes.",
                ctx.workdir,
            )

    print_done("Sex-matcher step complete.")


def _print_sex_summary(busco_table_path: Path) -> None:
    """
    Prints the first 10 lines of a BUSCO sex-matcher output table.

    Notebook source: ``print_sex_summary()`` function.

    Args:
        busco_table_path: Path to the Best_match* file produced by sex_matcher.
    """
    console.print("\n[bold cyan]Sex-matcher BUSCO summary (first 10 lines):[/bold cyan]")
    with open(busco_table_path) as fh:
        for i, line in enumerate(fh):
            if i >= 10:
                break
            console.print(line.rstrip())


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("sex-matcher", cls=GritCommand)
@click.pass_context
def sex_matcher_cmd(ctx):
    """Run sex-matcher for insect curation."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        run_sex_matcher(curation_ctx)
    except Exception:
        log.exception("sex-matcher failed")
        raise SystemExit(1)
