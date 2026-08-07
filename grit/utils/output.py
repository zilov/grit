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


def print_curation_results(tracker, workdir, tol_id: str, curated_dir=None) -> None:
    """Print a 'Curation Results' panel with data parsed from step output files."""
    from grit.utils.result_parsers import collect_curation_results

    r = collect_curation_results(tracker, workdir, tol_id, curated_dir=curated_dir)
    if not r.has_any():
        return

    lines = []

    if r.autosomes is not None:
        lines.append(f"[bold]Autosomes    :[/bold] {r.autosomes}")
    if r.allosomes:
        lines.append(f"[bold]Allosomes    :[/bold] {r.allosomes}")

    if r.cuts is not None:
        lines.append(f"[bold]Curation     :[/bold] {r.breaks} breaks, {r.cuts + r.joins} joins")

    if r.sex_matches:
        matches_str = "  ".join(f"{s} ({c})" for s, c in r.sex_matches)
        lines.append(f"[bold]Sex matches  :[/bold] {matches_str}")

    if r.completeness_text:
        lines.append(f"[bold]Completeness :[/bold]\n{r.completeness_text}")

    if r.qv_text:
        lines.append(f"[bold]QV           :[/bold]\n{r.qv_text}")

    console.print("\n".join(lines))
