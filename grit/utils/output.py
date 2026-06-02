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
