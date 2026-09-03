# grit — usage examples

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

# wait until the .agp file appears in the workdir — curate manually in PretextView

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
# unless you pass --reference/--local-path explicitly)
grit find-reference -t RC-1234
grit find-reference -t RC-1234 --local-path /path/to/reference.fa

# Determine sex from BUSCO (typically right after setup - runs on original.fa)
grit sex-matcher -t RC-1234

# FastGA synteny of curated fasta against a reference 
# (after find-reference AND pretext-to-asm, or with an explicit --reference)
grit fastga -t RC-1234
grit fastga -t RC-1234 --reference /path/to/reference.fa
grit fastga-stats -t RC-1234
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

# Split super-scaffolds into individual scaffolds in the AGP (after setup/curation)
grit super-to-scaffold -t RC-1234

# Second pass over microchromosomes if the first curation pass didn't split them
grit microchromosome-second-shot -t RC-1234 # before microchromosome curation
grit microchromosome-combine -t RC-1234 # after microchromosome curation
```

## 4. `grit status`

```bash
# All active tickets at a glance
grit status
```

Prints a table of every active ticket — ticket ID, ToL ID, species, last step
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

## Useful flags (work with any command)

```bash
# Dry run — print commands without executing them
grit setup -t RC-1234 --print-only

# Step status for a ticket
grit status -t RC-1234

# Summary across all tickets (active tickets + done-ticket counts by period)
grit status

# Increase bsub ram for some steps
grit [step] -t RC-1234 --bsub-ram NUM
```