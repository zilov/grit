"""Interactive `grit tutorial` — a guided --dry-run walkthrough of a curation."""

import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path

import rich_click as click
from rich.panel import Panel

from grit.core.tutorial_lessons import SCENARIOS, Lesson, Scenario, find_scenario
from grit.utils.output import console

# Short options the learner may type, and the long name they normalise to.
_ALIASES = {"-t": "--ticket", "-s": "--step", "-u": "--untracked"}
# Options that consume a following value and whose value is part of the answer.
_VALUE_OPTS = {"--ticket", "--step", "--bsub-ram", "--lineage"}
# Plumbing the tutorial supplies itself — consumed and ignored when matching.
_IGNORED_VALUE_OPTS = {"--config", "--yaml", "--logging-level"}


@dataclass(frozen=True)
class Parsed:
    """A grit command line reduced to the parts that decide whether it is the right one."""

    subcommand: str | None
    ticket: str | None
    flags: frozenset[str]


def parse_command(tokens: list[str]) -> Parsed:
    """Normalise *tokens* into the (subcommand, ticket, flags) triple used for matching."""
    toks = list(tokens)
    if toks and toks[0] == "grit":
        toks = toks[1:]

    subcommand: str | None = None
    ticket: str | None = None
    flags: set[str] = set()

    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok.startswith("-"):
            name, eq, inline = tok.partition("=")
            name = _ALIASES.get(name, name)
            if name in _VALUE_OPTS or name in _IGNORED_VALUE_OPTS:
                if eq:
                    value = inline
                else:
                    value = toks[i + 1] if i + 1 < len(toks) else ""
                    i += 1
                if name in _IGNORED_VALUE_OPTS:
                    pass
                elif name == "--ticket":
                    ticket = value
                else:
                    flags.add(f"{name}={value}")
            elif name != "--dry-run":
                # --dry-run is supplied by the tutorial, so typing it is neither
                # required nor wrong.
                flags.add(name)
        elif subcommand is None:
            subcommand = tok
        i += 1

    return Parsed(subcommand, ticket, frozenset(flags))


def expected_command(lesson: Lesson, ticket: str) -> Parsed:
    """Return the Parsed form of the command *lesson* is asking for."""
    return parse_command([lesson.command, "-t", ticket, *lesson.args])


def expected_line(lesson: Lesson, ticket: str) -> str:
    """Return the answer as a command line, for `??`."""
    return " ".join(["grit", lesson.command, "-t", ticket, *lesson.args])


def _flag_name(flag: str) -> str:
    """Return a flag's bare name, dropping any =value part."""
    return flag.split("=", 1)[0]


def hint_for(got: Parsed, lesson: Lesson, ticket: str, known: set[str]) -> str:
    """Return one sentence naming what is actually wrong with *got*."""
    want = expected_command(lesson, ticket)

    if got.subcommand is None:
        return "That has no command in it — start with `grit`, then the step name."
    if got.subcommand not in known:
        return f"grit has no command called {got.subcommand!r}. `grit --help` lists them all."
    if got.subcommand != want.subcommand:
        return f"{got.subcommand!r} is a real step, but this lesson is about {want.subcommand!r}."
    if got.ticket is None:
        return f"Every grit step needs to know which ticket it is working on: add -t {ticket}."
    if got.ticket != ticket:
        return f"The sandbox ticket for this scenario is {ticket}, not {got.ticket!r}."

    for flag in sorted(want.flags - got.flags):
        name = _flag_name(flag)
        if name in lesson.flag_hints:
            return lesson.flag_hints[name]
        return f"Something is missing: this step also needs {flag}."

    for flag in sorted(got.flags - want.flags):
        return (
            f"{_flag_name(flag)} is not needed here — see `grit {want.subcommand} --help` "
            "for what this step takes."
        )

    return "Close. Compare what you typed with `??`."


def matches(got: Parsed, lesson: Lesson, ticket: str) -> bool:
    """True when *got* is the command the lesson asked for."""
    return got == expected_command(lesson, ticket)


def _known_commands() -> set[str]:
    from grit.core.click_cli import cli

    return {name for name in cli.commands if not name.startswith("_")}


def _run_grit(argv: list[str]) -> bool:
    """Run grit's own CLI in-process with *argv*; True when it completed cleanly."""
    from grit.core.click_cli import cli

    try:
        cli.main(args=argv, prog_name="grit", standalone_mode=False)
    except click.ClickException as exc:
        exc.show()
        return False
    except SystemExit as exc:
        return exc.code in (0, None)
    except Exception as exc:  # a step blowing up should not end the lesson
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return False
    return True


def _reset_sandbox(ticket: str) -> None:
    """Delete *ticket*'s dry-run workdir and registry entry, so a scenario starts clean."""
    from grit.core.registry import RegistryManager, dry_run_root

    workdir = dry_run_root() / ticket
    if workdir.exists():
        shutil.rmtree(workdir)
    reg = RegistryManager(registry_dir=dry_run_root())
    if reg.find_ticket(ticket):
        reg.delete_ticket(ticket)


def _ask(prompt: str = "") -> str:
    return click.prompt(prompt, default="", show_default=False, prompt_suffix="> ").strip()


def _explain(lesson: Lesson, n: int, total: int) -> None:
    console.print(Panel(f"  {n}/{total}  {lesson.title}  ", style="bold magenta"))
    console.print(lesson.why)
    console.print(f"\n[bold]Your turn:[/bold] {lesson.task}")
    console.print(
        "[dim]Type the command. Other grit commands work too and won't skip ahead. "
        "?=hint  ??=answer  r=re-read  s=skip  q=quit[/dim]"
    )


def _check_phase(lesson: Lesson, base: list[str], ticket: str) -> str:
    """Nudge the learner to look at status; returns 'next' or 'quit'."""
    console.print(
        f"\n[bold yellow]Check it:[/bold yellow] run [bold]grit status -t {ticket}[/bold] "
        f"and find — {lesson.check}"
    )
    while True:
        raw = _ask()
        if raw.lower() == "q":
            return "quit"
        if not raw:
            return "next"
        if raw.lower() in {"s", "?", "??", "r"}:
            return "next"
        tokens = _safe_tokens(raw)
        if tokens is None:
            continue
        got = parse_command(tokens)
        if _safe_to_run(got, lesson, ticket, tokens):
            _run_grit([*base, *tokens])
        else:
            console.print(
                f"[yellow]Not run — {hint_for(got, lesson, ticket, _known_commands())}[/yellow]"
            )
        console.print("[dim]Enter to move on.[/dim]")


def _is_help(tokens: list[str]) -> bool:
    return "--help" in tokens or "-h" in tokens


def _safe_to_run(got: Parsed, lesson: Lesson, ticket: str, tokens: list[str]) -> bool:
    """True when a command that isn't the lesson's answer should still be executed.

    Only the read-only ones: `--help`, and `grit status` for this scenario's own
    ticket. Running another *step* would be allowed by the sandbox but would
    quietly invalidate the "run status and find X" line the next lesson makes —
    and a missing --ticket is worse still, since the tutorial's own --yaml makes
    grit derive one from the filename instead of failing.
    """
    if _is_help(tokens):
        return True
    return got.subcommand == "status" and got.ticket == ticket


def _safe_tokens(raw: str) -> list[str] | None:
    """Split *raw* into grit arguments, or None (with a message) when it is not runnable."""
    try:
        tokens = shlex.split(raw)
    except ValueError:
        console.print("[yellow]Unbalanced quotes — try again.[/yellow]")
        return None
    if not tokens:
        return None
    if tokens[0] != "grit":
        console.print("[yellow]Commands start with `grit`. Type ? for a hint, q to quit.[/yellow]")
        return None
    rest = tokens[1:]
    if rest and rest[0] == "init":
        console.print(
            "[yellow]`grit init` writes your real config, so the tutorial won't run it. "
            "Everything else is sandboxed.[/yellow]"
        )
        return None
    return rest


def _run_lesson(lesson: Lesson, scenario: Scenario, base: list[str], n: int, total: int) -> str:
    """Drive one lesson to completion; returns 'next' or 'quit'."""
    _explain(lesson, n, total)
    known = _known_commands()
    last: Parsed | None = None

    while True:
        raw = _ask()
        low = raw.lower()

        if low == "q":
            return "quit"
        if low == "s":
            console.print("[dim]skipped[/dim]")
            return "next"
        if low == "r":
            _explain(lesson, n, total)
            continue
        if low == "??":
            console.print(f"  [bold green]{expected_line(lesson, scenario.ticket)}[/bold green]")
            continue
        if low == "?":
            if last is None:
                console.print(
                    f"[bold yellow]Hint:[/bold yellow] the step you want is "
                    f"[bold]{lesson.command}[/bold]. Don't forget -t."
                )
            else:
                console.print(
                    f"[bold yellow]Hint:[/bold yellow] "
                    f"{hint_for(last, lesson, scenario.ticket, known)}"
                )
            continue
        if not raw:
            continue

        tokens = _safe_tokens(raw)
        if tokens is None:
            continue

        if _is_help(tokens):
            # Reading a step's --help is never a wrong answer, so it gets no hint.
            _run_grit([*base, *tokens])
            continue

        got = parse_command(tokens)
        if not matches(got, lesson, scenario.ticket):
            last = got
            if _safe_to_run(got, lesson, scenario.ticket, tokens):
                _run_grit([*base, *tokens])
            console.print(
                f"\n[bold yellow]Still on this lesson:[/bold yellow] "
                f"{hint_for(got, lesson, scenario.ticket, known)}"
            )
            continue

        if not _run_grit([*base, *tokens]):
            console.print(
                "[bold red]That step failed.[/bold red] Quit with q and re-run the "
                "scenario to start clean."
            )
        if lesson.check:
            return _check_phase(lesson, base, scenario.ticket)
        return "next"


def _run_scenario_auto(scenario: Scenario, base: list[str]) -> None:
    """Run every lesson's expected command unprompted (used by --auto and the smoke test)."""
    for n, lesson in enumerate(scenario.lessons, start=1):
        header = f"  {n}/{len(scenario.lessons)}  {lesson.title}  "
        console.print(Panel(header, style="bold magenta"))
        console.print(lesson.why)
        line = expected_line(lesson, scenario.ticket)
        console.print(f"\n  [bold green]$[/bold green] [bold]{line}[/bold]\n")
        _run_grit([*base, lesson.command, "-t", scenario.ticket, *lesson.args])
        if lesson.check:
            console.print(f"\n[dim]$ grit status -t {scenario.ticket}[/dim]")
            _run_grit([*base, "status", "-t", scenario.ticket])
            console.print(f"\n[bold yellow]Check it:[/bold yellow] {lesson.check}")


def run_scenario(scenario: Scenario, config_path: Path, auto: bool) -> None:
    """Reset the scenario's sandbox and walk its lessons."""
    _reset_sandbox(scenario.ticket)
    base = [
        "--config",
        str(config_path),
        "--yaml",
        str(scenario.yaml_path),
        "--dry-run",
    ]

    console.print(
        Panel(
            f"[bold]{scenario.title}[/bold]\n\n{scenario.blurb}\n\n"
            f"Sandbox ticket: [bold]{scenario.ticket}[/bold] — every command runs for "
            "real but under --dry-run, so nothing reaches Jira, LSF, lustre or your real "
            f"registry. Outputs are placeholders under ~/.grit/dry_run/{scenario.ticket}/.",
            style="bold cyan",
        )
    )

    if auto:
        _run_scenario_auto(scenario, base)
        return

    total = len(scenario.lessons)
    for n, lesson in enumerate(scenario.lessons, start=1):
        if _run_lesson(lesson, scenario, base, n, total) == "quit":
            console.print("\nStopped. Re-run `grit tutorial` any time — it starts clean.")
            return

    console.print(
        Panel(
            "Scenario finished.\n\n"
            "  • Canonical is not a fixed step order — the freshest successful tracked "
            "output wins, per haplotype. `grit status -t <ticket>` is the only honest "
            "answer to 'which file is current?'.\n"
            "  • `grit untrack` / `grit retrack` back a step out without deleting anything.\n\n"
            f"The sandbox is at ~/.grit/dry_run/{scenario.ticket}/ — poke around, then "
            "`rm -rf ~/.grit/dry_run` to clear it.\n\n"
            "`grit tutorial` again for another scenario; `grit --help` for everything else.",
            style="bold cyan",
        )
    )


def _choose_scenario() -> Scenario | None:
    """Show the scenario menu; None when the learner quits."""
    console.print(
        Panel(
            "[bold]grit tutorial[/bold] — learn the CLI by driving it.\n\n"
            "Each scenario is a real curation run against a fictional ticket with "
            "[bold]--dry-run[/bold]: no HPC job, no lustre path, no Jira, and a throwaway "
            "registry. You type the commands; the tutorial explains each one first and "
            "tells you what to look for afterwards.",
            style="bold cyan",
        )
    )
    for i, scenario in enumerate(SCENARIOS, start=1):
        console.print(f"  [bold]{i}[/bold]  {scenario.title}\n     [dim]{scenario.blurb}[/dim]")
    console.print("  [bold]q[/bold]  quit\n")

    while True:
        raw = _ask("Pick a scenario")
        if raw.lower() == "q":
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(SCENARIOS):
            return SCENARIOS[int(raw) - 1]
        console.print(f"[yellow]Enter 1-{len(SCENARIOS)}, or q.[/yellow]")


@click.command("tutorial")
@click.option(
    "--scenario",
    "scenario_key",
    default=None,
    help=f"Run one scenario directly: {', '.join(s.key for s in SCENARIOS)}.",
)
@click.option("--auto", is_flag=True, help="Run every lesson's command without prompting.")
@click.option("--all", "run_all", is_flag=True, help="With --auto, run every scenario.")
@click.pass_context
def tutorial_cmd(ctx, scenario_key, auto, run_all):
    """Guided --dry-run walkthrough of a curation, for learning the CLI."""
    config_path = Path(ctx.obj.config_path)
    if not config_path.exists():
        console.print(
            f"[bold red]No grit config at {config_path}.[/bold red]\n"
            "Run [bold]grit init[/bold] first — it writes one pre-filled with your username."
        )
        raise SystemExit(1)

    if run_all:
        for scenario in SCENARIOS:
            run_scenario(scenario, config_path, auto=True)
        return

    if scenario_key:
        scenario = find_scenario(scenario_key)
        if scenario is None:
            raise click.UsageError(
                f"Unknown scenario {scenario_key!r} — "
                f"choose from: {', '.join(s.key for s in SCENARIOS)}"
            )
    elif auto:
        scenario = SCENARIOS[0]
    else:
        scenario = _choose_scenario()
        if scenario is None:
            return

    run_scenario(scenario, config_path, auto=auto)
