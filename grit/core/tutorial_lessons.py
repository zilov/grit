"""Lesson and scenario text for `grit tutorial` — data only, no engine logic."""

from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEMO_YAML_HAPS = _CONFIG_DIR / "tutorial_demo.yaml"
DEMO_YAML_PRIMARY = _CONFIG_DIR / "tutorial_demo_primary.yaml"


@dataclass(frozen=True)
class Lesson:
    """One step: what it is for, what the learner must type, what to check afterwards."""

    title: str
    why: str
    task: str
    command: str
    args: list[str] = field(default_factory=list)
    flag_hints: dict[str, str] = field(default_factory=dict)
    check: str = ""


@dataclass(frozen=True)
class Scenario:
    """A named lesson chain with its own demo ticket."""

    key: str
    title: str
    blurb: str
    yaml_path: Path
    ticket: str
    lessons: list[Lesson]


_STATUS_LESSON = Lesson(
    title="status — how to read what grit knows",
    why=(
        "Before running anything else, learn to read the one command you will run "
        "most often. `grit status -t <ticket>` prints three things:\n"
        "  • the curation summary — species, assembly type, where the reads and the "
        "workdir are;\n"
        "  • Canonical files — for each haplotype, which FASTA, haplotigs file and "
        "chromosome list grit currently considers *the* current one. This is the "
        "table that decides what later steps consume and what finalize-qc ships;\n"
        "  • Step history — every run of every step, its status, and a Canonical "
        "column marking which outputs that particular run still owns.\n"
        "Right now only setup has run, so the canonical rows are all empty."
    ),
    task="Ask grit what it knows about this ticket.",
    command="status",
)


_STANDARD = Scenario(
    key="standard",
    title="Standard curation (diploid, hap1/hap2)",
    blurb="The full chain, setup through finalize-qc, on a two-haplotype assembly.",
    yaml_path=DEMO_YAML_HAPS,
    ticket="TUTORIAL-1",
    lessons=[
        Lesson(
            title="setup — claim the ticket and build the workdir",
            why=(
                "Reads the ticket's YAML, works out where the curation workdir belongs "
                "(the draft assembly path with assembly/draft swapped for working/), and "
                "stages the draft assembly and the Pretext map into it. Every later step "
                "resolves its inputs from what setup put there, so this always runs first."
            ),
            task="Run the setup step for this ticket. Every grit step needs -t <ticket>.",
            command="setup",
        ),
        _STATUS_LESSON,
        Lesson(
            title="pretext-to-asm — turn the curated map back into an assembly",
            why=(
                "This is what you run after the manual curation in PretextView. It "
                "converts the edited .pretext into an AGP and rebuilds a FASTA per "
                "haplotype — the first step that produces a new *canonical* assembly."
            ),
            task=(
                "You have curated the Pretext map. Turn it back into an assembly. "
                "(? if you don't remember the step name.)"
            ),
            command="pretext-to-asm",
            check="both haplotypes' assembly FA now point into pretext_to_asm/",
        ),
        Lesson(
            title="blast-contaminants — screen the curated assembly",
            why=(
                "Blasts the curated assembly against the contaminant databases and "
                "writes a cleaned FASTA. Watch what it does to canonical: grit has no "
                "hardcoded step order — the freshest successful tracked output wins, so "
                "canonical moves here simply because this ran last."
            ),
            task="Screen the curated assembly for contaminants.",
            command="blast-contaminants",
            check="canonical FA moved again — now blast_contaminants/",
        ),
        Lesson(
            title="hic-remapping — remap the HiC reads onto the curated assembly",
            why=(
                "Builds a fresh Pretext map from the curated assembly so you can look at "
                "it again for a second curation round. It produces a map, not an "
                "assembly, so it must not take canonical away from blast-contaminants."
            ),
            task="Remap the HiC reads for the first haplotype.",
            command="hic-remapping",
        ),
        Lesson(
            title="hic-remapping — and now the second haplotype",
            why=(
                "hic-remapping's --hap2 is *exclusive*: it runs the second haplotype "
                "instead of the first, so a diploid ticket needs the command twice. Other "
                "steps treat --hap2 additively — rename-and-orient below is one. Each "
                "step's --help says which it is; guessing is how people lose a haplotype."
            ),
            task="Do the same for the second haplotype.",
            command="hic-remapping",
            args=["--hap2"],
            flag_hints={
                "--hap2": (
                    "hic-remapping runs one haplotype per invocation — --hap2 selects the "
                    "second one instead of the first."
                )
            },
            check="canonical FA is still blast_contaminants — remapping never claims it",
        ),
        Lesson(
            title="pretext-to-asm-recurate — the second curation round",
            why=(
                "Same idea as pretext-to-asm, but it consumes the map hic-remapping made "
                "and applies the new edits on top of the already-curated assembly. Like "
                "hic-remapping, it is one haplotype per invocation."
            ),
            task="Apply the second round of curation to the first haplotype.",
            command="pretext-to-asm-recurate",
        ),
        Lesson(
            title="pretext-to-asm-recurate — second haplotype",
            why="Again exclusive: the second haplotype needs its own invocation.",
            task="And the second haplotype.",
            command="pretext-to-asm-recurate",
            args=["--hap2"],
            flag_hints={"--hap2": "pretext-to-asm-recurate is also one haplotype per invocation."},
            check=(
                "the two haplotypes are tracked separately — hap1 is "
                "pretext_to_asm_recurate/, hap2 is pretext_to_asm_recurate_hap2/"
            ),
        ),
        Lesson(
            title="rename-and-orient — name and orient the chromosomes",
            why=(
                "Compares the assembly to a reference and renames/flips scaffolds so the "
                "chromosome numbering matches it. Here --hap2 is *additive*: one "
                "invocation with it does both haplotypes. This is the opposite of "
                "hic-remapping, and the distinction is worth burning in."
            ),
            task="Name and orient the chromosomes for both haplotypes in one go.",
            command="rename-and-orient",
            args=["--hap2"],
            flag_hints={
                "--hap2": (
                    "rename-and-orient's --hap2 is additive — it adds the second "
                    "haplotype to the same run rather than replacing the first."
                )
            },
            check="canonical chained forward from recurate to rename_and_orient/",
        ),
        Lesson(
            title="finalize-qc — assemble the release",
            why=(
                "Copies the canonical assembly, AGP and chromosome list into the ticket's "
                "assembly_curated/ release directory and gathers the QC numbers. Whatever "
                "is canonical at this moment is what ships — which is why the canonical "
                "table is worth reading before you run this, not after."
            ),
            task="Build the release directory and the QC report.",
            command="finalize-qc",
            check="the assembly_curated/ path it printed — that is the release directory",
        ),
    ],
)


_SINGLE_HAP = Scenario(
    key="single-hap",
    title="Single-haplotype curation (primary/alternate)",
    blurb="The same chain on a one-haplotype assembly — and where the hap2 steps go.",
    yaml_path=DEMO_YAML_PRIMARY,
    ticket="TUTORIAL-SOLO",
    lessons=[
        Lesson(
            title="setup — a primary/alternate ticket",
            why=(
                "This ticket's YAML has a `primary` key instead of `hap1`/`hap2`, so grit "
                "detects it as a single-haplotype assembly. Nothing about the command "
                "changes; what changes is that every hap2 flag below is simply absent."
            ),
            task="Set the ticket up, exactly as before.",
            command="setup",
        ),
        _STATUS_LESSON,
        Lesson(
            title="pretext-to-asm — one haplotype, one row",
            why=(
                "The step is the same. What differs is the canonical table: a single-hap "
                "ticket must never grow an 'alternate' row. grit gates this centrally "
                "with is_single_hap(ctx), so a step cannot fabricate a second haplotype "
                "even by accident."
            ),
            task="Turn the curated map back into an assembly.",
            command="pretext-to-asm",
            check=("the canonical table has 'primary' rows only — no 'alternate' row appeared"),
        ),
        Lesson(
            title="blast-contaminants",
            why="Same screen, same canonical behaviour: freshest tracked output wins.",
            task="Screen the curated assembly for contaminants.",
            command="blast-contaminants",
            check="canonical FA is blast_contaminants/, still one haplotype",
        ),
        Lesson(
            title="hic-remapping — no --hap2 at all here",
            why=(
                "On a diploid ticket you would run this twice. Here there is no second "
                "haplotype, so passing --hap2 would be meaningless — the single "
                "invocation is the whole step."
            ),
            task="Remap the HiC reads.",
            command="hic-remapping",
        ),
        Lesson(
            title="pretext-to-asm-recurate",
            why="The second curation round, again a single invocation.",
            task="Apply the second round of curation.",
            command="pretext-to-asm-recurate",
            check="canonical FA moved to pretext_to_asm_recurate/",
        ),
        Lesson(
            title="finalize-qc",
            why=(
                "Identical to the diploid case — it ships whatever is canonical now, for "
                "the one haplotype this ticket has."
            ),
            task="Build the release directory and the QC report.",
            command="finalize-qc",
            check="the release directory holds one haplotype's files",
        ),
    ],
)


_OOPS = Scenario(
    key="oops",
    title="I ran the wrong step",
    blurb="Short: how canonical is decided, and how to back out without deleting anything.",
    yaml_path=DEMO_YAML_HAPS,
    ticket="TUTORIAL-OOPS",
    lessons=[
        Lesson(
            title="setup",
            why="A fresh sandbox ticket to make a mess in.",
            task="Set the ticket up.",
            command="setup",
        ),
        Lesson(
            title="pretext-to-asm",
            why="Some curated assembly to work from.",
            task="Turn the curated map into an assembly.",
            command="pretext-to-asm",
        ),
        Lesson(
            title="blast-contaminants — and now suppose it was wrong",
            why=(
                "Imagine you ran the contaminant screen against the wrong database. The "
                "output is bad, and because it is the freshest tracked output it is now "
                "canonical — every later step would consume it."
            ),
            task="Run the contaminant screen.",
            command="blast-contaminants",
            check="canonical FA is blast_contaminants/ — the bad output is now in charge",
        ),
        Lesson(
            title="untrack — demote it without deleting it",
            why=(
                "`grit untrack` marks a step's latest run non-canonical. Nothing is "
                "deleted: the run dir, the files and the history stay, they just stop "
                "counting. Canonical falls back to the next-freshest tracked output. "
                "untrack needs to be told which step, with -s / --step, and it takes the "
                "tracker's step name (blast_contaminants), not the CLI name."
            ),
            task="Demote the blast_contaminants run.",
            command="untrack",
            args=["-s", "blast_contaminants"],
            flag_hints={
                "--step": (
                    "untrack needs to know which step to demote: -s blast_contaminants "
                    "(underscores — that is the tracker's name for it)."
                )
            },
            check="canonical fell back to pretext_to_asm/",
        ),
        Lesson(
            title="retrack — and put it back",
            why=(
                "The mirror image. It promotes the untracked run back to canonical using "
                "the outputs already recorded for it — nothing is re-run. This is also "
                "how you recover a run you started with --untracked."
            ),
            task="Promote the blast_contaminants run back.",
            command="retrack",
            args=["-s", "blast_contaminants"],
            flag_hints={"--step": "retrack takes the same -s <step> as untrack."},
            check="canonical is blast_contaminants/ again",
        ),
        Lesson(
            title="rename-and-orient — recency, not step order",
            why=(
                "The important half of the lesson. There is no fixed pipeline order in "
                "grit: whichever canonical-producing step ran most recently owns the "
                "output, per haplotype."
            ),
            task="Name and orient the chromosomes for both haplotypes.",
            command="rename-and-orient",
            args=["--hap2"],
            flag_hints={"--hap2": "rename-and-orient's --hap2 is additive — both in one run."},
            check="canonical moved to rename_and_orient/",
        ),
        Lesson(
            title="…and run the screen again",
            why=(
                "Re-running an 'earlier' step takes canonical back, because it is now the "
                "freshest. That is by design, and it is why `grit status` is the only "
                "honest answer to 'which file is current?' — not the order in the docs."
            ),
            task="Run the contaminant screen once more.",
            command="blast-contaminants",
            check="canonical bounced back to blast_contaminants/, ahead of rename_and_orient",
        ),
    ],
)


SCENARIOS: list[Scenario] = [_STANDARD, _SINGLE_HAP, _OOPS]


def find_scenario(key: str) -> Scenario | None:
    """Return the scenario registered under *key*, or None."""
    return next((s for s in SCENARIOS if s.key == key), None)
