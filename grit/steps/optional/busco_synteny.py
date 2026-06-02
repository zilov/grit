"""Run BUSCO synteny analysis."""

import glob
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.utils.helpers import _run, _submit_bsub
from grit.utils.output import (
    print_done,
    print_info,
    print_step_header,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REHEADER_SCRIPT = "/software/grit/projects/vgp_curation_scripts/reheader_fna.py"
_BUSCO_SYNTENY_SCRIPT = "/software/grit/projects/vgp_curation_scripts/busco_synteny.sh"


# ---------------------------------------------------------------------------
# Public step functions
# ---------------------------------------------------------------------------


def run_busco_synteny(ctx: CurationContext, lineage: str) -> None:
    """
    Runs BUSCO synteny analysis between the curated assembly and a reference genome.

    Steps:
        1. Ensure reference is available (download if needed).
        2. Prepare reference: gunzip, rename .fa to .fna, reheader, replace 'chr' with 'SUPER'.
        3. Find the curated hap1 FASTA as query.
        4. Submit BUSCO synteny job via bsub.

    Command structure:
        bsub -n 32 -o o_busco_synt -M 50G -R'select[mem>50G] rusage[mem=50G] span[hosts=1]' \\
            busco_synteny.sh -r <ref_fasta> -q <query_fasta> -l <lineage>

    Prints:
        Step header, reference preparation commands, bsub command.
    """
    print_step_header(ctx.ticket_id, ctx.tol_id, "Run BUSCO synteny")

    # --- ensure reference is available ---
    ref_dir = ctx.workdir / "reference"
    ref_patterns = [
        str(ref_dir / "*_reheader.fa"),
        str(ref_dir / "*_reheader.fna"),
        str(ref_dir / "*.fa"),
        str(ref_dir / "*.fna"),
        str(ref_dir / "*.fa.gz"),
        str(ref_dir / "*.fna.gz"),
    ]
    ref_path = None
    for pattern in ref_patterns:
        if ctx.print_only:
            ref_path = Path(pattern.replace("*", "GCA_example"))
            break
        matches = glob.glob(pattern)
        if matches:
            ref_path = Path(sorted(matches)[-1])
            break

    if ref_path is None or (not ctx.print_only and not ref_path.exists()):
        print_info("No reference found, downloading closest reference")
        from grit.steps.find_reference import find_closest_reference

        find_closest_reference(ctx)
        # After download, find again
        ref_matches = glob.glob(str(ref_dir / "*.fa.gz")) + glob.glob(str(ref_dir / "*.fa"))
        if not ref_matches:
            raise FileNotFoundError(f"No reference downloaded to {ref_dir}")
        ref_path = Path(sorted(ref_matches)[-1])

    print_info("Reference FASTA", str(ref_path))

    # --- prepare reference ---
    ref_prefix = ref_path.stem.split(".")[0]  # e.g., GCA123456
    ref_fna = ctx.workdir / f"{ref_prefix}.fna"
    ref_reheader = ctx.workdir / f"{ref_prefix}_reheader.fna"

    prep_cmds = []

    # gunzip if needed
    if ref_path.suffix == ".gz":
        gunzip_cmd = f"gunzip {ref_path}"
        prep_cmds.append(gunzip_cmd)
        ref_unzipped = ref_path.with_suffix("")
    else:
        ref_unzipped = ref_path

    # mv .fa to .fna if needed
    if ref_unzipped.suffix == ".fa":
        mv_cmd = f"mv {ref_unzipped} {ref_fna}"
        prep_cmds.append(mv_cmd)
    else:
        ref_fna = ref_unzipped

    # reheader
    reheader_cmd = f"python {_REHEADER_SCRIPT} {ref_fna}"
    prep_cmds.append(reheader_cmd)

    # sed to replace chr with SUPER
    sed_cmd = f"sed -i 's/chr/SUPER/g' {ref_reheader}"
    prep_cmds.append(sed_cmd)

    # Run preparation commands
    for cmd in prep_cmds:
        _run(cmd, ctx.print_only)

    print_info("Prepared reference", str(ref_reheader))

    # --- find query fasta (curated hap1) ---
    query_pattern = str(ctx.workdir / f"{ctx.tol_id}*{ctx.hap1_prefix}*.curated.fa")
    if ctx.print_only:
        query_fa = ctx.workdir / f"{ctx.tol_id}.{ctx.hap1_prefix}.primary.curated.fa"
    else:
        query_matches = glob.glob(query_pattern)
        if not query_matches:
            raise FileNotFoundError(f"No curated hap1 FASTA found: {query_pattern}")
        query_fa = Path(sorted(query_matches)[-1])
    print_info("Query FASTA", str(query_fa))

    # --- submit BUSCO synteny job ---
    inner_cmd = f"{_BUSCO_SYNTENY_SCRIPT} -r {ref_reheader} -q {query_fa} -l {lineage}"
    bsub_opts = "-n 32 -o o_busco_synt -M 50G -R'select[mem>50G] rusage[mem=50G] span[hosts=1]'"
    _submit_bsub(inner_cmd, bsub_opts, ctx.print_only)

    print_done("BUSCO synteny submitted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("busco-synteny", cls=GritCommand)
@click.option("--lineage", required=True, help="BUSCO lineage name (e.g. insecta_odb10).")
@click.pass_context
def busco_synteny_cmd(ctx, lineage):
    """Run BUSCO synteny analysis between curated assembly and reference genome."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    run_busco_synteny(curation_ctx, lineage)
