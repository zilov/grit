"""Blast chosen draft scaffolds with decon_fasta; canonical is not changed."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.steps.optional.blast_contaminants import DECON_SCRIPT, target_phylum
from grit.utils.helpers import _run, require_workdir
from grit.utils.modules import module_cmd
from grit.utils.output import print_done, print_step_header

log = logging.getLogger(__name__)


def parse_headers(value: str) -> list[str]:
    """Return headers from a file (one per line, blank/# ignored) or a comma-separated string."""
    path = Path(value)
    if path.is_file():
        lines = path.read_text().splitlines()
        return [h.strip() for h in lines if h.strip() and not h.strip().startswith("#")]
    return [h.strip() for h in value.split(",") if h.strip()]


def run_blast_target(ctx: CurationContext, headers: list[str]) -> None:
    """Blast the given original.fa scaffolds and write a taxonomy table + KEEP/REMOVE/NO_HIT BED."""
    log.info("blast-target | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Target blast")
    require_workdir(ctx)

    original = ctx.workdir / "original.fa"
    if not ctx.print_only and not original.exists():
        raise click.UsageError(f"{original} not found — run `grit setup -t {ctx.ticket_id}` first.")

    _run(f"{module_cmd('GRIT')} && samtools faidx {original}", ctx.print_only)
    if ctx.print_only:
        lengths = dict.fromkeys(headers, 0)
    else:
        fai = Path(f"{original}.fai").read_text().splitlines()
        lengths = {line.split("\t")[0]: int(line.split("\t")[1]) for line in fai if line}

    missing = [h for h in headers if h not in lengths]
    if missing:
        log.warning("Not in %s, skipped: %s", original.name, ", ".join(missing))
    found = [h for h in headers if h in lengths]
    if not found:
        log.warning("None of the requested headers are in %s — nothing to blast.", original)
        return

    run_dir = ctx.tracker.start("blast_target", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
    try:
        targets = run_dir / "targets.fa"
        _run(
            f"{module_cmd('GRIT')} && samtools faidx {original} {' '.join(found)} > {targets}",
            ctx.print_only,
        )
        phylum = target_phylum(ctx)
        blast_out_dir = run_dir / "blast_out_dir"
        _run(
            f"{module_cmd('GRIT')} && {DECON_SCRIPT} --fasta {targets} --outdir {blast_out_dir}",
            ctx.print_only,
        )
        if ctx.print_only:
            return

        taxonomy_txt = blast_out_dir / "taxonomy.txt"
        taxonomy = run_dir / f"{ctx.tol_id}.target_taxonomy.tsv"
        shutil.copy(taxonomy_txt, taxonomy)

        # decon_fasta writes hits best-first, so a scaffold's first line is its top hit.
        top: dict[str, str] = {}
        for line in taxonomy_txt.read_text().splitlines():
            if line.strip():
                top.setdefault(line.split()[0], line)

        bed = run_dir / f"{ctx.tol_id}.blast_target.bed"
        rows = []
        for h in found:
            verdict = "NO_HIT" if h not in top else "KEEP" if phylum in top[h] else "REMOVE"
            rows.append(f"{h}\t0\t{lengths[h]}\t{verdict}\n")
        bed.write_text("".join(rows))

        ctx.tracker.finish(
            "blast_target",
            run_dir,
            "success",
            outputs={"bed": str(bed), "taxonomy": str(taxonomy)},
            untracked=ctx.untracked,
        )
    except Exception:
        ctx.tracker.finish("blast_target", run_dir, "failed", untracked=ctx.untracked)
        raise

    print_done(f"Target blast → {bed}")


@click.command("blast-target", cls=GritCommand)
@click.option(
    "--headers",
    required=True,
    help="File with one header per line, or a quoted comma-separated list "
    "(original.fa names, any haplotype). Large scaffolds make the blast slow.",
)
@click.pass_context
def blast_target_cmd(ctx, headers):
    """Blast chosen draft scaffolds; canonical is not changed."""
    from grit.core.click_cli import build_context

    header_list = parse_headers(headers)
    if not header_list:
        raise click.UsageError("--headers is empty.")
    curation_ctx = build_context(ctx.obj)
    try:
        run_blast_target(curation_ctx, header_list)
    except click.UsageError:
        raise
    except Exception:
        log.exception("blast-target failed")
        raise SystemExit(1)
