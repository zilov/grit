# Changelog

All notable changes to this project are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
