"""Optional pre-curation step: run sex_matcher."""

import glob
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run
from grit.utils.output import (
    console,
    print_done,
    print_info,
    print_step_header,
    print_warning,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# tol_id prefixes that typically require sex-matching (insects and similar)
_INSECT_PREFIXES = ("ic", "il", "id")


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_sex_matcher(ctx: CurationContext) -> None:
    """
    Runs sex_matcher (``sex`` command) in the workdir and prints the BUSCO summary.

    Applicable for insects and similar clades (tol_id starting with ``ic``, ``il``,
    ``id``, ``in``).  A reminder is printed for other taxa but the step still runs.

    Notebook source: ``pre_and_post_curation()`` — sex-matcher section.

    Steps:
        1. Print a reminder if the tol_id does not start with a known insect prefix.
        2. Build and print the command::

               cd {ctx.workdir} && sex

        3. Execute the command (unless print_only).
        4. Glob for ``Best_match*`` output files in ``ctx.workdir``.
        5. If found, call ``_print_sex_summary()`` to display the first 10 lines
           of the BUSCO table.

    Prints:
        Step header, sex command, BUSCO summary table (if available).
    """
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run sex-matcher")

    tol_id_lower = ctx.tol_id.lower()
    if not any(tol_id_lower.startswith(p) for p in _INSECT_PREFIXES):
        print_warning(
            f"tol_id '{ctx.tol_id}' does not start with a known insect prefix "
            f"({', '.join(_INSECT_PREFIXES)}). "
            "Sex-matcher is primarily used for insects — verify this is intentional."
        )

    cmd = f"cd {ctx.workdir} && sex"
    _run(cmd, print_only=ctx.print_only)

    if not ctx.print_only:
        # Look for the Best_match* output file produced by sex_matcher
        matches = glob.glob(str(ctx.workdir / "Best_match*"))
        if matches:
            best_match = Path(sorted(matches)[0])
            print_info("Best match file", str(best_match))
            _print_sex_summary(best_match)
        else:
            print_warning(
                f"No Best_match* file found in {ctx.workdir}. "
                "Sex-matcher may not have produced output yet — "
                "re-run after the job completes."
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
    run_sex_matcher(curation_ctx)
