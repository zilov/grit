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
        dry_run: bool = False,
        logging_level: str = "INFO",
        untracked: bool = False,
        bsub_ram: int | None = None,
    ):
        self.verbose = verbose
        self.config_path = config_path or Path.home() / ".grit" / "grit_curation_config.yaml"
        self.ticket = ticket
        self.yaml = yaml
        self.print_only = print_only
        self.dry_run = dry_run
        self.logging_level = logging_level
        self.untracked = untracked
        self.bsub_ram = bsub_ram


@click.group()
@click.version_option(package_name="grit")
@click.option("--verbose", is_flag=True, help="Enable verbose output.")
@click.option(
    "--config", "config_path", type=click.Path(exists=True), help="Path to user config YAML."
)
@click.option("--yaml", type=click.Path(exists=True), help="Path to YAML file")
@click.option("--print-only", is_flag=True, help="Print commands without executing")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Create placeholder outputs and mark steps done, without running any real "
    "command (for testing pipeline/tracking logic).",
)
@click.option(
    "--logging-level",
    "logging_level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging level.",
    show_default=True,
)
@click.pass_context
def cli(ctx, verbose, config_path, yaml, print_only, dry_run, logging_level):
    """Curation pipeline CLI."""
    configure_logging(logging_level)
    ctx.ensure_object(dict)
    ctx.obj = GlobalState(
        verbose=verbose,
        config_path=config_path,
        yaml=yaml,
        print_only=print_only,
        dry_run=dry_run,
        logging_level=logging_level,
    )


def load_user_config(config_path: Path) -> dict:
    if not config_path.exists():
        click.echo(f"Error: User config not found: {config_path}", err=True)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_yaml_override(state: GlobalState) -> dict | None:
    """Load the group-level --yaml FILE override, or None when not set."""
    if not state.yaml:
        return None
    yaml_file = Path(state.yaml)
    if not yaml_file.exists():
        click.echo(f"Error: YAML file not found: {yaml_file}", err=True)
        sys.exit(1)
    with open(yaml_file) as f:
        return yaml.safe_load(f)


def build_context(state: GlobalState) -> CurationContext:
    user_config = load_user_config(Path(state.config_path))
    yaml_override = load_yaml_override(state)
    return CurationContext.from_ticket(
        state.ticket,
        user_config,
        yaml_override=yaml_override,
        print_only=state.print_only,
        dry_run=state.dry_run,
        untracked=getattr(state, "untracked", False),
        bsub_ram=getattr(state, "bsub_ram", None),
    )


# Import and add commands (deferred to avoid circular imports)  # noqa: E402
from grit.steps.optional.blast_contaminants import blast_contaminants_cmd  # noqa: E402
from grit.steps.optional.busco_curated import busco_curated_cmd  # noqa: E402
from grit.steps.optional.busco_synteny import busco_synteny_cmd  # noqa: E402
from grit.steps.optional.fastga import fastga_cmd, fastga_stats_cmd  # noqa: E402
from grit.steps.optional.fastga_synteny import fastga_synteny_cmd  # noqa: E402
from grit.steps.optional.rename_and_orient import rename_and_orient_cmd  # noqa: E402
from grit.steps.optional.super_to_scaffold import super_to_scaffold_cmd  # noqa: E402
from grit.steps.post_curation.finalize_qc import finalize_qc_cmd  # noqa: E402
from grit.steps.post_curation.haplotig_files import haplotig_files_cmd  # noqa: E402
from grit.steps.post_curation.hic_remapping import hic_remapping_cmd  # noqa: E402
from grit.steps.post_curation.microchromosome_combine import (  # noqa: E402
    microchromosome_combine_cmd,
)
from grit.steps.post_curation.post_curation import post_curation_cmd  # noqa: E402
from grit.steps.post_curation.post_curation_recurate import (  # noqa: E402
    post_curation_recurate_cmd,
)
from grit.steps.post_curation.post_processing import post_processing_cmd, pp_cmd  # noqa: E402
from grit.steps.post_curation.pretext_to_asm import pretext_to_asm_cmd  # noqa: E402
from grit.steps.post_curation.pretext_to_asm_recurate import (  # noqa: E402
    pretext_to_asm_recurate_cmd,
)
from grit.steps.post_curation.qv import qv_cmd  # noqa: E402

# Not yet tested via CLI / not current — disabled for initial release.
# from grit.steps.post_curation.validate_files import validate_files_cmd  # noqa: E402
# from grit.steps.pre_curation.add_pretext_view_tracks import (  # noqa: E402
#     add_bedgraph_track_cmd,
#     add_gap_track_cmd,
#     add_telo_track_cmd,
# )
from grit.steps.pre_curation.find_reference import find_reference_cmd  # noqa: E402
from grit.steps.pre_curation.microchromosome_second_shot import (  # noqa: E402
    microchromosome_second_shot_cmd,
)
from grit.steps.pre_curation.setup import setup_cmd  # noqa: E402
from grit.steps.pre_curation.sex_matcher import sex_matcher_cmd  # noqa: E402


@cli.command("init")
def init_cmd():
    """Create ~/.grit/grit_curation_config.yaml, pre-filled with your username."""
    import getpass

    from grit.config.init import DEFAULT_CONFIG_PATH, write_default_config

    username = getpass.getuser()
    if write_default_config(username):
        click.echo(f"Wrote {DEFAULT_CONFIG_PATH} (username={username}).")
        click.echo("Review it, then you're ready to run: grit setup -t RC-1234")
    else:
        click.echo(f"Config already exists at {DEFAULT_CONFIG_PATH} — leaving it untouched.")


@cli.command("status")
@click.option("--ticket", "-t", default=None, help="Ticket ID for per-ticket step history.")
@click.pass_context
def status_cmd(ctx, ticket):
    """Show status of active curation tickets, or step history for a specific ticket."""
    from grit.core.registry import RegistryManager, dry_run_root
    from grit.core.status import show_global_status, show_ticket_history

    if getattr(ctx.obj, "dry_run", False):
        registry = RegistryManager(registry_dir=dry_run_root())
    else:
        registry = RegistryManager()
    registry.refresh_statuses()

    if ticket:
        user_config = load_user_config(Path(ctx.obj.config_path))
        show_ticket_history(
            registry,
            ticket,
            user_config,
            dry_run=getattr(ctx.obj, "dry_run", False),
            yaml_override=load_yaml_override(ctx.obj),
        )
    else:
        show_global_status(registry)


@cli.command("_state-update", hidden=True)
@click.option("--workdir", required=True, type=click.Path(), help="Ticket workdir path.")
@click.option("--step", required=True, help="Step name.")
@click.option("--run-dir", "run_dir", required=True, type=click.Path(), help="Run dir path.")
@click.option(
    "--status",
    "status",
    required=True,
    type=click.Choice(["success", "failed"]),
    help="Job outcome.",
)
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
                outputs = (
                    collect_outputs(specs, Path(run_dir), tol_id, hap1=hap1, hap2=hap2) or None
                )
    tracker.finish(step, Path(run_dir), status, job_id=job_id, outputs=outputs)
    log.info(
        "_state-update: step=%s status=%s job_id=%s outputs=%s",
        step,
        status,
        job_id,
        list(outputs) if outputs else None,
    )


cli.add_command(sex_matcher_cmd)
cli.add_command(finalize_qc_cmd)
cli.add_command(post_processing_cmd)
cli.add_command(pp_cmd)
# Not yet tested via CLI / not current — disabled for initial release.
# cli.add_command(add_bedgraph_track_cmd)
# cli.add_command(add_gap_track_cmd)
# cli.add_command(add_telo_track_cmd)
cli.add_command(find_reference_cmd)
cli.add_command(microchromosome_second_shot_cmd)
cli.add_command(microchromosome_combine_cmd)
cli.add_command(setup_cmd)
cli.add_command(haplotig_files_cmd)
cli.add_command(hic_remapping_cmd)
cli.add_command(post_curation_cmd)
cli.add_command(post_curation_recurate_cmd)
cli.add_command(pretext_to_asm_cmd)
cli.add_command(pretext_to_asm_recurate_cmd)
cli.add_command(qv_cmd)
# cli.add_command(validate_files_cmd)  # disabled for initial release, not yet tested via CLI
cli.add_command(blast_contaminants_cmd)
cli.add_command(busco_curated_cmd)
cli.add_command(busco_synteny_cmd)
cli.add_command(fastga_cmd)
cli.add_command(fastga_stats_cmd)
cli.add_command(fastga_synteny_cmd)
cli.add_command(rename_and_orient_cmd)
cli.add_command(super_to_scaffold_cmd)


from grit.core.cleanup import cleanup_cmd  # noqa: E402

cli.add_command(cleanup_cmd)


@cli.command("untrack")
@click.option("--ticket", "-t", required=True, help="Ticket ID.")
@click.option("--step", "-s", required=True, help="Step name to untrack (e.g. rename_and_orient).")
@click.option("--undo", is_flag=True, default=False, help="Re-enable latest untracked run.")
@click.pass_context
def untrack_cmd(ctx, ticket, step, undo):
    """Mark the latest run of a step as non-canonical (or undo that)."""
    from grit.core.registry import RegistryManager, dry_run_root
    from grit.core.run_tracker import RunTracker
    from grit.utils.output import print_done

    if getattr(ctx.obj, "dry_run", False):
        reg = RegistryManager(registry_dir=dry_run_root())
    else:
        reg = RegistryManager()
    entry = reg.find_ticket(ticket)
    if entry is None:
        click.echo(f"Ticket {ticket} not found in registry.", err=True)
        raise SystemExit(1)
    workdir = Path(entry["workdir"])
    tracker = RunTracker(workdir, registry=reg)
    if undo:
        runs = tracker.history(step)
        untracked_runs = [r for r in runs if r.get("status") == "untracked" and r.get("run_dir")]
        if not untracked_runs:
            click.echo(f"No untracked runs found for step {step!r}.", err=True)
            raise SystemExit(1)
        run_dir = Path(untracked_runs[-1]["run_dir"])
        success_before = [
            r for r in runs if r.get("status") == "success" and r.get("run_dir") == str(run_dir)
        ]
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

    if getattr(ctx.obj, "dry_run", False):
        raise click.UsageError("--dry-run is not supported for 'done'.")

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

    if getattr(ctx.obj, "dry_run", False):
        raise click.UsageError("--dry-run is not supported for 'reopen'.")

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


@cli.command("remove")
@click.option("--ticket", "-t", required=True, help="Ticket ID to permanently remove.")
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
@click.pass_context
def remove_cmd(ctx, ticket, yes):
    """Permanently delete a ticket's registry entry and its workdir. Cannot be undone."""
    import shutil

    from grit.core.registry import RegistryManager
    from grit.utils.output import console, print_done

    if getattr(ctx.obj, "dry_run", False):
        raise click.UsageError("--dry-run is not supported for 'remove'.")

    reg = RegistryManager()
    entry = reg.find_ticket(ticket)
    if entry is None:
        click.echo(f"Ticket {ticket} not found in registry.", err=True)
        raise SystemExit(1)

    workdir = Path(entry["workdir"])
    if workdir == Path.home() or workdir == Path("/") or len(workdir.parts) < 4:
        click.echo(f"Refusing to remove {ticket}: workdir looks unsafe ({workdir}).", err=True)
        raise SystemExit(1)

    console.print(
        f"[bold red]WARNING[/bold red]: this will permanently delete:\n"
        f"  ticket:  {ticket}\n"
        f"  tol_id:  {entry.get('tol_id', '')}\n"
        f"  workdir: {workdir}\n"
        f"This cannot be undone."
    )

    if not yes:
        typed = click.prompt(f"Type the ticket ID ({ticket}) to confirm")
        if typed != ticket:
            click.echo("Confirmation did not match — aborting. Nothing was deleted.", err=True)
            raise SystemExit(1)

    if workdir.exists():
        shutil.rmtree(workdir)
    else:
        log.info("Workdir %s already gone — nothing to remove on disk.", workdir)

    reg.delete_ticket(ticket)
    print_done(f"{ticket} ({entry.get('tol_id', '')}) removed — workdir and registry entry gone.")


@cli.command("summary")
@click.pass_context
def summary_cmd(ctx):
    """Show ticket counts by status, and done-ticket counts by time period."""
    from grit.core.registry import RegistryManager
    from grit.core.status import show_summary

    if getattr(ctx.obj, "dry_run", False):
        raise click.UsageError("--dry-run is not supported for 'summary'.")

    show_summary(RegistryManager())


if __name__ == "__main__":
    cli()
