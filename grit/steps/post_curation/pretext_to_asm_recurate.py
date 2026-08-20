"""Step: re-run pretext-to-asm on a curated remapped Hi-C map ("curation of curated map")."""

from __future__ import annotations

import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core
from grit.utils.helpers import find_canonical_fa, find_canonical_haplotigs
from grit.utils.output import print_step_header, print_tip

log = logging.getLogger(__name__)

_RECURATE_TIP = (
    "This uses the current canonical FASTA as input. The recuration output "
    "is one entry in the flat mtime pool — freshest tracked output wins. "
    "If you want the recurate output to remain canonical, avoid rerunning "
    "blast-contaminants, rename-and-orient, or microchromosome-combine "
    "afterward — doing so will make their output canonical instead, a "
    "supported forward-chain, not an error (no grit untrack needed).\n"
    "To remove this recurate output from the pool entirely: "
    "grit untrack --step {step_name} -t <ticket>"
)

_NEW_HAPLOTIGS_GLOBS = (
    "*.additional_haplotigs.curated.fa",
    "*.all_haplotigs.curated.fa",
    "*.haplotigs.fa",
)


def _merged_haplotigs_name(ctx: CurationContext, hap_prefix: str) -> str:
    """Filename for the merged (prior + new) haplotig FASTA of one haplotype."""
    return f"{ctx.tol_id}.{hap_prefix}.{ctx.release_version}.all_haplotigs.curated.fa"


def _output_specs_for_hap(
    ctx: CurationContext, hap_prefix: str
) -> list[tuple[str, str, list[str]]]:
    return [
        # hap-qualified naming first; the primary/unprefixed pattern below is only
        # tried if this found nothing (collect_outputs dedups by key).
        (
            f"{hap_prefix}_fa",
            f"{{tol_id}}.{hap_prefix}.*.curated.fa",
            ["all_haplotigs", "additional_haplotigs"],
        ),
        (
            f"{hap_prefix}_fa",
            "{tol_id}.*.primary.curated.fa",
            ["hap1", "hap2", "all_haplotigs", "additional_haplotigs"],
        ),
        (f"{hap_prefix}_chr_list", "{tol_id}.*.primary.chromosome.list.csv", []),
        (f"{hap_prefix}_haplotigs", _merged_haplotigs_name(ctx, hap_prefix), []),
    ]


def _merge_haplotigs_transform(merged_name: str, prior_haplotigs: Path | None):
    """Build the output_transform hook that merges haplotigs before collect_outputs runs."""

    def _transform(run_dir: Path) -> None:
        new_matches: list[Path] = []
        for pattern in _NEW_HAPLOTIGS_GLOBS:
            new_matches = sorted(run_dir.glob(pattern))
            if new_matches:
                break
        new_haplotigs = new_matches[-1] if new_matches else None

        prior_nonempty = bool(
            prior_haplotigs and prior_haplotigs.exists() and prior_haplotigs.stat().st_size > 0
        )
        new_nonempty = bool(
            new_haplotigs and new_haplotigs.exists() and new_haplotigs.stat().st_size > 0
        )

        if not prior_nonempty and not new_nonempty:
            return  # nothing to track

        merged_path = run_dir / merged_name
        if prior_nonempty and new_nonempty:
            merged_path.write_text(prior_haplotigs.read_text() + new_haplotigs.read_text())
        elif prior_nonempty:
            merged_path.write_text(prior_haplotigs.read_text())
        else:
            merged_path.write_text(new_haplotigs.read_text())

    return _transform


def run_pretext_to_asm_recurate(ctx: CurationContext, hap_prefix: str, step_name: str) -> Path:
    """
    Re-runs pretext-to-asm for one haplotype using the current canonical FASTA
    as input and a hap-qualified AGP from ``{workdir}/recurate/``.

    Merges haplotigs with whatever was canonical for this haplotype before
    this run (plain FASTA concatenation) — see ``_merge_haplotigs_transform``.

    Tracked under *step_name* (``pretext_to_asm_recurate`` for hap1,
    ``pretext_to_asm_recurate_hap2`` for hap2) so each haplotype's recuration
    status is fully independent.
    """
    log.info(
        "pretext-to-asm-recurate | ticket=%s tol_id=%s hap=%s",
        ctx.ticket_id,
        ctx.tol_id,
        hap_prefix,
    )
    print_step_header(ctx.ticket_id, ctx.tol_id, f"Pretext to ASM recurate ({hap_prefix})")
    print_tip(_RECURATE_TIP.format(step_name=step_name))

    prior_haplotigs: Path | None = None
    try:
        prior_haplotigs = find_canonical_haplotigs(ctx, hap_prefix)
    except FileNotFoundError:
        prior_haplotigs = None

    original_fa = find_canonical_fa(ctx, hap_prefix)
    agp_search_dir = ctx.workdir / "recurate"
    if not ctx.print_only:
        agp_search_dir.mkdir(parents=True, exist_ok=True)
    print_tip(
        "Expected AGP location and naming for this step:\n"
        f"[bold cyan]{agp_search_dir}/{ctx.tol_id}.{hap_prefix}.recurate.agp[/bold cyan]\n"
        f"(any filename matching {ctx.tol_id}*{hap_prefix}*.agp* works)"
    )

    merged_name = _merged_haplotigs_name(ctx, hap_prefix)
    run_dir = _run_pretext_to_asm_core(
        ctx,
        step_name,
        original_fa,
        f"No canonical FASTA found for {hap_prefix!r}. Run pretext-to-asm first.",
        agp_search_dir,
        f"{ctx.tol_id}.fa",
        _output_specs_for_hap(ctx, hap_prefix),
        agp_glob=f"{ctx.tol_id}*{hap_prefix}*.agp*",
        output_transform=_merge_haplotigs_transform(merged_name, prior_haplotigs),
    )

    # A missing FASTA output would silently leave canonical resolution pointing at
    # pre-recuration data while this step reports success — fail loudly instead.
    if not ctx.print_only and ctx.tracker:
        if not ctx.tracker.get_output(step_name, f"{hap_prefix}_fa"):
            raise FileNotFoundError(
                f"pretext-to-asm-recurate produced no curated FASTA for {hap_prefix!r} in "
                f"{run_dir}. Expected {ctx.tol_id}.{hap_prefix}.*.curated.fa or "
                f"{ctx.tol_id}.*.primary.curated.fa — canonical file resolution would "
                "silently fall back to pre-recuration output."
            )

    return run_dir


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("pretext-to-asm-recurate", cls=GritCommand)
@click.option(
    "--hap2",
    "run_hap2",
    is_flag=True,
    default=False,
    help="Recurate hap2 instead of hap1.",
)
@click.pass_context
def pretext_to_asm_recurate_cmd(ctx, run_hap2):
    """Re-run pretext-to-asm on a curated remapped Hi-C map."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    hap_prefix = curation_ctx.hap2_prefix if run_hap2 else curation_ctx.hap1_prefix
    step_name = "pretext_to_asm_recurate_hap2" if run_hap2 else "pretext_to_asm_recurate"
    try:
        run_pretext_to_asm_recurate(curation_ctx, hap_prefix, step_name)
    except Exception:
        log.exception("pretext-to-asm-recurate failed")
        raise SystemExit(1)
