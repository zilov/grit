"""Pipeline step output formatting via rich."""

from rich.console import Console
from rich.panel import Panel

console = Console()


def print_step_header(ticket_id: str, tol_id: str, step_name: str) -> None:
    """Prints a step header in the project's canonical style."""
    title = f"  {ticket_id} | {tol_id} | Step: {step_name}  "
    console.print(Panel(title, style="bold cyan"))


def print_next_step(func_name: str) -> None:
    console.print(f"\n[dim]Next step: {func_name}[/dim]")


def print_done(message: str) -> None:
    console.print(f"\n[bold green]Done:[/bold green] {message}")


def print_tip(message: str) -> None:
    console.print(f"\n[bold yellow]Tip:[/bold yellow] {message}")


def print_curation_results(tracker, workdir, tol_id: str) -> None:
    """Print a 'Curation Results' panel with data parsed from step output files."""
    from grit.utils.result_parsers import collect_curation_results

    r = collect_curation_results(tracker, workdir, tol_id)
    if not r.has_any():
        return

    lines = []

    if r.chromosomes_total is not None:
        chrom_str = f"{r.chromosomes_total} chromosomes"
        if r.sex_chromosomes:
            chrom_str += f", sex: {', '.join(r.sex_chromosomes)}"
        lines.append(f"[bold]Chromosomes  :[/bold] {chrom_str}")

    if r.cuts is not None:
        lines.append(
            f"[bold]Curation     :[/bold] {r.cuts} cuts, {r.breaks} breaks, {r.joins} joins"
        )

    if r.sex_matches:
        matches_str = "  ".join(f"{s} ({c})" for s, c in r.sex_matches)
        lines.append(f"[bold]Sex matches  :[/bold] {matches_str}")

    if r.qv_rows:
        qv_str = "  ".join(f"{asm}={qv}" for asm, qv in r.qv_rows)
        lines.append(f"[bold]QV           :[/bold] {qv_str}")

    if r.completeness_rows:
        comp_str = "  ".join(f"{asm}={pct}%" for asm, pct in r.completeness_rows)
        lines.append(f"[bold]Completeness :[/bold] {comp_str}")

    console.print(Panel("\n".join(lines), title="Curation Results", border_style="cyan"))
