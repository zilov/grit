# 55 — `grit tutorial`: curriculum, engine gaps, and terminal usability

Follows `TODO/done/53_tutorial_walkthrough.md` (the MVP) and
`TODO/done/54_tutorial_interactive.md` (typed commands, hints, three scenarios).
Numbers in parentheses are the items from the review this came out of, kept so
nothing is silently dropped.

## Problem

The tutorial teaches a single happy path with three scenarios invented while
building it. Real curation has more shapes than that, several of the commands a
curator uses daily never appear, and two of the explanations are simply wrong
about what the step does. On top of that the prompt is not a usable terminal
line: no cursor movement, no history.

## Design

### A. Engine and usability

- **(7, 8) Line editing and history.** `click.prompt` goes through `input()`,
  which only gets line editing when the `readline` module has been imported.
  Importing it in `tutorial.py` (guarded — it is absent on some platforms)
  gives arrow-key cursor movement *and* up/down history in one change. Today a
  learner who typos `grti` and presses left gets `grti^[[D^[[D`.
- **(4) Show what grit actually runs.** The biggest gap: a learner watches a
  step "succeed" with no idea what was submitted. Preferred implementation:
  before running the step under `--dry-run`, run the same command with
  `--print-only`, which prints the real `bsub`/tool invocation without
  executing it (print_only takes precedence over dry_run, so this is the real
  command string, not the dry-run branch). Displayed under a
  "what this runs on the farm" heading. Risk to verify per step: a print_only
  pass resolves real input paths and may fail on a sandbox ticket whose inputs
  are placeholders; where it does, fall back to a per-lesson `shows:` string.
- **(5) Short ticket IDs.** `TUTORIAL-1`/`TUTORIAL-SOLO`/`TUTORIAL-OOPS` are
  tedious to type on every line. Use `T-0` … `T-5`, matching the tutorial
  number. The sandbox is keyed by ticket ID, so the tutorials stay isolated.
- **(9) status at any time.** Already implemented in 54 (`_safe_to_run`): only
  `grit status` for this ticket and `--help` run out of turn; every other
  command must be the lesson's own. No change — listed to confirm it is done.
- **(1) `grit status` with no ticket.** The global view (active tickets, done
  counts) is used as often as the per-ticket one and never appears. Add it to
  tutorial 0 and again at the end of tutorial 1. Note the tutorial's own
  `--dry-run` makes it read the sandbox registry, so it shows the tutorial
  tickets, not real work — worth saying out loud in the lesson.
- **Manual steps.** Several tutorials need "now copy the AGP into the workdir"
  — a curator action with no grit command. Add a lesson kind with no expected
  command that explains the real `scp`, writes the placeholder file the next
  step needs, and continues on Enter.
- **Difficulty labels.** The scenario menu shows easy/medium/hard per the
  curriculum below.

### B. Text corrections

- **(2) setup.** It does not copy the Pretext map. Drop the parenthetical about
  how the workdir is derived from the draft dir — it is implementation detail
  the learner cannot act on.
- **(3) pretext-to-asm.** Rewrite to: after curating in PretextView you have an
  AGP file, which you copy into the workdir so grit can see it; pretext-to-asm
  takes the draft FASTA plus that AGP and writes an updated curated FASTA;
  results land in `workdir/pretext_to_asm/<timestamp>/`.
- **(6) blast-contaminants.** Rewrite to: blasts the non-SUPER scaffolds of the
  curated assembly (chromosomes are not blasted) against core-nt, compares the
  phylum of the curated species with the blast hits, and drops any scaffold
  whose phylum does not match.

### C. Curriculum

Six tutorials replace the current three scenarios.

**0 — Overview (no commands).** What grit is: a ticket in Jira carries the
assembly YAML, `grit setup` turns that into a workdir on the farm, and the
registry in `~/.grit/` remembers every run. What canonical files are and why
they are decided by recency rather than a fixed step order. What `--dry-run`,
`--print-only` and `--untracked` mean. `grit --help` and `grit status` with no
ticket. Ends by listing tutorials 1-5 and how to start each.

**1 — Basic (easy).** `setup`, `status`, `pretext-to-asm`, `hic-remapping`,
`finalize-qc`, `pp`.

**2 — Working with references (medium).** `setup`, `find-reference` (mention
`--local` for when the automatic match is wrong), `pretext-to-asm`,
`busco-synteny`, `fastga`, `fastga-stats`, `super-to-scaffold`; then renaming
the sex chromosomes by hand from what BUSCO and FastGA showed, copying the new
AGP in as `grit status` suggests; then `post-curation` (pretext-to-asm +
hic-remapping), `finalize-qc`, `pp`.

**3 — Steps that change the canonical FASTA (hard).** `setup`,
`pretext-to-asm`, `microchromosome-second-shot`, `microchromosome-combine`,
`blast-contaminants`, `find-reference --local` (the case where a collaborator
asked for renaming and orientation against a reference they already have),
`fastga` (rename-and-orient consumes its PAF), `rename-and-orient`,
`hic-remapping`, `finalize-qc`, `pp`.

**4 — Curating an already-curated map (medium).** `setup`, `post-curation`,
`post-curation-recurate` (or `pretext-to-asm-recurate` + `hic-remapping`),
`finalize-qc`, `pp`.

**5 — Other commands (medium).** `setup`, `sex-matcher` (results show up in
`status`), `pretext-to-asm`, `blast-contaminants --untracked` (why: to see what
blast calls a contaminant and then remove it from the map by hand instead),
copy the AGP, `post-curation`, `find-reference` + `fastga`, `rename-and-orient`
— which this time we *forgot* to mark `--untracked` and whose output we do not
like — then `grit untrack -t T-5 -s rename_and_orient` to put canonical back on
the last `pretext_to_asm` run, and finally
`rename-and-orient --mapping-table table.tsv` with the correct chromosome
naming.

(12) `find-reference` before `rename-and-orient`, with a `grit status` after it
so the learner sees the reference appear, is covered by tutorials 2, 3 and 5.
(13)-(18) `busco-synteny`, `fastga`, `fastga-stats`, `super-to-scaffold`, `pp`,
`post-curation`, `post-curation-recurate` are all placed above.

Corrections to the request, from checking the actual CLI:

- the flag is `--untracked` / `-u`, not `--untrack`;
- `grit untrack` takes `-t <ticket> -s <step>` and the step is the tracker's
  name, with underscores (`rename_and_orient`);
- `busco-synteny` requires `--lineage`; the demo YAMLs carry `busco_lineage`,
  so the lesson should use that value and say where it came from;
- `busco-synteny` and `fastga` take an optional `--reference`; after
  `find-reference` has run they do not need it, which is worth stating.

### D. Out of scope here

- **(10) Canonical map** in the canonical-files table is a change to grit
  itself, not to the tutorial — see `TODO/56_canonical_map.md`.
- **(19) `grit cleanup`** is taught as an explanation only, with no run. It
  takes no `--ticket`, it sweeps *done* tickets from the real registry, and it
  refuses `--dry-run` — as does `grit done`, which would have to run first.
  Giving both dry-run support was considered and rejected for now: the lesson
  covers what cleanup deletes, when to run it, and why it is already a preview
  without `--yes`.
- **(11) Branch hygiene** — done: the tutorial commits live on `tutorial`, and
  `test_and_fix_steps` was reset to the commit before them.

## Decisions taken

- **cleanup** — explain only, no run, no dry-run support added (above).
- **single-hap** — the `primary`/`alternate` scenario from 54 is dropped, along
  with `grit/config/tutorial_demo_primary.yaml`. Tutorial 0 mentions in one
  line that single-hap tickets exist and simply have no hap2 flags.
- **(4) commands under the hood** — always shown, always derived automatically
  from a `--print-only` pass, never hand-written. If a step's print_only path
  cannot run against a sandbox ticket, fix that step or say nothing for it; a
  hand-written command string that can drift from the code is not acceptable.
