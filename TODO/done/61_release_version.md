# 61 — release version from Jira, per-version workdir

## Problem

A re-release (v2) of a species comes as a new Jira ticket with
`release_version: 2` set as a **Jira custom field**. grit ignores that field:

1. **Version is read from the wrong place.** `CurationContext.from_yaml` reads
   `int(yaml_data.get("release_version", 1))` (`grit/core/context.py:174`), but
   the key is not in the ticket YAML — `GritJiraIssue.get_release_version()`
   reads it from the custom field (`vgp_submission/modules/GritJiraIssue.py:1383`).
   So every real ticket runs as version 1. For a v2 ticket:
   - `finalize-qc` copies into `assembly/curated/<tol>.1/` under `.1` names,
     **overwriting the files v1 was released from**;
   - post-processing (`post_process_rc`, `vgp_submission/scripts/post_process_rc.snakefile`)
     takes the version from the same Jira field, so it looks for
     `<tol>[.<hap>].2.primary.curated.fa` etc. in `assembly/curated/<tol>.2/`,
     finds nothing and fails.
   Also affected: `haplotig_files`, `blast_contaminants` and recurate output
   names, and the `kmer_completeness.bash <tol> <version>` arg in `qv`.

2. **v1 and v2 share a workdir and step history.** `_derive_workdir` strips the
   version, so both tickets get `working/<user>_curation/<tol_id>/`. The registry
   finds step records by workdir (`append_step`/`get_steps`/`patch_step_job_id`
   in `grit/core/registry.py` take the first ticket with that workdir), so v2's
   steps are written under the v1 ticket, `grit status -t <v2>` shows v1's
   history, and canonical resolution (which globs the version as `*`) can hand
   v1's outputs to v2 for any step not re-run.

## Design

1. **Take the version from Jira.** In `CurationContext.from_ticket`, after
   fetching the issue, use `jira_issue.get_release_version()` and pass it into
   `from_yaml` (copy of `yaml_data` with `release_version` set — `from_yaml`
   already reads it from there, so `--yaml`/tests keep working unchanged).
   If the field is empty (`get_release_version()` raises), fall back to the
   YAML value / 1 with a `log.warning`.

2. **Per-version workdir from v2 on.** `_derive_workdir(..., tol_id,
   release_version)` returns `<user>_curation/<tol_id>` for v1 (unchanged — no
   in-flight curation moves) and `<user>_curation/<tol_id>.<v>` for v ≥ 2.
   A separate workdir is automatically a separate registry ticket entry and step
   history; the shared species dir is unchanged. The dry-run sandbox is keyed by
   ticket id already and needs no change.

3. **Version in pretext-to-asm output names.** `pretext-to-asm`
   (sanger-tol/agp-tpf-utils, `parse_output_file`) takes the version from the
   `-o` name: `-o <tol>.<v>.fa` → `<tol>[.<hap>].<v>.primary.curated.fa` etc.;
   without a numeric suffix it defaults to `1`. grit passed `-o {tol_id}.fa`, so
   every run produced `.1` files. `pretext_to_asm` and `pretext_to_asm_recurate`
   now pass `{ctx.tol_id_versioned}.fa`. `microchromosome_combine`'s
   `{tol_id}_small.fa` run is an intermediate that is merged and renamed, so it is
   left as is; `finalize_qc` names the published files from `release_version`
   anyway.

Out of scope: migrating a v2 ticket already set up under the shared workdir
(re-run `setup`, or `grit remove` and start again); trio/`paternal` naming.

## Tests

- `from_ticket` with a fake `gritjiraissue_module` whose `get_release_version()`
  returns `"2"` → `ctx.release_version == 2`, `assembly_curated_dir` ends in
  `<tol>.2`, workdir ends in `<tol>.2`.
- field missing → falls back to 1, warning logged.
- `_derive_workdir` v1 unchanged (existing tests), v2 gets the `.2` suffix.
- `run_pretext_to_asm` with `release_version = 2` passes `-o …/<tol>.2.fa`.

## Docs

CLAUDE.md "Workdir derivation" line: mention the `.<v>` suffix for v ≥ 2 and
that the version comes from the Jira field. CHANGELOG entry.
