"""
Click-based CLI for the curation pipeline.

This is the new Click-based interface, allowing modular use of pipeline steps.
"""

import logging
import sys
from pathlib import Path

import rich_click as click
import yaml
from rich.logging import RichHandler
from rich.table import Table

from grit.core.context import CurationContext
from grit.utils.output import console

log = logging.getLogger(__name__)


def configure_logging(logging_level: str) -> None:
    level = getattr(logging, logging_level.upper(), logging.INFO)
    show_path = level == logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(show_path=show_path, rich_tracebacks=True)],
    )


class GlobalState:
    """Global state for Click commands."""

    def __init__(
        self,
        verbose: bool = False,
        config_path: str = None,
        ticket: str = None,
        yaml: str = None,
        print_only: bool = False,
        logging_level: str = "INFO",
    ):
        self.verbose = verbose
        self.config_path = config_path or Path.home() / ".grit_curation_config.yaml"
        self.ticket = ticket
        self.yaml = yaml
        self.print_only = print_only
        self.logging_level = logging_level


@click.group()
@click.option("--verbose", is_flag=True, help="Enable verbose output.")
@click.option(
    "--config", "config_path", type=click.Path(exists=True), help="Path to user config YAML."
)
@click.option("--yaml", type=click.Path(exists=True), help="Path to YAML file")
@click.option("--print-only", is_flag=True, help="Print commands without executing")
@click.option(
    "--logging-level",
    "logging_level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging level.",
    show_default=True,
)
@click.pass_context
def cli(ctx, verbose, config_path, yaml, print_only, logging_level):
    """Curation pipeline CLI."""
    configure_logging(logging_level)
    ctx.ensure_object(dict)
    ctx.obj = GlobalState(
        verbose=verbose,
        config_path=config_path,
        yaml=yaml,
        print_only=print_only,
        logging_level=logging_level,
    )


def load_user_config(config_path: Path) -> dict:
    if not config_path.exists():
        click.echo(f"Error: User config not found: {config_path}", err=True)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def build_context(state: GlobalState) -> CurationContext:
    user_config = load_user_config(Path(state.config_path))
    yaml_override = None
    if state.yaml:
        yaml_file = Path(state.yaml)
        if not yaml_file.exists():
            click.echo(f"Error: YAML file not found: {yaml_file}", err=True)
            sys.exit(1)
        with open(yaml_file) as f:
            yaml_override = yaml.safe_load(f)
    return CurationContext.from_ticket(
        state.ticket,
        user_config,
        yaml_override=yaml_override,
        print_only=state.print_only,
    )


# Import and add commands (deferred to avoid circular imports)  # noqa: E402
from grit.steps.optional.blast_contaminants import blast_contaminants_cmd  # noqa: E402
from grit.steps.optional.busco_curated import busco_curated_cmd  # noqa: E402
from grit.steps.optional.busco_synteny import busco_synteny_cmd  # noqa: E402
from grit.steps.optional.fastga import fastga_cmd  # noqa: E402
from grit.steps.optional.rename_and_orient import rename_and_orient_cmd  # noqa: E402
from grit.steps.post_curation.finalize_qc import finalize_qc_cmd  # noqa: E402
from grit.steps.post_curation.haplotig_files import haplotig_files_cmd  # noqa: E402
from grit.steps.post_curation.hic_remapping import hic_remapping_cmd  # noqa: E402
from grit.steps.post_curation.post_curation import post_curation_cmd  # noqa: E402
from grit.steps.post_curation.pretext_to_asm import pretext_to_asm_cmd  # noqa: E402
from grit.steps.post_curation.qv import qv_cmd  # noqa: E402
from grit.steps.post_curation.validate_files import validate_files_cmd  # noqa: E402
from grit.steps.pre_curation.add_pretext_view_tracks import (  # noqa: E402
    add_bedgraph_track_cmd,
    add_gap_track_cmd,
    add_telo_track_cmd,
)
from grit.steps.pre_curation.find_reference import find_reference_cmd  # noqa: E402
from grit.steps.pre_curation.microchromosome import (  # noqa: E402
    microchromosome_cmd,
    microchromosome_post_cmd,
)
from grit.steps.pre_curation.setup import setup_cmd  # noqa: E402
from grit.steps.pre_curation.sex_matcher import sex_matcher_cmd  # noqa: E402

@cli.command("status")
@click.option("--ticket", "-t", default=None, help="Ticket ID for per-ticket step history.")
@click.pass_context
def status_cmd(ctx, ticket):
    """Show status of active curation tickets, or step history for a specific ticket."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.utils.helpers import _check_bjobs

    registry = RegistryManager()
    registry.refresh_statuses()

    if ticket:
        _show_ticket_history(registry, ticket)
    else:
        _show_global_status(registry)


def _show_global_status(registry) -> None:
    """Print table of all active tickets."""
    from grit.core.run_tracker import RunTracker
    from grit.utils.helpers import _check_bjobs

    tickets = registry.all_tickets()
    if not tickets:
        console.print("[dim]No active tickets. Run [bold]grit setup[/bold] to start curation.[/dim]")
        return

    table = Table(title="Active Curation Tickets", show_header=True, header_style="bold cyan")
    table.add_column("Ticket", style="bold")
    table.add_column("ToL ID")
    table.add_column("Species")
    table.add_column("Last Step")
    table.add_column("Last Run")
    table.add_column("Status", style="green")

    for t in tickets:
        workdir = Path(t["workdir"])
        last_step = ""
        last_run = ""
        if workdir.exists():
            tracker = RunTracker(workdir)
            history = tracker.history()
            if history:
                last_entry = history[-1]
                last_step = last_entry.get("step", "")
                last_run = last_entry.get("timestamp", "")
            status_display = t.get("status", "")
        else:
            status_display = "[red]workdir missing[/red]"
        table.add_row(
            t["ticket_id"],
            t.get("tol_id", ""),
            t.get("species", ""),
            last_step,
            last_run,
            status_display,
        )

    console.print(table)

    done = registry.done_tickets(limit=3)
    if done:
        console.print("\n[dim]Recently completed:[/dim]")
        for t in done:
            console.print(f"  [dim]{t['ticket_id']} ({t.get('tol_id', '')}) — {t.get('status', '')}[/dim]")


def _show_ticket_history(registry, ticket_id: str) -> None:
    """Print per-step run history for a single ticket."""
    from grit.core.run_tracker import RunTracker
    from grit.utils.helpers import _check_bjobs

    tickets = registry.all_tickets() + registry.done_tickets(limit=20)
    ticket = next((t for t in tickets if t["ticket_id"] == ticket_id), None)
    if ticket is None:
        console.print(f"[red]Ticket {ticket_id} not found in registry.[/red]")
        return

    workdir = Path(ticket["workdir"])
    if not workdir.exists():
        console.print(f"[yellow]Workdir not found: {workdir}[/yellow]")
        return

    tracker = RunTracker(workdir)
    history = tracker.history()

    # Poll bjobs for any pending jobs
    pending = tracker.pending_jobs()
    live_job_statuses: dict[str, str] = {}
    if pending:
        job_ids = [r["job_id"] for r in pending if r.get("job_id")]
        if job_ids:
            live_job_statuses = _check_bjobs(job_ids)

    # Aggregate by step: last run per step
    step_latest: dict[str, dict] = {}
    step_counts: dict[str, int] = {}
    for r in history:
        step = r.get("step", "")
        step_counts[step] = step_counts.get(step, 0) + 1
        step_latest[step] = r

    table = Table(
        title=f"Step history — {ticket_id} ({ticket.get('tol_id', '')})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Step")
    table.add_column("Runs", justify="right")
    table.add_column("Last Run")
    table.add_column("Status")
    table.add_column("Job ID")

    for step, entry in step_latest.items():
        status = entry.get("status", "")
        job_id = entry.get("job_id") or ""
        ts = entry.get("timestamp", "")

        # Enrich bsub job status from live bjobs query
        if status == "started" and job_id and job_id in live_job_statuses:
            bjobs_status = live_job_statuses[job_id]
            if bjobs_status in ("DONE",):
                status = "done (check)"
            elif bjobs_status == "EXIT":
                status = "failed (job exited)"
            elif bjobs_status in ("RUN", "PEND"):
                status = f"running ({bjobs_status})"
            elif bjobs_status == "gone":
                status = "unknown (gone)"

        style = ""
        if "success" in status:
            style = "green"
        elif "fail" in status or "EXIT" in status:
            style = "red"
        elif "running" in status or status == "started":
            style = "yellow"

        table.add_row(
            step,
            str(step_counts.get(step, 1)),
            ts,
            f"[{style}]{status}[/{style}]" if style else status,
            job_id,
        )

    console.print(table)


@cli.command("_state-update", hidden=True)
@click.option("--workdir", required=True, type=click.Path(), help="Ticket workdir path.")
@click.option("--step", required=True, help="Step name.")
@click.option("--run-dir", "run_dir", required=True, type=click.Path(), help="Run dir path.")
@click.option("--status", "status", required=True, type=click.Choice(["success", "failed"]), help="Job outcome.")
@click.option("--job-id", "job_id", default=None, help="LSF job ID.")
def state_update_cmd(workdir, step, run_dir, status, job_id):
    """[Internal] Called by bsub -Ep epilogue to record job completion."""
    from grit.core.run_tracker import RunTracker
    tracker = RunTracker(Path(workdir))
    tracker.finish(step, Path(run_dir), status, job_id=job_id)
    log.info("_state-update: step=%s status=%s job_id=%s", step, status, job_id)


cli.add_command(sex_matcher_cmd)
cli.add_command(finalize_qc_cmd)
cli.add_command(add_bedgraph_track_cmd)
cli.add_command(add_gap_track_cmd)
cli.add_command(add_telo_track_cmd)
cli.add_command(find_reference_cmd)
cli.add_command(microchromosome_cmd)
cli.add_command(microchromosome_post_cmd)
cli.add_command(setup_cmd)
cli.add_command(haplotig_files_cmd)
cli.add_command(hic_remapping_cmd)
cli.add_command(post_curation_cmd)
cli.add_command(pretext_to_asm_cmd)
cli.add_command(qv_cmd)
cli.add_command(validate_files_cmd)
cli.add_command(blast_contaminants_cmd)
cli.add_command(busco_curated_cmd)
cli.add_command(busco_synteny_cmd)
cli.add_command(fastga_cmd)
cli.add_command(rename_and_orient_cmd)


if __name__ == "__main__":
    cli()
