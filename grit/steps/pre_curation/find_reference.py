"""Find and download closest reference genome."""

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _clean_species_name, _run
from grit.utils.modules import module_cmd
from grit.utils.output import (
    print_done,
    print_step_header,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_GET_NEAREST_COMPARATOR = "/software/grit/projects/vgp_curation_scripts/get_nearest_comparator.rb"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def reheader_reference(ctx: CurationContext, raw: Path, *, remove_raw: bool = False) -> Path:
    """
    Reheader a single reference FASTA with the GRIT ``reheader`` tool (gunzipping
    first if needed) and return the resulting ``{prefix}_reheader.fna`` path.
    Skips the work if that file already exists.

    ``remove_raw`` deletes the (decompressed) source file afterwards — used for
    references we downloaded ourselves, never for a user-supplied ``--reference-path``.
    """
    ref_prefix = raw.stem.split(".")[0].removesuffix("_reheader")
    ref_reheader = raw.parent / f"{ref_prefix}_reheader.fna"
    if ref_reheader.exists():
        log.info("Reheadered reference already exists — skipping prep: %s", ref_reheader)
        return ref_reheader

    if raw.suffix == ".gz":
        unzipped = raw.with_suffix("")
        cmd = f"gunzip {raw} && reheader {unzipped} > {ref_reheader}"
        if remove_raw:
            cmd += f" && rm {unzipped}"
    else:
        cmd = f"reheader {raw} > {ref_reheader}"
        if remove_raw:
            cmd += f" && rm {raw}"
    _run(f"{module_cmd('GRIT')} && {cmd}", ctx.print_only)
    return ref_reheader


def _reheader_downloaded_references(ctx: CurationContext, run_dir: Path) -> None:
    """
    Reheader every reference FASTA get_nearest_comparator.rb just downloaded into
    ``run_dir``, removing the raw files afterwards — so only
    ``{prefix}_reheader.fna`` remains. fastga and busco-synteny both consume that
    file directly and no longer prepare it themselves.
    """
    raw_matches = set()
    for pattern in ("*.fa.gz", "*.fna.gz", "*.fa", "*.fna"):
        raw_matches.update(glob.glob(str(run_dir / pattern)))
    raw_paths = sorted(Path(p) for p in raw_matches if not p.endswith("_reheader.fna"))

    for raw in raw_paths:
        reheader_reference(ctx, raw, remove_raw=True)


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

    species_query = _clean_species_name(ctx.species)
    log.info("Species (raw): %s", ctx.species)
    log.info("Species (query): %s", species_query)

    run_dir = ctx.tracker.start("find_reference", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked) if ctx.tracker else ctx.workdir / "find_reference" / "untracked"
    log.info("Reference dir: %s", run_dir)
    cmd = (
        f"mkdir -p {run_dir} && "
        f"cd {run_dir} && "
        f'{_GET_NEAREST_COMPARATOR} -s "{species_query}" -d -n {number}'
    )
    try:
        _run(cmd, ctx.print_only)
        _reheader_downloaded_references(ctx, run_dir)
        if ctx.tracker and run_dir:
            ctx.tracker.finish("find_reference", run_dir, "success")
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("find_reference", run_dir, "failed")
        raise
    print_done(f"Reference downloaded to {run_dir}")


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
