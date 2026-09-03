# grit — usage examples

## Contents

- [1. Installation](#1-installation)
- [2. Standard workflow](#2-standard-workflow)
- [3. Optional steps](#3-optional-steps)
- [4. `grit status`](#4-grit-status)
- [5. Useful flags](#5-useful-flags)
- [6. Which file is "canonical"](#6-which-file-is-canonical)
  - [Seeing it](#seeing-it)
- [7. Undoing a step with `untrack` and `retrack`](#7-undoing-a-step-with-untrack-and-retrack)
  - [What untrack does not cover: several `fastga` runs](#what-untrack-does-not-cover-several-fastga-runs)
  - [Running a step without it counting](#running-a-step-without-it-counting)
- [8. Re-curating an already-curated map](#8-re-curating-an-already-curated-map)
- [9. Worked pipelines, with canonical shown at each step](#9-worked-pipelines-with-canonical-shown-at-each-step)
  - [Ordinary genome](#ordinary-genome)
  - [Ordinary, with hap2 also curated](#ordinary-with-hap2-also-curated)
  - [Analysis steps, which never change canonical](#analysis-steps-which-never-change-canonical)
  - [Microchromosomes (birds)](#microchromosomes-birds)
  - [Contaminant check](#contaminant-check)
  - [Rename and orient](#rename-and-orient)
  - [Re-curating the remapped map](#re-curating-the-remapped-map)
  - [Everything at once: contaminants, renaming, then recuration](#everything-at-once-contaminants-renaming-then-recuration)

## 1. Installation

```bash
git clone https://github.com/zilov/grit.git
cd grit
uv tool install .   # don't forget the trailing dot
```

If `uv` is not available:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Re-ssh into the farm and `uv` should be available.

Initialize the config:

```bash
grit init
```

This creates `~/.grit/grit_curation_config.yaml`, pre-filled with your username
and Sanger-wide defaults. You can also set `email` there — if filled in, you'll
get email notifications after `hic-remapping` (curationpretext) finishes.

To upgrade to a newer version:

```bash
git pull && uv tool upgrade grit --reinstall
```

## 2. Standard workflow

```bash
# 1. Set up the ticket — downloads the assembly, copies pretext maps, etc.
grit setup -t RC-1234

# grit waits until the .agp file appears in the workdir — curate genome manually 
# in PretextView and copy agp to the workdir to continue

# 2. Post-curation — runs the whole chain (pretext-to-asm, haplotig-files,
# hic-remapping/curationpretext) in one go. Add --hap2 if you want to run
# curationpretext for both haplotypes
grit post-curation -t RC-1234
grit post-curation -t RC-1234 --hap2

# or run the steps individually:
grit pretext-to-asm -t RC-1234
grit haplotig-files -t RC-1234
grit hic-remapping -t RC-1234 # hap1 only
grit hic-remapping -t RC-1234 --hap2 # hap2 only

# 3. Copying results to curated directory + run qv/completeness check
grit finalize-qc -t RC-1234

# 4. Post-processing (short alias — pp)
grit pp -t RC-1234
```

## 3. Optional steps

Run these as needed, typically after `setup` or after `pretext-to-asm`.

```bash
# Find the closest reference genome (needed before fastga/busco-synteny,
# unless you pass those steps an explicit --reference)
grit find-reference -t RC-1234

# The search doesn't always pick the genome you want. When you already have a
# better one, point at it instead — this skips the NCBI download and preps your
# file the same way, so every later step finds it where it expects to:
grit find-reference -t RC-1234 --local /path/to/reference.fa

# Determine sex from BUSCO (typically right after setup - runs on original.fa)
grit sex-matcher -t RC-1234

# FastGA synteny of curated fasta against a reference 
# (after find-reference AND pretext-to-asm, or with an explicit --reference)
grit fastga -t RC-1234
grit fastga -t RC-1234 --reference /path/to/reference.fa
grit fastga-stats -t RC-1234 # table - top ref chromosome alignment for each super  
grit fastga-synteny -t RC-1234 --min-align-len 10000 ## not properly tested yet

# BUSCO on the curated assembly (after pretext-to-asm)
grit busco-curated -t RC-1234 --lineage insecta_odb10

# BUSCO synteny between curated fasta and reference (after pretext-to-asm)
grit busco-synteny -t RC-1234 --lineage insecta_odb10
grit busco-synteny -t RC-1234 --lineage insecta_odb10 --reference /path/to/reference.fa

# Contamination screening (after pretext-to-asm)
grit blast-contaminants -t RC-1234

# Rename and orient scaffolds against a reference (after pretext-to-asm)
grit rename-and-orient -t RC-1234
grit rename-and-orient -t RC-1234 --hap2

# Check which scaffold is the largest in super from the AGP (after pretext-to-asm/post-curation)
grit super-to-scaffold -t RC-1234 # outputs table super - largest scaffold 

# Second pass over microchromosomes if the first curation pass didn't split them
grit microchromosome-second-shot -t RC-1234 # before microchromosome curation
grit microchromosome-combine -t RC-1234 # after microchromosome curation
```

## 4. `grit status`

```bash
# All active tickets at a glance + curation summary from grit registry
grit status
```

Prints a table of every active ticket — ticket ID, days in curation, ToL ID, species, last step
run, last run time, and status (`success`/`failed`/`running`).

```bash
# Full history + next-step guidance for one ticket
grit status -t RC-1234
```

For a single ticket this prints, in order:

- **Curation summary** — species, assembly type, workdir, and other metadata
  pulled from the ticket.
- **Canonical files** table — assembly FASTA / haplotigs FASTA / chr list for
  each haplotype, with a ✓/✗ for whether each one was found. Canonical FASTA used
  as input for (almost) all steps.
- **Step history** table — every step run for the ticket, with run count,
  last-run timestamp, live status, job ID, and an `agp_copied` row showing whether the
  curated `.agp` has landed in the workdir yet.
- **scp / less tips** — ready-to-paste commands for pulling result files
  (FastGA plots, BUSCO synteny plots, remapped pretext maps) down to your
  local machine, or `less`-ing a summary file directly on the farm, for any
  step that completed successfully.
- **AGP copy command** — the exact `scp` command to copy your locally-saved
  `.agp` from PretextView up to the workdir.
- **Next-step tip** — one of:
  - re-run `grit post-curation -t RC-1234` if the AGP or `original.fa` is
    newer than the curated FASTA (curation changed since the last post-curation run)
  - run `grit post-curation -t RC-1234` if the AGP was just copied and
    post-curation hasn't run yet
  - run `grit finalize-qc -t RC-1234` once HiC remapping succeeded
  - for bird genomes (ToL ID starting with `b`) that haven't run
    microchromosome second-shot yet, a reminder that it may be needed
- **Submission notes** link, once `merquryk` output exists in the curated dir.

## 5. Useful flags

```bash
# Print the commands a step would run, without running them
grit setup -t RC-1234 --print-only

# Increase bsub ram for some steps
grit [step] -t RC-1234 --bsub-ram NUM

# Run a step without its output counting as canonical (see §7)
grit [step] -t RC-1234 --untracked
```

`--print-only` shows you the command; it runs nothing and changes nothing.

There is also `--dry-run`, which is **for developing and testing grit itself,
not for curation work**. It runs no real command: each step writes placeholder
outputs into an isolated sandbox under `~/.grit/dry_run/`, so step sequencing,
tracking and canonical resolution can be exercised end to end with no farm or
NFS access. It never touches the real registry, a real workdir or the curated
release directory.

```bash
grit --dry-run setup -t RC-1234
grit --dry-run pretext-to-asm -t RC-1234
grit --dry-run status -t RC-1234
```

If both flags are given, `--print-only` wins.

## 6. Which file is "canonical"

Most post-curation steps don't read a fixed filename — they read **the canonical
FASTA** for a haplotype, whatever that currently is. Five commands produce a new
candidate for it:

```
pretext-to-asm
microchromosome-combine
blast-contaminants
rename-and-orient          (and --hap2)
pretext-to-asm-recurate    (and --hap2)
```

The rule is simply **the freshest output wins** — compared by file modification
time. No step outranks another, and there is no special case for recurate: if
you run `blast-contaminants` again after a recurate round, that rerun becomes
canonical. This is what lets you keep chaining steps after re-curating without
untracking anything first.

Two details worth knowing:

- It is decided **per haplotype**. Recurating hap1 does not touch hap2's
  canonical file.
- The chromosome list and haplotigs follow the same rule over smaller sets —
  `blast-contaminants` doesn't affect the chromosome list, and only
  `pretext-to-asm`/`pretext-to-asm-recurate` affect haplotigs. So a recurate run
  can legitimately own the haplotigs while a later `rename-and-orient` owns the
  FASTA. That is not a conflict.

Steps like `hic-remapping`, `qv` and `finalize-qc` read the canonical files but
never become canonical themselves.

### Seeing it

```bash
grit status -t RC-1234
```

Two places in that output answer the question:

- the **Canonical files** table — the actual path per haplotype for assembly
  FASTA, haplotigs and chromosome list, with a ✓/✗ for whether it's still on
  disk;
- the **Canonical** column in the step-history table — marks which step each
  file currently comes from: `fa` (assembly FASTA), `hap` (haplotigs), `chr`
  (chromosome list), with a `(1)`/`(2)` haplotype index when the ticket has more
  than one. A row reading `hap(1),chr(1)` and a later row reading `fa(1)` means
  they own different files, not that they disagree.

If one of these steps ran and you are not happy with the result, **you do not
have to redo the pipeline**. The step's output is canonical only because it is
the freshest one — demote it and the previous file takes over again:

```bash
grit untrack -t RC-1234 --step blast_contaminants
```

Nothing is deleted and no other step re-runs. See
[§7](#7-undoing-a-step-with-untrack-and-retrack) for the details.

The full decision path, including where each step takes its input from, is in
[`recuration-canonical-priority.md`](recuration-canonical-priority.md).

## 7. Undoing a step with `untrack` and `retrack`

`untrack` marks a step's latest run as non-canonical, so the next-freshest
output takes over as the canonical file:

```bash
grit untrack -t RC-1234 --step blast_contaminants
```

It changes nothing else: the files stay on disk, the run stays in the step
history, and no other step re-runs. Use it when a step made things worse —
`blast-contaminants` stripped something it shouldn't have, `rename-and-orient`
ran against the wrong reference — instead of re-running the chain from
`pretext-to-asm`.

The step name is the tracker name (underscores, as shown in the step-history
table), and each haplotype's run is its own name — `rename_and_orient` and
`rename_and_orient_hap2` are untracked separately.

To bring it back:

```bash
grit retrack -t RC-1234 --step blast_contaminants
```

`retrack` promotes that run again using the outputs it recorded when it ran, so
it works even if the run has since scrolled far down the history.

A typical loop is: check what's canonical now, demote, check again.

```bash
grit status -t RC-1234                                  # Canonical column: fa(1) on blast_contaminants
grit untrack -t RC-1234 --step blast_contaminants
grit status -t RC-1234                                  # fa(1) moved back to the previous step
```

### What untrack does not cover: several `fastga` runs

`untrack` only moves the **canonical** files. A step whose output is consumed as
a step *input* rather than as a canonical file is not affected by it.

`fastga` is the case that comes up: if you ran it against two references,
`rename-and-orient` takes the PAF from the newest `fastga` run directory on
disk, and untracking that run does not send it back to the earlier one. To
rename against a different reference, re-run `fastga` against the one you want —
its run directory becomes the newest — or hand `rename-and-orient` a mapping
table directly:

```bash
grit fastga -t RC-1234 --reference /path/to/the_one_you_want.fa
grit rename-and-orient -t RC-1234

# or skip the PAF entirely
grit rename-and-orient -t RC-1234 --mapping-table /path/to/mapping.tsv
```

### Running a step without it counting

If you already know a run is exploratory — comparing two references, testing a
lineage — pass `--untracked` and it never becomes canonical in the first place:

```bash
grit rename-and-orient -t RC-1234 --untracked
```

The run still appears in `grit status` with its outputs recorded, just marked
untracked. If the result turns out to be the one you want after all, promote it
with the same `retrack` command above — no re-run needed.

`--untracked` works on every step.

## 8. Re-curating an already-curated map

After `hic-remapping` you get `{hap}_remapped.pretext` — the Hi-C map rebuilt
against the curated assembly. If it needs another round of manual curation:

```bash
# 1. Pull the remapped map down and curate it in PretextView as usual.
#    `grit status -t RC-1234` prints a ready-to-paste scp command for it.

# 2. Copy the new AGP into the recurate directory (not the workdir root)
scp yourmap.agp farm:{workdir}/recurate/{tol_id}.{hap}.recurate.agp

# 3. Build the new assembly from it
grit pretext-to-asm-recurate -t RC-1234           # hap1 / primary
grit pretext-to-asm-recurate -t RC-1234 --hap2    # hap2 / alternate

# 4. Remap Hi-C against the new assembly
grit hic-remapping -t RC-1234 [--hap2]

# steps 3 and 4 in one go:
grit post-curation-recurate -t RC-1234 [--hap2]
```

The recurate step reads whatever is canonical at that moment as its input, and
its own output becomes canonical. Repeat from step 1 for another round, or
carry on with `blast-contaminants` / `rename-and-orient` — each of those, run
now, becomes canonical in turn.

```bash
grit finalize-qc -t RC-1234
```

## 9. Worked pipelines, with canonical shown at each step

Each block shows what `grit status -t` would report as canonical after each
command. `fa` = assembly FASTA, `chr` = chromosome list, `hap` = haplotigs.
Steps not listed in the pool (see [§6](#6-which-file-is-canonical)) read the
canonical files but never
become canonical themselves.

### Ordinary genome

```bash
grit setup -t RC-1234
# curate in PretextView, copy the AGP into the workdir

grit post-curation -t RC-1234        # pretext-to-asm + haplotig-files + hic-remapping
#   fa, chr, hap  ->  pretext_to_asm

grit finalize-qc -t RC-1234          # reads the canonical files, changes nothing
grit pp -t RC-1234
```

### Ordinary, with hap2 also curated

```bash
grit setup -t RC-1234
# curate both haplotypes, copy both AGPs into the workdir

grit post-curation -t RC-1234 --hap2   # here --hap2 means ALSO hap2, hap1 still runs
#   hap1:  fa, chr, hap  ->  pretext_to_asm
#   hap2:  fa, chr, hap  ->  pretext_to_asm

grit finalize-qc -t RC-1234
grit pp -t RC-1234
```

One `pretext-to-asm` run produces both haplotypes' files, so both haplotypes
point at the same step.

### Analysis steps, which never change canonical

```bash
grit setup -t RC-1234
grit sex-matcher -t RC-1234          # runs on original.fa, before curation
grit find-reference -t RC-1234
# curate, copy the AGP

grit post-curation -t RC-1234
#   fa, chr, hap  ->  pretext_to_asm

grit fastga -t RC-1234               # all of these read the canonical FASTA
grit fastga-stats -t RC-1234
grit busco-curated -t RC-1234
grit busco-synteny -t RC-1234
grit qv -t RC-1234
grit super-to-scaffold -t RC-1234
#   fa, chr, hap  ->  pretext_to_asm    (unchanged — none of them join the pool)

grit finalize-qc -t RC-1234
```

### Microchromosomes (birds)

```bash
grit setup -t RC-1234
# curate, copy the AGP

grit pretext-to-asm -t RC-1234
#   fa, chr, hap  ->  pretext_to_asm

grit microchromosome-second-shot -t RC-1234   # reads canonical, doesn't change it
# curate the merged microchromosome map, copy the new AGP into the workdir

grit microchromosome-combine -t RC-1234
#   fa, chr  ->  microchromosome_combine
#   hap      ->  pretext_to_asm            (combine doesn't produce haplotigs)

grit hic-remapping -t RC-1234
grit finalize-qc -t RC-1234
```

### Contaminant check

```bash
grit setup -t RC-1234
# curate, copy the AGP

grit pretext-to-asm -t RC-1234
#   fa, chr, hap  ->  pretext_to_asm

grit blast-contaminants -t RC-1234
#   fa   ->  blast_contaminants
#   chr  ->  pretext_to_asm
#   hap  ->  pretext_to_asm

grit hic-remapping -t RC-1234
grit finalize-qc -t RC-1234
```

### Rename and orient

```bash
grit setup -t RC-1234
# curate, copy the AGP

grit pretext-to-asm -t RC-1234
grit find-reference -t RC-1234               # or --local /path/to/reference.fa
                                             # if the search picks the wrong genome
grit fastga -t RC-1234                       # rename-and-orient needs its PAF,
                                             # unless you pass --mapping-table

grit rename-and-orient -t RC-1234 --hap2     # here --hap2 means ALSO hap2,
                                             # reusing hap1's mapping table
#   hap1:  fa, chr  ->  rename_and_orient
#   hap2:  fa, chr  ->  rename_and_orient_hap2
#   both:  hap      ->  pretext_to_asm       (it doesn't produce haplotigs)

grit hic-remapping -t RC-1234
grit finalize-qc -t RC-1234
```

### Re-curating the remapped map

```bash
grit setup -t RC-1234
# curate, copy the AGP

grit post-curation -t RC-1234
#   fa, chr, hap  ->  pretext_to_asm

# curate {hap}_remapped.pretext, drop the AGP at
# {workdir}/recurate/{tol_id}.{hap}.recurate.agp

grit post-curation-recurate -t RC-1234           # recurate + remap, hap1
#   hap1:  fa, chr, hap  ->  pretext_to_asm_recurate

grit post-curation-recurate -t RC-1234 --hap2    # here --hap2 means INSTEAD of hap1
#   hap2:  fa, chr, hap  ->  pretext_to_asm_recurate_hap2

grit finalize-qc -t RC-1234
```

### Everything at once: contaminants, renaming, then recuration

The case where "freshest wins" is easiest to lose track of.

```bash
grit pretext-to-asm -t RC-1234
#   fa, chr, hap  ->  pretext_to_asm

grit blast-contaminants -t RC-1234
#   fa   ->  blast_contaminants
#   chr  ->  pretext_to_asm

grit rename-and-orient -t RC-1234
#   fa, chr  ->  rename_and_orient
#   hap      ->  pretext_to_asm

grit hic-remapping -t RC-1234
# curate the remapped map, drop the recurate AGP

grit pretext-to-asm-recurate -t RC-1234
#   fa, chr, hap  ->  pretext_to_asm_recurate     (freshest, so it takes all three)

grit hic-remapping -t RC-1234
grit finalize-qc -t RC-1234
```

Two things to watch in this one:
- If you re-run any pool step here — say `rename-and-orient` again after the
  recurate round — it becomes canonical again. That is usually what you want;
  when it isn't, [`grit untrack` (§7)](#7-undoing-a-step-with-untrack-and-retrack)
  demotes it without re-running anything.
