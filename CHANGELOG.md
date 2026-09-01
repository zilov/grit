# Changelog

All notable changes to this project are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added

- `pretext-to-asm-recurate` step (with `--hap2`) for a second curation round on an already-remapped pretext map, plus the `post-curation-recurate` composite that chains it with the rest of post-curation.
- `retrack` command to promote an `--untracked` run back to canonical using the outputs its own run recorded.
- `--dry-run` mode: every supported step writes placeholder outputs into an isolated `~/.grit/dry_run/` sandbox instead of running real commands, so step sequencing, tracking and canonical resolution can be exercised end to end without farm/NFS access. `--print-only` takes precedence when both are given.
- `--untracked` flag on every step via the `GritCommand` base class, for running a step without it counting as canonical registry state.
- `rename-and-orient` gained `--mapping-table`, `--min-coverage` and `--plot-alignments`.
- `fastga-stats` as its own synchronous tracked step, decoupled from the `fastga` bsub job, skipping re-computation when results already exist.
- `grit status -t` shows a "Canonical" column marking which run currently owns each output type (`fa`/`hap`/`chr`), a ticket age column, and per-month counts for done tickets; the global status absorbed the old summary.
- `recuration-canonical-priority.md`: curator-facing decision path and flowchart for canonical resolution.

### Changed

- Canonical file resolution (`find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs`) replaced its fixed step-priority tiers with a single flat pool compared by file mtime — whichever qualifying step ran most recently wins. This unblocks chaining `blast-contaminants`/`rename-and-orient` after a recurate round without running `grit untrack` first.
- `fastga-stats` picks its best PAF target by summed non-overlapping alignment coverage instead of the single longest alignment (new `paf_top_targets_by_coverage.py`, replacing `paf_top_targets_add_top_longest.py`); the top-targets table gained a fourth column.
- `blast-contaminants` uses `decon_fasta` instead of `decon_blastBTK`, groups its outputs per haplotype and fails loudly instead of silently producing nothing.
- `rename-and-orient` is resolved as an external dependency at submission time (constraint `>=1.2.2`) rather than assuming a path.

### Fixed

- An `--untracked` run no longer becomes canonical the moment it finishes: `RunTracker.finish()` keeps writing `status="untracked"` instead of overwriting it with `success`/`failed`.
- A run whose registry `outputs` were recorded incompletely no longer hands the canonical slot back to an older step — the step's latest run dir is re-globbed with its own `_OUTPUT_SPECS` first, so canonical can never move backwards in time.
- `pretext-to-asm` records its haplotig FASTA and chromosome list for primary (single-haplotype) assemblies, not just hap-prefixed ones.
- `rename-and-orient` tracks its chromosome-list output, not just the FASTA, and writes into its own run dir rather than a shared output dir.
- `fastga` captures every file matched by a multi-match output spec instead of only the last one.
- `fastga-stats` marks its tracker record failed on a script error or missing output instead of leaving it stuck as "started", and fails with a clear message on a stale 3-column top-targets file.
- `grit status` no longer inflates run counts: all records of one run collapse into a single history row, superseded "started" rows are dropped, and cleaned-up tickets count towards the done total again.
- The `--dry-run` sandbox is keyed by ticket ID rather than ToL ID, and single-haplotype tickets no longer leave stray hap2/alternate placeholder files behind.

## [0.3.5] - 2026-08-19

### Fixed

- `sex-matcher` accepts nematode ToL IDs (`n` prefix).

## [0.3.4] - 2026-08-14

### Fixed

- Bundled script paths (`fastga`, `sex-matcher`, `busco-synteny`) resolve correctly when grit is installed as a package rather than run from a clone.

### Changed

- README installs grit as a `uv` tool straight from git, with no local clone needed.

## [0.3.3] - 2026-08-14

### Added

- `examples.md` with end-to-end usage examples: installation, the standard curation workflow, optional steps, and `grit status` / `grit status -t` output.

## [0.3.2] - 2026-08-14

### Added

- Optional `email` field in `grit_curation_config.yaml`. When set, `hic-remapping` passes it to `curationpretext.sh` via `--email`.

### Fixed

- README/CLAUDE.md CLI usage examples now match the actual `-t/--ticket` syntax (`grit setup -t RC-1234`, not `grit RC-1234 setup`).

## [0.3.1] - 2026-08-14

### Changed

- `hic-remapping` passes `--split_telomere true` to `curationpretext.sh`.

## [0.3.0] - 2026-08-14

### Added

- `grit remove` command to permanently delete a ticket.
- `super-to-scaffold` step to report the largest scaffold per super.
- Nextflow `.nextflow*`/`work` scratch cleanup, with the plan documented in `--help`.
- `cleanup` skips tickets already marked done via a `cleaned_up` flag.

### Fixed

- `finalize-qc` and `haplotig-files` now derive haplotig naming and assembly type from what's actually on disk (pretext-to-asm's real output) instead of trusting the YAML, and fail hard on a YAML/disk assembly-type mismatch instead of warning.
- `post-processing` no longer strips the `tola_production` venv from `PATH` or runs `module purge` before sourcing `contamination_screen.conf`, both of which broke downstream tooling.
- `sex-matcher` resolves a stale `started` status instead of blocking forever.
- `setup` accepts `HAP<N>_SCAFFOLD_N` headers (not just `HAPM_`), validates scaffold headers, and tracks `original.fa` freshness.
- `hic-remapping` makes `--hap2` exclusive of `--hap1`.
- `status` resolves `hic_remapping` DONE jobs immediately instead of waiting for `bjobs` to forget them.
- `super-to-scaffold` no longer counts internal gaps as separate pieces, excludes unplaced scaffolds from the report, and correctly finds the combined-window AGP to sum split scaffold pieces.
- Rich markup is escaped in printed `bsub` commands.

### Changed

- README recommends `uv tool install` for a global `grit` command.
- README documents how to update: `git pull && uv tool upgrade grit --reinstall`.
