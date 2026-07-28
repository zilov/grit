"""Shared base Click command class for all grit pipeline subcommands."""

from pathlib import Path

import rich_click as click


class GritCommand(click.RichCommand):
    """Click Command that auto-adds --ticket/-t and --print-only to every subcommand.

    Both options are extracted from ctx.params before the callback is invoked, so
    individual command functions do NOT need them as arguments — they read them via
    ctx.obj.ticket / ctx.obj.print_only.

    --ticket is optional when --yaml is provided at the group level; in that case
    the ticket_id is derived from the YAML filename stem.
    --print-only can be specified after the subcommand name (in addition to the
    global position before it).

    --ticket is also optional for commands that declare their own ``--query-fasta``
    option (fastga, busco-curated, busco-synteny) — passing ``--query-fasta`` runs
    the step standalone, with no CurationContext/tracker involved at all.
    """

    def __init__(self, name=None, **kwargs):
        super().__init__(name=name, **kwargs)
        # Insert in reverse order so --ticket appears first, --print-only second, --untracked third
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
        untracked = ctx.params.pop("untracked", False)

        # Commands that support standalone (ticket-free) runs declare their own
        # --query-fasta option; passing it makes --ticket optional here.
        standalone = bool(ctx.params.get("query_fasta"))

        if ctx.obj is not None:
            # Local --print-only ORs with the global flag
            if print_only:
                ctx.obj.print_only = True

            if untracked:
                ctx.obj.untracked = True

            if ticket:
                ctx.obj.ticket = ticket
            elif ctx.obj.ticket is None and not standalone:
                # --ticket not given; try to derive from --yaml filename
                if ctx.obj.yaml:
                    ctx.obj.ticket = Path(ctx.obj.yaml).stem
                else:
                    raise click.UsageError("Missing option '--ticket' / '-t'.")

        return super().invoke(ctx)
