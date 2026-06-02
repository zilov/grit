"""Shared base Click command class for all grit pipeline subcommands."""

import rich_click as click


class GritCommand(click.RichCommand):
    """Click Command that automatically adds --ticket/-t as a required option.

    The ticket value is extracted from ctx.params before the callback is
    invoked, so individual command functions do NOT need a ``ticket``
    argument — they continue to read it via ``ctx.obj.ticket``.
    """

    def __init__(self, name=None, **kwargs):
        super().__init__(name=name, **kwargs)
        # Prepend so --ticket appears first in help output
        self.params.insert(
            0,
            click.Option(
                ["--ticket", "-t"],
                required=True,
                help="Jira ticket ID.",
            ),
        )

    def invoke(self, ctx: click.Context):
        ticket = ctx.params.pop("ticket", None)
        if ticket and ctx.obj is not None:
            ctx.obj.ticket = ticket
        return super().invoke(ctx)
