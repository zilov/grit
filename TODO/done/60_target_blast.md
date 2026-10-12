# 60 — `target-blast`: blast chosen scaffolds, no canonical change

## Problem

`blast-contaminants` blasts every `SCAFFOLD_N` of the canonical FASTA and produces
a new decontaminated FASTA (canonical moves). Curators also want to check a handful
of specific sequences they suspect in PretextView — and get a verdict — without
producing a new assembly.

## Design

New optional step `grit/steps/optional/target_blast.py`, `target-blast -t RC-1234
--headers X`. Synchronous tracked step, same shape as `blast-contaminants`
(which already runs `decon_fasta` via `_run`, no bsub).

**Input.** One option `--headers`, either:
- a file path — one header per line (blank lines/`#` ignored):
  `--headers targets.txt`
- or a quoted comma-separated string, spaces around commas stripped:
  `--headers "HAP1_SCAFFOLD_12,HAP2_SCAFFOLD_7, HAP1_SCAFFOLD_40"`

An existing file wins; anything else is split on commas. Empty list →
`UsageError`.

**Source: `original.fa`, no haplotype flag.** Headers are looked up in
`ctx.workdir / "original.fa"` — the draft hap1(+hap2) concatenation `setup`
copies into the workdir — so both haplotypes are one file and the curator
never says which hap. `require_workdir(ctx)`; missing `original.fa` →
`UsageError` "run `grit setup` first".

1. `samtools faidx original.fa` (indexes once, `.fai` stays next to it), then
   read the `.fai` names. A requested header not in it → `log.warning` listing
   it, the run carries on with the rest. None found → warning and return
   before `tracker.start()` (nothing to blast, no empty run record). Under
   `print_only` the `.fai` can't be read, so every header is passed through.
2. `samtools faidx original.fa <found headers...>` → `run_dir/targets.fa`.
3. `decon_fasta --fasta targets.fa --outdir run_dir/blast_out_dir` (same command
   as blast-contaminants).
4. Python post-processing (skipped under `print_only`):
   - `<tol_id>.target_taxonomy.tsv` — `taxonomy.txt` as is (draft headers are
     already `SCAFFOLD_N`, which `decon_fasta` matches — no renaming).
   - `<tol_id>.target_blast.bed` — **every** found header:
     `name  0  length  KEEP|REMOVE|NO_HIT`. REMOVE when the top hit's lineage
     lacks the target phylum, KEEP when it has it, NO_HIT when decon_fasta
     wrote no line for it. Real length from the `.fai` (not blast-contaminants'
     fixed 10000). Names are draft headers, so the BED applies to the draft
     (`original.fa`), not to the curated FASTA.

**Canonical unchanged — for free.** Step name `target_blast` is not in the
canonical resolver pool (`find_canonical_*` in `grit/utils/helpers.py`), and
the step writes no FASTA. Tracked normally (so it's in `grit status` history),
`finish(..., outputs={"bed": ..., "taxonomy": ...})`.

**Reuse / small refactor.**
- Pull the lineage → target-phylum block out of `_blast_contaminants_for_hap`
  into `target_phylum(ctx) -> str` in `blast_contaminants.py` (it's also
  recomputed per hap today for no reason); `target_blast.py` imports it with
  `DECON_SCRIPT`.
- `require_workdir`, `_run`, `module_cmd("GRIT")`,
  `print_step_header` / `print_done`, `GritCommand`.
- Failure handling per the synchronous-step rule in CLAUDE.md: try/except around
  post-`start()` work → `finish(..., "failed", untracked=ctx.untracked)`; re-raise.
- Register `target_blast_cmd` in `grit/core/click_cli.py`.

**To check on the farm first:** `module load grit && which samtools`. If absent,
use whatever module has it (add a key to `MODULE_VERSIONS`).

**Skipped (add when needed):**
- `--dry-run` branch / tutorial lesson — not in `_DRY_RUN_SUPPORTED_COMMANDS`,
  so `GritCommand` refuses it cleanly. Add when a tutorial wants it.
- Applying the BED (making a new FASTA) — that's what `blast-contaminants` is for.
- bsub submission — blast-contaminants runs the same tool synchronously; move
  both together if it gets too slow.
- Blasting whole chromosomes: fine in principle, but huge SUPERs may be slow on
  the blast server; warn in `--help`, don't guard.

## Tests

One `tests/test_target_blast.py`, mocked `_run` like `test_blast_contaminants.py`:
- `--headers` parsing: file vs comma string.
- unknown header → warning, the others still blasted; all unknown → warning,
  no `tracker.start()`.
- BED verdicts from a fixture `taxonomy.txt` + `.fai`: KEEP / REMOVE / NO_HIT.
- canonical FASTA unchanged after a run (`find_canonical_fa` same before/after).
- missing `original.fa` → UsageError.

## Docs
- `docs/examples.md` §3 Optional steps, right after `blast-contaminants`:
  ```bash
  # Blast chosen draft scaffolds (headers as in original.fa, any haplotype),
  # canonical is not changed. Writes a taxonomy table + BED with KEEP/REMOVE/NO_HIT
  grit target-blast -t RC-1234 --headers "HAP1_SCAFFOLD_12,HAP2_SCAFFOLD_7"
  # or from a file, one header per line
  grit target-blast -t RC-1234 --headers targets.txt
  ```
- CLAUDE.md step list (`optional/`) + CHANGELOG line. Move this file to
`TODO/done/` when implemented.
