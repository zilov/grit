"""
Click-based CLI for the curation pipeline.

This is the new Click-based interface, allowing modular use of pipeline steps.
"""

import json
import logging
import sys
from pathlib import Path

import rich_click as click
import yaml
from rich.logging import RichHandler

from grit.core.context import CurationContext

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
        untracked: bool = False,
    ):
        self.verbose = verbose
        self.config_path = config_path or Path.home() / ".grit_curation_config.yaml"
        self.ticket = ticket
        self.yaml = yaml
        self.print_only = print_only
        self.logging_level = logging_level
        self.untracked = untracked


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
        untracked=getattr(state, "untracked", False),
    )


# Import and add commands (deferred to avoid circular imports)  # noqa: E402
from grit.steps.optional.blast_contaminants import blast_contaminants_cmd  # noqa: E402
from grit.steps.optional.busco_curated import busco_curated_cmd  # noqa: E402
from grit.steps.optional.busco_synteny import busco_synteny_cmd  # noqa: E402
from grit.steps.optional.fastga import fastga_cmd  # noqa: E402
from grit.steps.optional.rename_and_orient import rename_and_orient_cmd  # noqa: E402
from grit.steps.post_curation.finalize_qc import finalize_qc_cmd  # noqa: E402
from grit.steps.post_curation.haplotig_files import haplotig_files_cmd  # noqa: E402
from grit.steps.post_curation.post_processing import post_processing_cmd, pp_cmd  # noqa: E402
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
    from grit.core.status import show_global_status, show_ticket_history

    registry = RegistryManager()
    registry.refresh_statuses()

    if ticket:
        user_config = load_user_config(Path(ctx.obj.config_path))
        show_ticket_history(registry, ticket, user_config)
    else:
        show_global_status(registry)


@cli.command("_state-update", hidden=True)
@click.option("--workdir", required=True, type=click.Path(), help="Ticket workdir path.")
@click.option("--step", required=True, help="Step name.")
@click.option("--run-dir", "run_dir", required=True, type=click.Path(), help="Run dir path.")
@click.option("--status", "status", required=True, type=click.Choice(["success", "failed"]), help="Job outcome.")
@click.option("--job-id", "job_id", default=None, help="LSF job ID.")
def state_update_cmd(workdir, step, run_dir, status, job_id):
    """[Internal] Called by bsub -Ep epilogue to record job completion."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.utils.helpers import _get_step_specs, collect_outputs

    workdir_path = Path(workdir)
    tracker = RunTracker(workdir_path)
    outputs = None
    if status == "success":
        ticket = RegistryManager().find_ticket_by_workdir(workdir_path)
        if ticket:
            tol_id = ticket.get("tol_id", "")
            hap1 = ticket.get("hap1_prefix", "hap1")
            hap2 = ticket.get("hap2_prefix", "hap2")
            specs = _get_step_specs(step)
            if specs and tol_id:
                outputs = collect_outputs(specs, Path(run_dir), tol_id, hap1=hap1, hap2=hap2) or None
    tracker.finish(step, Path(run_dir), status, job_id=job_id, outputs=outputs)
    log.info(
        "_state-update: step=%s status=%s job_id=%s outputs=%s",
        step, status, job_id, list(outputs) if outputs else None,
    )


cli.add_command(sex_matcher_cmd)
cli.add_command(finalize_qc_cmd)
cli.add_command(post_processing_cmd)
cli.add_command(pp_cmd)
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


from grit.core.cleanup import cleanup_cmd  # noqa: E402

cli.add_command(cleanup_cmd)


@cli.command("untrack")
@click.option("--ticket", "-t", required=True, help="Ticket ID.")
@click.option("--step", "-s", required=True, help="Step name to untrack (e.g. rename_and_orient).")
@click.option("--undo", is_flag=True, default=False, help="Re-enable latest untracked run.")
@click.pass_context
def untrack_cmd(ctx, ticket, step, undo):
    """Mark the latest run of a step as non-canonical (or undo that)."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.utils.output import print_done

    reg = RegistryManager()
    entry = reg.find_ticket(ticket)
    if entry is None:
        click.echo(f"Ticket {ticket} not found in registry.", err=True)
        raise SystemExit(1)
    workdir = Path(entry["workdir"])
    tracker = RunTracker(workdir)
    if undo:
        runs = tracker.history(step)
        untracked_runs = [r for r in runs if r.get("status") == "untracked" and r.get("run_dir")]
        if not untracked_runs:
            click.echo(f"No untracked runs found for step {step!r}.", err=True)
            raise SystemExit(1)
        run_dir = Path(untracked_runs[-1]["run_dir"])
        success_before = [r for r in runs if r.get("status") == "success"
                         and r.get("run_dir") == str(run_dir)]
        outputs = success_before[-1].get("outputs") if success_before else None
        tracker.finish(step, run_dir, "success", outputs=outputs)
        print_done(f"Re-enabled {step!r} run: {run_dir.name}")
    else:
        if not tracker.untrack(step):
            click.echo(f"No successful run found for step {step!r} in {ticket}.", err=True)
            raise SystemExit(1)
        run_dir = tracker.latest_run_dir(step)
        console_hint = f" → canonical is now: {run_dir.name}" if run_dir else ""
        print_done(f"Untracked latest {step!r} run{console_hint}")


cli.add_command(untrack_cmd)


@cli.command("done")
@click.option("--ticket", "-t", required=True, help="Ticket ID to mark as done.")
@click.pass_context
def done_cmd(ctx, ticket):
    """Mark a curation ticket as done and remove it from the active list."""
    from grit.core.registry import RegistryManager
    from grit.utils.output import print_done

    reg = RegistryManager()
    entry = reg.find_ticket(ticket)
    if entry is None:
        click.echo(f"Ticket {ticket} not found in registry.", err=True)
        raise SystemExit(1)
    if entry.get("status") == "done":
        click.echo(f"{ticket} is already marked as done.")
        return
    reg.mark_done(ticket)
    print_done(f"{ticket} ({entry.get('tol_id', '')}) marked as done — removed from active list.")


@cli.command("reopen")
@click.option("--ticket", "-t", required=True, help="Ticket ID to reopen.")
@click.pass_context
def reopen_cmd(ctx, ticket):
    """Set a done ticket's status back to active curation."""
    from grit.core.registry import RegistryManager
    from grit.utils.output import print_done

    reg = RegistryManager()
    entry = reg.find_ticket(ticket)
    if entry is None:
        click.echo(f"Ticket {ticket} not found in registry.", err=True)
        raise SystemExit(1)
    if entry.get("status") != "done":
        click.echo(f"{ticket} is not marked as done (status: {entry.get('status')}).")
        return
    reg.update_status(ticket, "in_curation")
    print_done(f"{ticket} ({entry.get('tol_id', '')}) reopened — status set to in_curation.")


@cli.command("summary")
@click.pass_context
def summary_cmd(ctx):
    """Show ticket counts by status, and done-ticket counts by time period."""
    from grit.core.registry import RegistryManager
    from grit.core.status import show_summary

    show_summary(RegistryManager())


@cli.command("migrate-tracker")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be migrated without writing.")
@click.option("--yes", is_flag=True, default=False, help="Actually migrate (required unless --dry-run).")
@click.option("--from-registry", type=click.Path(exists=True), default=None,
              help="Import tickets from an existing registry JSON file before migrating steps.")
def migrate_tracker_cmd(dry_run, yes, from_registry):
    """Migrate per-ticket runs.jsonl files into registry steps array.

    Use --from-registry to seed from an existing registry.json (e.g. the old one)
    before populating steps from runs.jsonl files.
    """
    from grit.core.registry import RegistryManager

    if not dry_run and not yes:
        click.echo("Pass --yes to actually migrate, or --dry-run to preview.", err=True)
        raise SystemExit(1)

    reg = RegistryManager()

    # Seed from an existing registry file (e.g. old registry.json)
    if from_registry:
        source_path = Path(from_registry)
        try:
            source_tickets = json.loads(source_path.read_text())
        except Exception as exc:
            click.echo(f"Could not read {source_path}: {exc}", err=True)
            raise SystemExit(1)
        imported = 0
        for ticket in source_tickets:
            tid = ticket.get("ticket_id", "?")
            workdir = ticket.get("workdir")
            if not workdir:
                continue
            if dry_run:
                click.echo(f"Would import {tid} ({workdir})")
            else:
                reg.add_ticket(
                    tid,
                    ticket.get("tol_id", ""),
                    ticket.get("species", ""),
                    Path(workdir),
                    status=ticket.get("status", "in_curation"),
                    hap1_prefix=ticket.get("hap1_prefix", "hap1"),
                    hap2_prefix=ticket.get("hap2_prefix", "hap2"),
                )
            imported += 1
        click.echo(f"{'[dry-run] ' if dry_run else ''}Imported {imported} ticket(s) from {source_path.name}.")

    all_tickets = reg._load()
    migrated = 0
    skipped = 0

    for ticket in all_tickets:
        ticket_id = ticket.get("ticket_id", "?")
        workdir = Path(ticket["workdir"])
        if ticket.get("steps"):
            log.debug("migrate-tracker: %s already has steps, skipping", ticket_id)
            skipped += 1
            continue
        runs_log = workdir / ".grit" / "runs.jsonl"
        if not runs_log.exists():
            log.debug("migrate-tracker: %s has no runs.jsonl", ticket_id)
            skipped += 1
            continue
        records = [
            json.loads(line)
            for line in runs_log.read_text().splitlines()
            if line.strip()
        ]
        if dry_run:
            click.echo(f"Would migrate {len(records)} step record(s) for {ticket_id} ({workdir})")
        else:
            for record in records:
                reg.append_step(workdir, record)
            log.info("migrate-tracker: migrated %d records for %s", len(records), ticket_id)
        migrated += 1

    summary = f"{'[dry-run] ' if dry_run else ''}Migrated steps for {migrated} ticket(s), skipped {skipped}."
    click.echo(summary)


if __name__ == "__main__":
    cli()
