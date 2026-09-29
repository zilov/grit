"""Lesson and scenario text for `grit tutorial` — data only, no engine logic."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEMO_YAML_HAPS = _CONFIG_DIR / "tutorial_demo.yaml"

# The demo YAML's `specimen` field — every tutorial ticket shares this fixture,
# so the AGP filename a manual_action writes can be hardcoded rather than
# re-parsed from the YAML each time.
_TOL_ID = "xxTutDemo1"


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
    shows: str = ""
    manual_action: Callable[[str], None] | None = None


@dataclass(frozen=True)
class Scenario:
    """A named lesson chain with its own demo ticket."""

    key: str
    title: str
    blurb: str
    yaml_path: Path
    ticket: str
    lessons: list[Lesson]
    difficulty: str = ""
    is_overview: bool = False  # tutorial 0: no sandbox, runs the real CLI


def _copy_agp_into_workdir(ticket: str) -> None:
    """Write a placeholder AGP where pretext-to-asm's dry-run sandbox expects one."""
    from grit.core.registry import dry_run_root

    agp_path = dry_run_root() / ticket / f"{_TOL_ID}.agp"
    agp_path.parent.mkdir(parents=True, exist_ok=True)
    agp_path.write_text(
        "SUPER_1\t1\t1000\t1\tW\tSCAFFOLD_1\t1\t1000\t+\n"
        "SUPER_2\t1\t800\t1\tW\tSCAFFOLD_2\t1\t800\t+\n"
    )


_STATUS_LESSON = Lesson(
    title="status — how to read what grit knows",
    why=(
        "Before running anything else, learn to read the one command you will run "
        "most often. `grit status -t <ticket>` prints three things:\n"
        "  • Canonical files — for each haplotype, which FASTA, haplotigs file and "
        "chromosome list grit currently considers *the* current one. This is the "
        "table that decides what later steps consume and what finalize-qc ships;\n"
        "  • Reference — the reference genome the ticket YAML names (if any) and "
        "what find-reference actually resolved;\n"
        "  • Step history — every run of every step, its status, and a Canonical "
        "column marking which outputs that particular run still owns.\n"
        "Right now only setup has run, so the canonical rows are all empty."
    ),
    task="Ask grit what it knows about this ticket.",
    command="status",
)

_AGP_MANUAL_LESSON = Lesson(
    title="Copy the curated AGP into the workdir",
    why=(
        "PretextView doesn't talk to grit directly. When you're done curating, "
        "PretextView exports an AGP file describing the edits — you save it "
        "locally, then scp it onto the farm into this ticket's workdir so "
        "pretext-to-asm can find it:\n"
        "  scp ~/curations/work/<tol_id>/<tol_id>*.agp* "
        "<farm host>:<workdir>/\n"
        "Here the tutorial does that copy for you, into the sandbox workdir."
    ),
    task="Press Enter once you've copied the AGP in.",
    command="",
    manual_action=_copy_agp_into_workdir,
)


def _grit(*argv: str) -> Callable[[str], None]:
    """Return a manual_action that runs `grit *argv` in-process, ignoring the ticket."""

    def action(_ticket: str) -> None:
        from grit.core.tutorial import _run_grit

        _run_grit(list(argv))

    return action


_TUTORIAL_0 = Scenario(
    key="overview",
    title="0 — Overview",
    blurb="What grit is and how it thinks, before you type a single step.",
    yaml_path=DEMO_YAML_HAPS,
    ticket="T-0",
    is_overview=True,
    lessons=[
        Lesson(
            title="What grit is",
            why=(
                "A curation ticket in Jira carries an assembly YAML — draft FASTA "
                "paths, HiC reads, the species' BUSCO lineage, and so on. `grit setup "
                "-t <ticket>` reads that YAML and builds a workdir for it on the farm; "
                "every later step reads and writes there. Every run of every step is "
                "recorded in a registry under ~/.grit/ — that's what `grit status` "
                "reads, and it's the only record of what has actually happened to a "
                "ticket.\n"
                "Most tickets carry two haplotypes (hap1/hap2). Some — primary/"
                "paternal assemblies — are single-hap: those tickets simply have no "
                "hap2 flags to pass; nothing is missing."
            ),
            task="Press Enter to continue.",
            command="",
            manual_action=lambda _ticket: None,
        ),
        Lesson(
            title="Canonical: decided by recency, not by a fixed order",
            why=(
                "At any moment, each haplotype has exactly one FASTA grit considers "
                "current — its canonical assembly. There is no fixed step order that "
                "decides this: whichever tracked step last produced a successful "
                "output for that haplotype is canonical, full stop. Run "
                "blast-contaminants after rename-and-orient and canonical moves to "
                "blast-contaminants; run rename-and-orient again after that and it "
                "moves back. `grit status -t <ticket>` is the only honest answer to "
                "'which file is current?' — the canonical-files table at the top, and "
                "the Canonical column in the step history below it."
            ),
            task="Press Enter to continue.",
            command="",
            manual_action=lambda _ticket: None,
        ),
        Lesson(
            title="--dry-run, --print-only, --untracked",
            why=(
                "Three flags every step understands, doing three different things:\n"
                "  • --print-only prints the real command grit would run — the "
                "actual bsub/tool invocation — without executing it;\n"
                "  • --dry-run runs the real sequencing/tracking/canonical logic but "
                "writes placeholder outputs instead of real ones, into an isolated "
                "sandbox under ~/.grit/dry_run/ — this whole tutorial runs under it, "
                "against fictional tickets, so nothing here touches Jira, LSF, "
                "lustre or your real registry;\n"
                "  • --untracked (-u) runs a step for real but keeps its output out "
                "of the canonical pool, no matter how fresh — for looking at a "
                "result without committing to it. `grit untrack`/`grit retrack` do "
                "the same after the fact, for a run you already let become canonical."
            ),
            task="Press Enter to continue.",
            command="",
            manual_action=lambda _ticket: None,
        ),
        Lesson(
            title="grit --help — every command, for real",
            why=(
                "Not a sandboxed copy — this runs the actual `grit --help` you'd get "
                "in your own terminal, so what you see now is what's really there."
            ),
            task="Press Enter to run it.",
            command="",
            manual_action=_grit("--help"),
        ),
        Lesson(
            title="grit status — your real queue, for real",
            why=(
                "And this is the real `grit status` with no -t — every ticket "
                "currently active in your actual registry, not a tutorial fixture. "
                "If you have no active tickets yet, that's exactly what it will say."
            ),
            task="Press Enter to run it.",
            command="",
            manual_action=_grit("status"),
        ),
    ],
)


_TUTORIAL_1 = Scenario(
    key="basic",
    title="1 — Basic curation",
    blurb="The core chain end to end: setup through finalize-qc, on a two-haplotype assembly.",
    yaml_path=DEMO_YAML_HAPS,
    ticket="T-1",
    difficulty="easy",
    lessons=[
        Lesson(
            title="setup — claim the ticket and build the workdir",
            why=(
                "Reads the ticket's YAML, creates the curation workdir, and copies the "
                "draft assembly into it as original.fa. Every later step resolves its "
                "inputs from what setup put there, so this always runs first. It does "
                "not copy the Pretext map — that map is downloaded separately (setup "
                "prints the scp command for it) and opened locally in PretextView."
            ),
            task="Run the setup step for this ticket. Every grit step needs -t <ticket>.",
            command="setup",
        ),
        _STATUS_LESSON,
        _AGP_MANUAL_LESSON,
        Lesson(
            title="pretext-to-asm — turn the curated map back into an assembly",
            why=(
                "After curating in PretextView you have an AGP file describing the "
                "edits — you just copied it into the workdir. pretext-to-asm takes the "
                "draft FASTA plus that AGP and writes an updated curated FASTA. Results "
                "land in workdir/pretext_to_asm/<timestamp>/ — the first step that "
                "produces a new *canonical* assembly."
            ),
            task=(
                "You have curated the Pretext map and copied the AGP in. Turn it back "
                "into an assembly. (? if you don't remember the step name.)"
            ),
            command="pretext-to-asm",
            check="both haplotypes' assembly FA now point into pretext_to_asm/",
        ),
        Lesson(
            title="hic-remapping — remap the HiC reads onto the curated assembly",
            why=(
                "Builds a fresh Pretext map from the curated assembly so you can look at "
                "it again for a second curation round. It produces a map, not an "
                "assembly, so it must not take canonical away from pretext-to-asm."
            ),
            task="Remap the HiC reads for the first haplotype.",
            command="hic-remapping",
        ),
        Lesson(
            title="hic-remapping — and now the second haplotype",
            why=(
                "hic-remapping's --hap2 is *exclusive*: it runs the second haplotype "
                "instead of the first, so a diploid ticket needs the command twice. "
                "Other steps treat --hap2 additively — you'll meet one later. Each "
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
            check="canonical FA is still pretext_to_asm — remapping never claims it",
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
        Lesson(
            title="pp — post-processing and submission prep",
            why=(
                "Runs the contamination screen and submission prep pipeline over the "
                "finalized release directory, then marks the ticket done in the "
                "registry. `pp` is a short alias for `post-processing` — both run the "
                "same step."
            ),
            task="Run post-processing on the finalized release.",
            command="pp",
        ),
        Lesson(
            title="status — the global view",
            why=(
                "`grit status` with no -t at all shows every active ticket, not just "
                "this one — species, last step, last run time, status. It's the view "
                "you'd use to see what's in flight across your whole queue. Because "
                "this tutorial runs under --dry-run, it reads the sandbox registry, so "
                "it lists tutorial tickets rather than your real work — the same command "
                "against your real terminal shows your real queue."
            ),
            task="Press Enter to see it.",
            command="",
            manual_action=_grit("--dry-run", "status"),
        ),
    ],
)


_TUTORIAL_2 = Scenario(
    key="references",
    title="2 — Working with references",
    blurb="Finding a reference genome and using it to check and rename chromosomes.",
    yaml_path=DEMO_YAML_HAPS,
    ticket="T-2",
    difficulty="medium",
    lessons=[
        Lesson(
            title="setup",
            why="Same first step as always — build the workdir and stage the draft assembly.",
            task="Set the ticket up.",
            command="setup",
        ),
        Lesson(
            title="find-reference — get something to compare against",
            why=(
                "Downloads the closest reference genome on NCBI for this species and "
                "preps it for the synteny/alignment steps below. If the automatic match "
                "picks the wrong species — it goes by name distance, not genome quality — "
                "pass --local /path/to/reference.fa to use a reference you already have "
                "instead of the NCBI search."
            ),
            task="Find the closest reference genome for this species.",
            command="find-reference",
        ),
        _AGP_MANUAL_LESSON,
        Lesson(
            title="pretext-to-asm",
            why=(
                "After curating in PretextView you have an AGP file, which you just "
                "copied into the workdir. pretext-to-asm takes the draft FASTA plus "
                "that AGP and writes an updated curated FASTA, into "
                "workdir/pretext_to_asm/<timestamp>/."
            ),
            task="Turn the curated map back into an assembly.",
            command="pretext-to-asm",
            check="both haplotypes' assembly FA now point into pretext_to_asm/",
        ),
        Lesson(
            title="busco-synteny — compare gene order against the reference",
            why=(
                "Plots BUSCO gene positions in the curated assembly against the "
                "reference, so you can see at a glance whether chromosome-scale synteny "
                "holds up. --lineage is required — grit does not guess it. This ticket's "
                "YAML carries busco_lineage: vertebrata_odb10; that's the value to pass. "
                "Because find-reference already ran, --reference is not needed here — "
                "it would only be for overriding the auto-search."
            ),
            task="Run BUSCO synteny using this ticket's busco_lineage value.",
            command="busco-synteny",
            args=["--lineage", "vertebrata_odb10"],
            flag_hints={
                "--lineage": (
                    "busco-synteny needs --lineage — use this ticket's busco_lineage "
                    "value from the YAML: vertebrata_odb10."
                )
            },
        ),
        Lesson(
            title="fastga — a second, alignment-based comparison",
            why=(
                "Runs a whole-genome dot-plot alignment (FastGA) of the curated assembly "
                "against the same reference — a different, complementary view from "
                "BUSCO synteny's gene-order one. Its PAF output is also what "
                "rename-and-orient reads later. --reference is optional here too, for "
                "the same reason: find-reference already ran."
            ),
            task="Run FastGA against the reference.",
            command="fastga",
        ),
        Lesson(
            title="fastga-stats — read the alignment as a table",
            why=(
                "Turns fastga's PAF into a plain table: for each curated scaffold, its "
                "best-matching reference chromosome and how much of it is covered. This "
                "is what you actually read to decide chromosome numbering, rather than "
                "eyeballing the dot plot."
            ),
            task="Summarise the FastGA alignment as a table.",
            command="fastga-stats",
        ),
        Lesson(
            title="super-to-scaffold — which scaffold is really each chromosome",
            why=(
                "After curation a chromosome (SUPER_n) can be made of more than one "
                "original scaffold. This reports the single largest scaffold within "
                "each SUPER and what fraction of it that scaffold makes up — the "
                "scaffold whose alignment you should trust when naming that chromosome."
            ),
            task="Report the largest scaffold within each curated chromosome.",
            command="super-to-scaffold",
        ),
        Lesson(
            title="Rename the sex chromosomes by hand, then re-curate",
            why=(
                "BUSCO synteny and FastGA showed you which curated chromosome "
                "corresponds to the reference's sex chromosome(s) — but that renaming "
                "happens back in PretextView, by hand: relabel the scaffold, re-export "
                "the AGP, and copy the new one in exactly like before. `grit status` "
                "would tell you when a fresh AGP is expected and where."
            ),
            task="Copy the new AGP in.",
            command="",
            manual_action=_copy_agp_into_workdir,
        ),
        Lesson(
            title="post-curation — pretext-to-asm and hic-remapping together",
            why=(
                "A shortcut for the two steps you'd otherwise run back to back: "
                "pretext-to-asm on the new AGP, then hic-remapping to build the next "
                "Pretext map. Pass --hap2 to also remap the second haplotype "
                "(additively — hap1 still runs)."
            ),
            task="Run post-curation for both haplotypes.",
            command="post-curation",
            args=["--hap2"],
            flag_hints={
                "--hap2": (
                    "post-curation's --hap2 is additive — it submits hic-remapping for "
                    "hap2 as well as hap1, both in the same run."
                )
            },
        ),
        Lesson(
            title="finalize-qc",
            why="Ships whatever is canonical right now into the release directory.",
            task="Build the release directory and the QC report.",
            command="finalize-qc",
            check="the assembly_curated/ path it printed — that is the release directory",
        ),
        Lesson(
            title="pp",
            why="Contamination screen and submission prep over the finalized release.",
            task="Run post-processing.",
            command="pp",
        ),
    ],
)


_TUTORIAL_3 = Scenario(
    key="canonical-changes",
    title="3 — Steps that change the canonical FASTA",
    blurb="Microchromosomes, contaminant screening, and a reference a collaborator already had.",
    yaml_path=DEMO_YAML_HAPS,
    ticket="T-3",
    difficulty="hard",
    lessons=[
        Lesson(
            title="setup",
            why="Same first step as always.",
            task="Set the ticket up.",
            command="setup",
        ),
        _AGP_MANUAL_LESSON,
        Lesson(
            title="pretext-to-asm",
            why=(
                "After curating in PretextView you have an AGP file, which you just "
                "copied into the workdir. pretext-to-asm takes the draft FASTA plus "
                "that AGP and writes an updated curated FASTA, into "
                "workdir/pretext_to_asm/<timestamp>/."
            ),
            task="Turn the curated map back into an assembly.",
            command="pretext-to-asm",
            check="both haplotypes' assembly FA now point into pretext_to_asm/",
        ),
        Lesson(
            title="microchromosome-second-shot — a closer look at the small chromosomes",
            why=(
                "Some assemblies (birds especially) have many small chromosomes that are "
                "easy to miscurate at whole-genome zoom. This splits the curated assembly "
                "into large and small scaffolds and builds a fresh, zoomed-in HiC map of "
                "just the small ones for a second curation pass."
            ),
            task="Run the microchromosome second-shot pre-step.",
            command="microchromosome-second-shot",
        ),
        Lesson(
            title="microchromosome-combine — merge the re-curated smalls back in",
            why=(
                "After curating the zoomed-in small-chromosome map and copying its AGP "
                "into the second-shot run's curated_small_agp/ directory, this rebuilds "
                "the small chromosomes from that AGP and stitches them back together "
                "with the large scaffolds from the first pass. Its merged output becomes "
                "the new canonical assembly."
            ),
            task="Combine the re-curated small chromosomes with the large ones.",
            command="microchromosome-combine",
            check="canonical FA moved again — now microchromosome_combine/",
        ),
        Lesson(
            title="blast-contaminants — screen the non-chromosome scaffolds",
            why=(
                "Blasts the non-SUPER scaffolds of the curated assembly — the shrapnel "
                "that didn't get placed into a chromosome — against core-nt. "
                "Chromosomes themselves are not blasted. It compares the phylum of each "
                "blast hit with the curated species' own phylum, and drops any scaffold "
                "whose phylum doesn't match. Watch canonical: grit has no hardcoded step "
                "order — the freshest successful tracked output wins, so canonical moves "
                "here simply because this ran last."
            ),
            task="Screen the curated assembly for contaminants.",
            command="blast-contaminants",
            check="canonical FA moved again — now blast_contaminants/",
        ),
        Lesson(
            title="find-reference --local — a reference a collaborator already had",
            why=(
                "A collaborator working on a related species asked for the chromosomes "
                "renamed and oriented against a reference they already had on disk, "
                "rather than whatever NCBI's automatic search would pick. --local skips "
                "the download and preps that file directly."
            ),
            task="Prep the collaborator's reference instead of searching NCBI.",
            command="find-reference",
            args=["--local", "/nfs/scratch/shared/collaborator_reference.fa"],
            flag_hints={
                "--local": (
                    "find-reference --local <path> preps a reference FASTA you already "
                    "have instead of downloading one from NCBI."
                )
            },
        ),
        Lesson(
            title="fastga — align against it",
            why=(
                "rename-and-orient works from a FastGA alignment, not the reference "
                "directly — this is what produces the PAF it will read next. "
                "--reference isn't needed here: find-reference (with --local) already ran."
            ),
            task="Align the curated assembly against the collaborator's reference.",
            command="fastga",
        ),
        Lesson(
            title="rename-and-orient — apply the collaborator's numbering",
            why=(
                "Reads fastga's PAF and renames/flips scaffolds so the chromosome "
                "numbering matches the reference. --hap2 here is *additive* — one "
                "invocation with it does both haplotypes in the same run, unlike "
                "hic-remapping's exclusive --hap2 you've seen before."
            ),
            task="Rename and orient the chromosomes for both haplotypes in one go.",
            command="rename-and-orient",
            args=["--hap2"],
            flag_hints={
                "--hap2": (
                    "rename-and-orient's --hap2 is additive — it adds the second "
                    "haplotype to the same run rather than replacing the first."
                )
            },
            check="canonical chained forward to rename_and_orient/",
        ),
        Lesson(
            title="hic-remapping",
            why="Build the next Pretext map from whatever is canonical now.",
            task="Remap the HiC reads for the first haplotype.",
            command="hic-remapping",
        ),
        Lesson(
            title="hic-remapping — second haplotype",
            why="Exclusive --hap2 again: one invocation per haplotype.",
            task="And the second haplotype.",
            command="hic-remapping",
            args=["--hap2"],
            flag_hints={
                "--hap2": (
                    "hic-remapping runs one haplotype per invocation — --hap2 selects the "
                    "second one instead of the first."
                )
            },
        ),
        Lesson(
            title="finalize-qc",
            why="Ships whatever is canonical right now.",
            task="Build the release directory and the QC report.",
            command="finalize-qc",
            check="the assembly_curated/ path it printed — that is the release directory",
        ),
        Lesson(
            title="pp",
            why="Contamination screen and submission prep over the finalized release.",
            task="Run post-processing.",
            command="pp",
        ),
    ],
)


_TUTORIAL_4 = Scenario(
    key="recurate",
    title="4 — Curating an already-curated map",
    blurb="A second curation round on an assembly that has already been through finalize-qc once.",
    yaml_path=DEMO_YAML_HAPS,
    ticket="T-4",
    difficulty="medium",
    lessons=[
        Lesson(
            title="setup",
            why="Same first step as always.",
            task="Set the ticket up.",
            command="setup",
        ),
        Lesson(
            title="post-curation — the first full round",
            why=(
                "Runs pretext-to-asm, haplotig-files and hic-remapping in sequence — a "
                "shortcut for the usual first-round chain, ending with a fresh Pretext "
                "map ready for a second look."
            ),
            task="Run the first post-curation round.",
            command="post-curation",
        ),
        Lesson(
            title="post-curation-recurate — curate the remapped map again",
            why=(
                "Same idea as pretext-to-asm, but it consumes the map hic-remapping just "
                "made and applies new edits on top of the already-curated assembly, then "
                "remaps again — a shortcut for pretext-to-asm-recurate + hic-remapping. "
                "Here --hap2 is *exclusive*, like post-curation-recurate's own hap2 "
                "flag but unlike post-curation's: it recurates hap2 instead of hap1, not "
                "in addition to it, so a diploid ticket needs the command twice."
            ),
            task="Recurate the first haplotype's remapped map.",
            command="post-curation-recurate",
        ),
        Lesson(
            title="post-curation-recurate — second haplotype",
            why="Same command, --hap2 this time to recurate the other haplotype instead.",
            task="And the second haplotype.",
            command="post-curation-recurate",
            args=["--hap2"],
            flag_hints={
                "--hap2": (
                    "post-curation-recurate's --hap2 is exclusive — it recurates hap2 "
                    "instead of hap1, so both haplotypes need their own invocation."
                )
            },
            check=(
                "the two haplotypes are tracked separately — hap1 is "
                "pretext_to_asm_recurate/, hap2 is pretext_to_asm_recurate_hap2/"
            ),
        ),
        Lesson(
            title="finalize-qc",
            why="Ships whatever is canonical now — the recurated assembly, not the first round.",
            task="Build the release directory and the QC report.",
            command="finalize-qc",
            check="the assembly_curated/ path it printed — that is the release directory",
        ),
        Lesson(
            title="pp",
            why="Contamination screen and submission prep over the finalized release.",
            task="Run post-processing.",
            command="pp",
        ),
    ],
)


_TUTORIAL_5 = Scenario(
    key="other",
    title="5 — Other commands",
    blurb="sex-matcher, an untracked contaminant check, and recovering from a bad rename.",
    yaml_path=DEMO_YAML_HAPS,
    ticket="T-5",
    difficulty="medium",
    lessons=[
        Lesson(
            title="setup",
            why="Same first step as always.",
            task="Set the ticket up.",
            command="setup",
        ),
        Lesson(
            title="sex-matcher — check for sex chromosomes",
            why=(
                "Runs a BUSCO-based comparison to spot likely sex chromosomes before you "
                "curate — mainly useful for insects and nematodes, which is why setup "
                "printed a tip about it when the ticket's ID matched. Its results show up "
                "as a Best_match file, and `grit status` will list this run once it's done."
            ),
            task="Run sex-matcher.",
            command="sex-matcher",
        ),
        _AGP_MANUAL_LESSON,
        Lesson(
            title="pretext-to-asm",
            why=(
                "After curating in PretextView you have an AGP file, which you just "
                "copied into the workdir. pretext-to-asm takes the draft FASTA plus "
                "that AGP and writes an updated curated FASTA, into "
                "workdir/pretext_to_asm/<timestamp>/."
            ),
            task="Turn the curated map back into an assembly.",
            command="pretext-to-asm",
            check="both haplotypes' assembly FA now point into pretext_to_asm/",
        ),
        Lesson(
            title="blast-contaminants --untracked — look without committing",
            why=(
                "Blasts the non-SUPER scaffolds against core-nt and compares phylum to "
                "flag contaminants, same as always — but --untracked means this run's "
                "output is never canonical, no matter how fresh it is. That's the point "
                "here: you want to *see* what blast calls a contaminant so you can decide "
                "by hand whether to remove it from the map yourself, without this run "
                "silently becoming the assembly every later step consumes."
            ),
            task="Run the contaminant screen without letting it become canonical.",
            command="blast-contaminants",
            args=["--untracked"],
            flag_hints={
                "--untracked": (
                    "--untracked (-u) runs the step but keeps its output out of the "
                    "canonical pool — useful for looking without committing."
                )
            },
        ),
        Lesson(
            title="Remove the flagged scaffold by hand, then copy the new AGP in",
            why=(
                "Having seen what blast-contaminants flagged, you delete that scaffold "
                "in PretextView yourself, re-export, and copy the new AGP in — the same "
                "action as always."
            ),
            task="Copy the new AGP in.",
            command="",
            manual_action=_copy_agp_into_workdir,
        ),
        Lesson(
            title="post-curation",
            why="pretext-to-asm on the new AGP, then hic-remapping, in one command.",
            task="Run post-curation.",
            command="post-curation",
        ),
        Lesson(
            title="find-reference",
            why="Get a reference to align and rename against.",
            task="Find the closest reference genome.",
            command="find-reference",
        ),
        Lesson(
            title="fastga",
            why="Align the curated assembly against it — rename-and-orient reads this PAF next.",
            task="Run FastGA against the reference.",
            command="fastga",
        ),
        Lesson(
            title="rename-and-orient — and this time we forgot --untracked",
            why=(
                "Renames and orients both haplotypes from the FastGA alignment — but "
                "suppose the result comes out wrong (a bad reference match, a coverage "
                "threshold that renamed too little) and, worse, you forgot --untracked, "
                "so this bad output is now canonical. Nothing is lost; the next lesson "
                "backs it out."
            ),
            task="Rename and orient both haplotypes.",
            command="rename-and-orient",
            args=["--hap2"],
            flag_hints={
                "--hap2": (
                    "rename-and-orient's --hap2 is additive — both haplotypes in the same run."
                )
            },
            check="canonical FA moved to rename_and_orient/ — the run you don't want",
        ),
        Lesson(
            title="untrack — put canonical back",
            why=(
                "`grit untrack` marks a step's latest run non-canonical without deleting "
                "anything — the run dir, files and history all stay, they just stop "
                "counting. Canonical falls back to the next-freshest tracked output. "
                "It needs -s / --step, and takes the tracker's step name "
                "(rename_and_orient), not the CLI command name."
            ),
            task="Demote the bad rename-and-orient run.",
            command="untrack",
            args=["-s", "rename_and_orient"],
            flag_hints={
                "--step": (
                    "untrack needs to know which step to demote: -s rename_and_orient "
                    "(underscores — that is the tracker's name for it)."
                )
            },
            check="canonical fell back to pretext_to_asm/",
            shows=(
                "untrack runs nothing on the farm — no bsub, no tool. It appends a "
                'status="untracked" record for this run straight to the registry, so '
                "canonical resolution skips it from then on."
            ),
        ),
        Lesson(
            title="rename-and-orient --mapping-table — redo it correctly",
            why=(
                "With the coverage threshold or the reference sorted out, redo the "
                "rename with a pre-built mapping table instead of a fresh FastGA PAF — "
                "useful when you already know the correct chromosome-to-scaffold mapping "
                "and don't want to re-run the alignment. --mapping-table is used for "
                "every haplotype in the run, so no separate --hap2 pass is needed here."
            ),
            task="Redo the rename using a correct, pre-built mapping table.",
            command="rename-and-orient",
            args=["--mapping-table", "table.tsv"],
            flag_hints={
                "--mapping-table": (
                    "--mapping-table (-mt) <file> reuses a pre-built chromosome mapping "
                    "instead of a FastGA PAF — no fresh alignment needed."
                )
            },
            check="canonical is rename_and_orient/ again, this time the correct run",
        ),
        Lesson(
            title="finalize-qc",
            why="Ships whatever is canonical now — the corrected rename.",
            task="Build the release directory and the QC report.",
            command="finalize-qc",
            check="the assembly_curated/ path it printed — that is the release directory",
        ),
        Lesson(
            title="pp",
            why="Contamination screen and submission prep over the finalized release.",
            task="Run post-processing.",
            command="pp",
        ),
    ],
)


SCENARIOS: list[Scenario] = [
    _TUTORIAL_0,
    _TUTORIAL_1,
    _TUTORIAL_2,
    _TUTORIAL_3,
    _TUTORIAL_4,
    _TUTORIAL_5,
]


def find_scenario(key: str) -> Scenario | None:
    """Return the scenario registered under *key*, or None."""
    return next((s for s in SCENARIOS if s.key == key), None)
