# 54 — `grit tutorial`: type the commands, branch by scenario

## Problem

The MVP (`TODO/done/53_tutorial_walkthrough.md`) walks a curator through a whole
dry-run curation, but it teaches by demonstration only. Three concrete faults
came out of the first real run-through:

1. **Nothing is typed.** The learner presses Enter eleven times. They watch
   eleven correct commands scroll past and retain none of them — no muscle
   memory for `-t`, for the exclusive-vs-additive `--hap2`, for the step names.
2. **Any input runs the step.** Only `s` and `q` are special; a typo, a stray
   word, an accidental paste all mean "go". There is no way to ask for a hint
   and no way to re-read the explanation.
3. **`grit status` prints itself.** Running it automatically after most lessons
   turns the session into a wall of output that appears without being asked
   for, so nobody reads it — which is exactly backwards, because reading the
   canonical table *is* the skill being taught.

And the single linear chain only ever shows the diploid happy path; single-hap
tickets and "I ran the wrong step" are where new curators actually get stuck.

## Design

### The prompt becomes a small shell

Each lesson states a task in prose and waits for the learner to type the
command. The tutorial supplies its own plumbing (`--config`, `--yaml`,
`--dry-run`) and runs **whatever** grit command was typed — but only advances
to the next lesson when the typed command matches the lesson's expected one.

That one rule gets `grit status` for free: it can be typed at any moment, it
runs, and the lesson stays put. So can `grit <cmd> --help`.

```
> grit pretext-to-asm -t TUTORIAL-1     matches  -> runs, lesson advances
> grit status -t TUTORIAL-1             runs, still on this lesson
?   a hint naming what is actually wrong        ??  reveal the answer
r   re-read the explanation      s  skip      q  quit
```

Anything that is not one of those keys and does not start with `grit` is
rejected with a nudge instead of being treated as "run it".

### Matching and hints

Both sides are normalised to `(subcommand, ticket, frozenset(flags))`: long
aliases for short options, `--step`/`-s` keeps its value, `--dry-run` ignored
(the tutorial adds it either way). Hints are checked in order and name the
actual fault — wrong subcommand, missing `-t`, wrong ticket, a missing flag
(with the lesson's own explanation of why that flag exists), an extra flag, an
unknown command. This is pure string logic with no I/O, so it is unit-tested
directly.

### `status` is a lesson, then a habit

Lesson 2 of every scenario is `grit status` itself: the curation summary, the
Canonical files table, the step history and its Canonical column. After that,
a lesson that changes canonical state carries a `check` line — "run status and
find: canonical FA now points into `blast_contaminants/`" — and the learner
runs it. Nothing prints on its own.

### Scenarios

A menu replaces the single chain, each entry with its own demo YAML and lesson
list:

- **standard** — diploid hap1/hap2, setup through finalize-qc
- **single-hap** — `primary`/`alternate`, so the absence of the hap2 steps is
  something the curator sees rather than something they trip over later
- **oops** — short: canonical follows recency, `untrack`/`retrack` back out of
  a step without deleting anything

Microchromosomes were considered and left out unless `second-shot` and
`combine` compose cleanly in a dry-run chain; a scenario that needs its steps
bent to fit teaches the wrong thing.

### Safety

The tutorial always injects `--dry-run` at the group level, so `done`,
`reopen`, `remove` and `cleanup` refuse by themselves. `init` is the one
command that writes real state without consulting `dry_run`, so the prompt
rejects it explicitly.

### Layout

`grit/core/tutorial.py` keeps the engine (prompt loop, matcher, hints, runner);
the lesson and scenario text moves to `grit/core/tutorial_lessons.py`, which is
almost entirely prose and would otherwise dominate the engine file.
`--auto` runs each lesson's expected command (and its status check)
unprompted — that is what the smoke test drives, now across every scenario.
