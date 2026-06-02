"""
Click-based CLI for the curation pipeline.

This is the new Click-based interface, allowing modular use of pipeline steps.
"""

import sys
from pathlib import Path

import rich_click as click
import yaml

from grit.core.context import CurationContext


class GlobalState:
    """Global state for Click commands."""

    def __init__(
        self,
        verbose: bool = False,
        config_path: str = None,
        ticket: str = None,
        yaml: str = None,
        print_only: bool = False,
    ):
        self.verbose = verbose
        self.config_path = config_path or Path.home() / ".grit_curation_config.yaml"
        self.ticket = ticket
        self.yaml = yaml
        self.print_only = print_only


@click.group()
@click.option("--verbose", is_flag=True, help="Enable verbose output.")
@click.option(
    "--config", "config_path", type=click.Path(exists=True), help="Path to user config YAML."
)
@click.option("--yaml", type=click.Path(exists=True), help="Path to YAML file")
@click.option("--print-only", is_flag=True, help="Print commands without executing")
@click.pass_context
def cli(ctx, verbose, config_path, yaml, print_only):
    """Curation pipeline CLI."""
    ctx.ensure_object(dict)
    ctx.obj = GlobalState(
        verbose=verbose, config_path=config_path, yaml=yaml, print_only=print_only
    )


def load_user_config(config_path: Path) -> dict:
    if not config_path.exists():
        click.echo(f"Error: User config not found: {config_path}", err=True)
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def build_context(state: GlobalState) -> CurationContext:
    if not state.ticket:
        raise click.UsageError("Missing option '--ticket' / '-t'.")
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
