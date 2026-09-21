"""Interactive `grit tutorial` — a guided --dry-run walkthrough of a curation."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import rich_click as click
from rich.panel import Panel

from grit.utils.output import console

DEMO_YAML = Path(__file__).resolve().parent.parent / "config" / "tutorial_demo.yaml"
DEFAULT_TICKET = "TUTORIAL-1"


@dataclass(frozen=True)
class Lesson:
    """One step of the walkthrough: what to explain, what to run, what to look at."""

    title: str
    why: str
    command: str
    args: list[str] = field(default_factory=list)
    watch: str = ""
    status_after: bool = False


LESSONS: list[Lesson] = [
    Lesson(
        title="setup — claim the ticket and build the workdir",
        why=(
            "Reads the ticket's YAML, works out where the curation workdir belongs "
            "(the draft assembly path with assembly/draft swapped for working/), and "
            "stages the draft assembly and the Pretext map into it. Every later step "
            "resolves its inputs from what setup put there, so this always runs first."
        ),
        command="setup",
        watch="The workdir path it prints — that is where everything below will land.",
        status_after=True,
    ),
    Lesson(
        title="pretext-to-asm — turn the curated Pretext map back into an assembly",
        why=(
            "This is the step you run after the manual curation in PretextView. It "
            "converts the edited .pretext into an AGP and rebuilds a FASTA per "
            "haplotype. It is the first step that produces a new *canonical* assembly."
        ),
        command="pretext-to-asm",
        watch=(
            "In the Canonical files table, both haplotypes now point into "
            "pretext_to_asm/ instead of the draft."
        ),
        status_after=True,
    ),
    Lesson(
        title="blast-contaminants — screen the curated assembly",
        why=(
            "Blasts the curated assembly against the contaminant databases and writes "
            "a cleaned FASTA. Note what this does to canonical: grit never hardcodes a "
            "step order — the freshest successful tracked output wins, so canonical "
            "moves to blast_contaminants simply because it ran last."
        ),
        command="blast-contaminants",
        watch="Canonical FA moved again — now blast_contaminants/.",
        status_after=True,
    ),
    Lesson(
        title="hic-remapping (hap1) — remap the HiC reads onto the curated assembly",
        why=(
            "Builds a fresh Pretext map from the curated assembly so you can look at it "
            "again for a second curation round. It produces a map, not an assembly, so "
            "it must NOT take canonical away from blast-contaminants."
        ),
        command="hic-remapping",
        watch="",
    ),
    Lesson(
        title="hic-remapping (hap2) — the same, for the second haplotype",
        why=(
            "--hap2 here is exclusive: it runs the second haplotype *instead of* the "
            "first, so a diploid ticket needs both invocations. Other steps use --hap2 "
            "additively (see rename-and-orient below) — the help text of each step says "
            "which it is."
        ),
        command="hic-remapping",
        args=["--hap2"],
        watch="Canonical FA is still blast_contaminants — remapping never claims it.",
        status_after=True,
    ),
    Lesson(
        title="pretext-to-asm-recurate — the second curation round",
        why=(
            "Same idea as pretext-to-asm, but it consumes the map hic-remapping made and "
            "applies the edits on top of the already-curated assembly. Run it once per "
            "haplotype; the tutorial does hap1 here and hap2 next."
        ),
        command="pretext-to-asm-recurate",
        watch="",
    ),
    Lesson(
        title="pretext-to-asm-recurate (hap2)",
        why="The second haplotype's recuration — again an exclusive --hap2.",
        command="pretext-to-asm-recurate",
        args=["--hap2"],
        watch=(
            "Each haplotype is tracked separately: hap1 canonical is "
            "pretext_to_asm_recurate/, hap2 is pretext_to_asm_recurate_hap2/."
        ),
        status_after=True,
    ),
    Lesson(
        title="rename-and-orient — name and orient the chromosomes",
        why=(
            "Compares the assembly to a reference and renames/flips scaffolds so the "
            "chromosome numbering matches. Here --hap2 is additive: this one invocation "
            "does both haplotypes."
        ),
        command="rename-and-orient",
        args=["--hap2"],
        watch="Canonical chains forward from recurate to rename_and_orient/.",
        status_after=True,
    ),
    Lesson(
        title="untrack — undo a step you should not have run",
        why=(
            "Suppose rename-and-orient used the wrong reference. `grit untrack` marks its "
            "latest run non-canonical without deleting anything, and canonical falls back "
            "to the next-freshest tracked output."
        ),
        command="untrack",
        args=["-s", "rename_and_orient"],
        watch=(
            "hap1 canonical fell back to pretext_to_asm_recurate/, while hap2 is "
            "untouched — rename_and_orient_hap2 is a separate step with its own history."
        ),
        status_after=True,
    ),
    Lesson(
        title="retrack — put it back",
        why=(
            "The mirror image: it promotes the untracked run back to canonical using the "
            "outputs already recorded for it. Nothing is re-run."
        ),
        command="retrack",
        args=["-s", "rename_and_orient"],
        watch="hap1 canonical is rename_and_orient/ again.",
        status_after=True,
    ),
    Lesson(
        title="finalize-qc — assemble the release",
        why=(
            "Copies the canonical assembly, AGP and chromosome list into the ticket's "
            "assembly_curated/ release directory and gathers the QC numbers. Whatever was "
            "canonical at this moment is what ships — which is why the Canonical column "
            "above is worth reading before you run it."
        ),
        command="finalize-qc",
        watch="The assembly_curated/ path it prints is the release directory.",
        status_after=True,
    ),
]


def _display(lesson: Lesson, ticket: str) -> str:
    """Return the command line as a curator would type it, without the tutorial's plumbing."""
    parts = ["grit", lesson.command, "-t", ticket, *lesson.args, "--dry-run"]
    return " ".join(parts)


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
    except Exception as exc:  # a step blowing up should not kill the lesson plan
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return False
    return True


def _reset_sandbox(ticket: str) -> None:
    """Delete *ticket*'s dry-run workdir and registry entry, so the walkthrough starts clean."""
    from grit.core.registry import RegistryManager, dry_run_root

    workdir = dry_run_root() / ticket
    if workdir.exists():
        shutil.rmtree(workdir)
    reg = RegistryManager(registry_dir=dry_run_root())
    if reg.find_ticket(ticket):
        reg.delete_ticket(ticket)


def run_tutorial(config_path: Path, ticket: str, auto: bool = False) -> int:
    """Walk through a full dry-run curation, one explained step at a time."""
    if not Path(config_path).exists():
        console.print(
            f"[bold red]No grit config at {config_path}.[/bold red]\n"
            "Run [bold]grit init[/bold] first — it writes one pre-filled with your username."
        )
        return 1

    console.print(
        Panel(
            "[bold]grit tutorial[/bold] — a guided walkthrough of a whole curation.\n\n"
            "Every command below is a real grit command, run for real, but with "
            "[bold]--dry-run[/bold]: no HPC job is submitted and no lustre path is "
            f"touched. Outputs are placeholder files under [bold]~/.grit/dry_run/{ticket}/[/bold], "
            "and the step history goes into a throwaway registry next to it — your real "
            "tickets are never involved.\n\n"
            f"The ticket is fictional ({ticket}, specimen xxTutDemo1, a diploid "
            "hap1/hap2 assembly).\n\n"
            "[dim]At each step: Enter to run it, s to skip, q to quit.[/dim]",
            style="bold cyan",
        )
    )

    _reset_sandbox(ticket)
    base = ["--config", str(config_path), "--yaml", str(DEMO_YAML), "--dry-run"]

    for n, lesson in enumerate(LESSONS, start=1):
        console.print(Panel(f"  {n}/{len(LESSONS)}  {lesson.title}  ", style="bold magenta"))
        console.print(lesson.why)
        console.print(f"\n  [bold green]$[/bold green] [bold]{_display(lesson, ticket)}[/bold]\n")

        if not auto:
            choice = click.prompt("", default="", show_default=False, prompt_suffix="> ").strip()
            if choice.lower() == "q":
                console.print("\nStopped. Re-run `grit tutorial` any time — it starts clean.")
                return 0
            if choice.lower() == "s":
                console.print("[dim]skipped[/dim]")
                continue

        if not _run_grit([*base, lesson.command, "-t", ticket, *lesson.args]):
            console.print(
                "[bold red]That step failed.[/bold red] The walkthrough continues, but later "
                "steps may not make sense — quit with q and re-run `grit tutorial` to reset."
            )

        if lesson.status_after:
            console.print("\n[dim]$ grit --dry-run status -t " + ticket + "[/dim]")
            _run_grit([*base, "status", "-t", ticket])

        if lesson.watch:
            console.print(f"\n[bold yellow]Look at:[/bold yellow] {lesson.watch}")

    console.print(
        Panel(
            "That is the whole chain.\n\n"
            "Two things worth remembering:\n"
            "  • Canonical is not a fixed step order — the freshest successful tracked "
            "output wins, per haplotype. `grit status -t <ticket>` always tells you "
            "which file is current.\n"
            "  • `grit untrack` / `grit retrack` are how you back out of a step without "
            "deleting anything.\n\n"
            f"The sandbox is at ~/.grit/dry_run/{ticket}/ — poke around in it, then "
            "`rm -rf ~/.grit/dry_run` (or just re-run this tutorial) to clear it.\n\n"
            "Next: `grit --help` for the full command list, and `grit <command> --help` "
            "for a step's flags.",
            style="bold cyan",
        )
    )
    return 0


@click.command("tutorial")
@click.option("--ticket", "-t", default=DEFAULT_TICKET, help="Sandbox ticket ID to use.")
@click.option("--auto", is_flag=True, help="Run every step without prompting.")
@click.pass_context
def tutorial_cmd(ctx, ticket, auto):
    """Guided --dry-run walkthrough of a full curation, for learning the CLI."""
    raise SystemExit(run_tutorial(Path(ctx.obj.config_path), ticket, auto=auto))
