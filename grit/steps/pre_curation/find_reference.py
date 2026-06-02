"""Find and download closest reference genome."""

import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _clean_species_name, _run
from grit.utils.output import (
    print_done,
    print_info,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_GET_NEAREST_COMPARATOR = "/software/grit/projects/vgp_curation_scripts/get_nearest_comparator.rb"


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def find_closest_reference(ctx: CurationContext, number: int = 1) -> None:
    """
    Finds (and downloads) the closest reference genome from NCBI for the
    species being curated.

    The reference FASTA is downloaded into ``{ctx.workdir}/reference/``.
    The script must be run from that directory, so we ``cd`` into it first.

    Command::

        mkdir -p {ctx.workdir}/reference && \\
        cd {ctx.workdir}/reference && \\
        /software/grit/projects/vgp_curation_scripts/get_nearest_comparator.rb \\
            -s "{ctx.species}" -d -n {number}

    Prints:
        Step header, command executed, path to reference directory.
    """
    log.info("find-reference | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Find closest reference")

    ref_dir = ctx.workdir / "reference"
    species_query = _clean_species_name(ctx.species)
    print_info("Reference dir", str(ref_dir))
    print_info("Species (raw)", ctx.species)
    print_info("Species (query)", species_query)

    cmd = (
        f"mkdir -p {ref_dir} && "
        f"cd {ref_dir} && "
        f'{_GET_NEAREST_COMPARATOR} -s "{species_query}" -d -n {number}'
    )
    _run(cmd, ctx.print_only)
    print_done(f"Reference downloaded to {ref_dir}")


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------


@click.command("find-reference", cls=GritCommand)
@click.pass_context
def find_reference_cmd(ctx):
    """Find and download closest reference genome."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        find_closest_reference(curation_ctx)
    except Exception:
        log.exception("find-reference failed")
        raise SystemExit(1)
