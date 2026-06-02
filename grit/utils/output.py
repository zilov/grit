"""Pipeline step output formatting via rich."""

from rich.console import Console
from rich.panel import Panel

console = Console()


def print_step_header(ticket_id: str, tol_id: str, step_name: str) -> None:
    """Prints a step header in the project's canonical style."""
    title = f"  {ticket_id} | {tol_id} | Step: {step_name}  "
    console.print(Panel(title, style="bold cyan"))


def print_info(label: str, value: str) -> None:
    console.print(f"  [bold]{label:<16}[/bold]: {value}")


def print_command(description: str, cmd: str) -> None:
    console.print(f"\n[yellow]{description}:[/yellow]")
    console.print(f"  [green]{cmd}[/green]")


def print_next_step(func_name: str) -> None:
    console.print(f"\n[dim]Next step: {func_name}[/dim]")


def print_done(message: str) -> None:
    console.print(f"\n[bold green]Done:[/bold green] {message}")


def print_warning(message: str) -> None:
    console.print(f"[bold yellow]Warning:[/bold yellow] {message}")


def print_error(message: str) -> None:
    console.print(f"[bold red]Error:[/bold red] {message}")
