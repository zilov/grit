"""Shared base Click command class for all grit pipeline subcommands."""

from pathlib import Path

import rich_click as click

# Registered Click command names (the string passed to @click.command(...)) of
# steps whose run_* function has an `if ctx.dry_run:` branch. Every other
# GritCommand-based step ignores --dry-run entirely today and would otherwise
# run for real — GritCommand.invoke() below refuses those before the callback runs.
_DRY_RUN_SUPPORTED_COMMANDS = frozenset(
    {
        "setup",
        "pretext-to-asm",
        "blast-contaminants",
        "rename-and-orient",
        "microchromosome-combine",
        "pretext-to-asm-recurate",
        "busco-synteny",
        "fastga-synteny",
        "fastga",
        "microchromosome-second-shot",
        "hic-remapping",
        "post-curation",
        "post-curation-recurate",
        "fastga-stats",
        "haplotig-files",
        "validate-files",
    }
)


class GritCommand(click.RichCommand):
    """Click Command that auto-adds --ticket/-t and --print-only to every subcommand.

    Both options are extracted from ctx.params before the callback is invoked, so
    individual command functions do NOT need them as arguments — they read them via
    ctx.obj.ticket / ctx.obj.print_only.

    --ticket is optional when --yaml is provided at the group level; in that case
    the ticket_id is derived from the YAML filename stem.
    --print-only can be specified after the subcommand name (in addition to the
    global position before it).
    """

    def __init__(
        self,
        name=None,
        bsub_ram_default: int | None = None,
        bsub_ram_help: str | None = None,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        # Insert in reverse order so --ticket appears first, --print-only second, --dry-run
        # third, --untracked fourth, --bsub-ram fifth (only for steps that pass
        # bsub_ram_default/bsub_ram_help)
        if bsub_ram_default is not None or bsub_ram_help is not None:
            help_text = bsub_ram_help or f"LSF memory limit in MB [default: {bsub_ram_default}]"
            self.params.insert(
                0,
                click.Option(
                    ["--bsub-ram"],
                    type=int,
                    default=None,
                    help=help_text,
                ),
            )
        self.params.insert(
            0,
            click.Option(
                ["--untracked", "-u"],
                is_flag=True,
                default=False,
                help="Run step but mark output as non-canonical (untracked).",
            ),
        )
        self.params.insert(
            0,
            click.Option(
                ["--dry-run"],
                is_flag=True,
                default=False,
                help="Create placeholder outputs and mark steps done, without running any "
                "real command (for testing pipeline/tracking logic).",
            ),
        )
        self.params.insert(
            0,
            click.Option(
                ["--print-only"],
                is_flag=True,
                default=False,
                help="Print commands without executing (can also be set globally).",
            ),
        )
        self.params.insert(
            0,
            click.Option(
                ["--ticket", "-t"],
                required=False,
                default=None,
                help="Jira ticket ID. Optional when --yaml is provided.",
            ),
        )

    def invoke(self, ctx: click.Context):
        ticket = ctx.params.pop("ticket", None)
        print_only = ctx.params.pop("print_only", False)
        dry_run = ctx.params.pop("dry_run", False)
        untracked = ctx.params.pop("untracked", False)
        bsub_ram = ctx.params.pop("bsub_ram", None)

        if ctx.obj is not None:
            # Local --print-only ORs with the global flag
            if print_only:
                ctx.obj.print_only = True

            if dry_run:
                ctx.obj.dry_run = True

            # print_only always takes precedence over dry_run (same rule as
            # CurationContext.from_yaml) — a print_only invocation is always safe
            # to allow, regardless of whether this command supports --dry-run.
            effective_dry_run = ctx.obj.dry_run and not ctx.obj.print_only
            if effective_dry_run and self.name not in _DRY_RUN_SUPPORTED_COMMANDS:
                raise click.UsageError(
                    f"--dry-run is not yet supported for '{self.name}' — supported "
                    f"commands: {sorted(_DRY_RUN_SUPPORTED_COMMANDS)}"
                )

            if untracked:
                ctx.obj.untracked = True

            if bsub_ram is not None:
                ctx.obj.bsub_ram = bsub_ram

            if ticket:
                ctx.obj.ticket = ticket
            elif ctx.obj.ticket is None:
                # --ticket not given; try to derive from --yaml filename
                if ctx.obj.yaml:
                    ctx.obj.ticket = Path(ctx.obj.yaml).stem
                else:
                    raise click.UsageError("Missing option '--ticket' / '-t'.")

        return super().invoke(ctx)
