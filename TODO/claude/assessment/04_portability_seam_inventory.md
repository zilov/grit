# 04 — Portability / Coupling Seam Inventory (Phase 1: the MAP)

Read-only inventory of every place Sanger Tree of Life infrastructure is baked into `grit`
(branch `test_and_fix_steps`, 9,671 LOC across `grit/`). No design, no migration plan — that is Phase 2.

Scope: `grit/**` (source), `pyproject.toml`, `.github/workflows/ci.yml`, `grit/scripts/**`.
`tests/`, `TODO/`, `.venv/`, caches excluded except where explicitly noted.

---

## Summary

**Verified grep counts** (the brief's numbers were over-counted because they included `tests/`):

| Pattern | Brief said | Actual in `grit/` | Actual in `tests/` |
|---|---|---|---|
| `bsub` | 146 | **117 lines** (21 files) | 218 |
| `module load` / `module purge` | 13 | **15 lines**, of which **2 are live code** (`modules.py:83`, `FastGA_dot_dgenies_stats.sh:36`), rest are docstrings/comments | 1 |
| `/nfs` | ~44 | **19 lines** (9 distinct absolute paths) | 29 |
| `/lustre` | 4 | **10 lines** (5 distinct paths + 4 `-B /lustre` binds) | 98 (fixture YAML paths) |
| `LSB_` | 2 | **2** (`helpers.py:104`, `modules.py` docstring 0) — actually 1 live use | 1 |
| `Jira`/`jira` | ~12 | **22 lines**, of which **7 are live code** (all in `context.py`) | 12 |
| `bjobs` | — | **24 lines** (4 files) | 37 |
| `/software` | — | **14 lines** (5 distinct paths) | 0 |

**Seam counts per port** (rows in the tables below):

| Port | Seam rows | Grouped mechanical repeats |
|---|---|---|
| 1 ExecutionBackend | 24 | 7 × `_submit_bsub` call sites, 7 × `build_bsub_opts` call sites |
| 2 ToolProvider | 27 | 12 × `module_cmd()` call sites |
| 3 MetadataSource | 16 | — |
| 4 StorageLayout | 34 | 5 × duplicated `_PTA_ALIASES` dicts, 3 × duplicated haplotig-keyword tuples |
| 5 ReleaseTarget | 11 | — |
| Unclassified environment | 13 | — |
| **Total** | **125** | |

**Headline conclusions**

1. The *scheduler* seam (Port 1) is almost entirely **syntactic** and is already funnelled through
   three functions in one file (`_submit_bsub`, `build_bsub_opts`, `_check_bjobs`). It is the
   easiest of the five ports.
2. The *tool* seam (Port 2) is where the real blockers are, and `modules.py` covers only a *fraction*
   of it. Five module keys map to just two real modules (`grit`, `pretextgraph/…`); meanwhile **at
   least 14 distinct external binaries/scripts** are invoked with hardcoded absolute Sanger paths
   that `modules.py` never sees, several of them in personal home directories (`~mh6/…`,
   `/nfs/users/nfs_d/dz11/…`, `/nfs/users/nfs_d/da16/…`). The pixi draft's "open question" about
   `curationpretext` understates this by roughly an order of magnitude.
3. `from_yaml` (Port 3) is genuinely close to a complete Jira-free path — closer than the brief
   assumed. See the assessment in Port 3; the gaps are small and enumerable.
4. Naming conventions (Port 4) are the largest single category by row count and are the seam most
   likely to be discovered late: ToL ID prefix semantics (`b…` = bird, `ic/il/id/n…` = insect/nematode),
   `SUPER_`/`SCAFFOLD_` scaffold naming, and the `hap1/hap2` ↔ `primary/alternate` alias table
   (duplicated 5×) are load-bearing in control flow, not just in strings.
5. Nothing in this repo is itself proprietary and **no credentials were found**. The proprietary
   surface is entirely *outside* the repo: `GritJiraIssue` (injected via `sys.path`) and the
   `/software/grit/…` + `~mh6/…` script trees.

---

## Port 1 ExecutionBackend

**Semantic vs syntactic** — the distinction the port design turns on:

*Semantic* (any scheduler has these concepts): submit-and-return-a-handle; poll a handle for
state; a terminal exit status; a run-on-completion callback; a resource request (memory, cores,
wall-time); an accounting group; a synchronous/blocking submit; a per-job stdout/stderr log file.

*Syntactic* (LSF-only spelling): the literal `bsub`; flag letters `-q -n -G -K -o -e -M -Ep`; the
`-R'select[mem>N] rusage[mem=N] span[hosts=1]'` resource string; the `Job <12345> is submitted…`
stdout format; `bjobs -noheader` and its column layout; the state vocabulary
`PEND/RUN/DONE/EXIT/ZOMBI/UNKWN`; `$LSB_JOBEXIT_STAT`; `TERM_MEMLIMIT` and friends; queue name
`normal`; group name `team135`.

Notably **absent**: any job-dependency syntax. There is no `-w`, no `done(jobid)`, no job arrays,
no `bkill`. Sequencing between steps is done by the curator re-invoking `grit`, or by composite
Python functions (`run_post_curation`) calling step functions in order. That is a real
simplification for the port.

| file:line | assumption | semantic / syntactic | effort |
|---|---|---|---|
| `grit/utils/helpers.py:62-86` | `_submit_bsub()` — the single submit choke point; builds `bsub{-Ep} {opts} "{inner}"` | mixed: submit = semantic, spelling = syntactic | S |
| `grit/utils/helpers.py:78` | `-Ep '<cmd>'` is how a completion callback is registered | semantic concept, syntactic flag | M |
| `grit/utils/helpers.py:79` | inner command is wrapped in exactly one `"…"` pair; quoting rules are LSF-shell-specific | syntactic | M |
| `grit/utils/helpers.py:82-85` | job ID is parsed out of stdout by splitting on `Job <` / `>` | syntactic | S |
| `grit/utils/helpers.py:89-105` | `_state_update_epilogue()` — epilogue shells out to `grit _state-update` | semantic | M |
| `grit/utils/helpers.py:100` | `sys.argv[0]` (submit-host path to the `grit` binary) is valid on the *compute* node | environment (shared FS) — see Unclassified | M |
| `grit/utils/helpers.py:104` | `$LSB_JOBEXIT_STAT` carries the exit status into the epilogue env | syntactic | S |
| `grit/utils/helpers.py:108-134` | `_check_bjobs()` — `bjobs -noheader <ids>`; parses positional columns `jid user status` | syntactic | S |
| `grit/utils/helpers.py:117,133` | absence from `bjobs` output means `"gone"` (job aged out of history) | semantic (poll may lose history) | S |
| `grit/utils/helpers.py:137-191` | `build_bsub_opts()` — the entire LSF flag vocabulary in one builder | mixed | S |
| `grit/utils/helpers.py:139` | default queue is the literal `"normal"` | syntactic + site config | S |
| `grit/utils/helpers.py:190` | `-R'select[mem>M] rusage[mem=M] span[hosts=1]'` resource-string grammar | syntactic | S |
| `grit/utils/helpers.py:161,185` | `-K` blocking submit (`wait=True`) — declared but **no caller uses it today** | semantic | S |
| `grit/steps/pre_curation/sex_matcher.py:148`, `grit/steps/optional/fastga.py:138`, `grit/steps/optional/rename_and_orient.py:98` | hardcoded LSF accounting group `team135` (3 sites) | site config | S |
| **7 × `_submit_bsub()` call sites** — `sex_matcher.py:158`, `busco_curated.py:153`, `busco_synteny.py:119`, `fastga.py:152`, `fastga_synteny.py:108`, `rename_and_orient.py:114`, `cleanup.py:288` | *grouped mechanical repeat*: identical `submit + record_job + epilogue` boilerplate | semantic | S per site |
| **7 × `build_bsub_opts()` call sites** — same files, at `:145 / :139 / :108 / :137 / :97 / :97 / :280` | *grouped mechanical repeat*: per-step memory/core defaults | semantic | S per site |
| `grit/core/registry.py:242-279` | `_refresh_pending_jobs()` — bulk `bjobs` sweep over every active ticket on every `grit status` | semantic | M |
| `grit/core/registry.py:276-279` | `EXIT` → failed, `gone` → resolve-by-output-presence | semantic, syntactic vocabulary | S |
| `grit/core/registry.py:281-297` | `_resolve_gone_job()` — output-file presence substitutes for a lost exit status | semantic | M |
| `grit/core/run_tracker.py:154-162, 231-250` | a run has at most one scheduler `job_id`; `pending_jobs()` = `status=="started" and job_id` | semantic | S |
| `grit/core/click_cli.py:210-255` | hidden `_state-update` CLI is the epilogue contract (`--workdir --step --run-dir --status --job-id --untracked`) | semantic | M |
| `grit/core/click_cli.py:221` | `--job-id` help text: "LSF job ID" | cosmetic/syntactic | S |
| `grit/core/status.py:457-463, 523-550` | live `bjobs` enrichment of the history table; `DONE`/`gone`/`EXIT`/`RUN`/`PEND` branch | syntactic vocabulary | M |
| `grit/utils/result_parsers.py:120-129` | `parse_lsf_exit_reason()` — regex for `TERM_\w+:` in the job log | syntactic | S |
| `grit/utils/result_parsers.py:132-144` | `find_lsf_log()` — LSF log naming convention `e_* / *.err / o_* / *.out / *.log` | syntactic | S |
| `grit/core/status.py:556-562, 597-601` | `TERM_MEMLIMIT` → suggest `--bsub-ram` (LSF-specific failure mode surfaced in UX) | syntactic | S |
| `grit/core/context.py:90-91`, `grit/core/base_command.py:65-75` | `bsub_ram` context field and `--bsub-ram` flag named after LSF, help text "LSF memory limit in MB" | naming only | S |
| `grit/steps/post_curation/hic_remapping.py:120-123` | `re.search(r"Job <(\d+)>")` scraped from `curationpretext.sh` stdout — grit did *not* submit this job, so no `-Ep` is possible | semantic (external submitter) | L |
| `grit/steps/pre_curation/microchromosome_second_shot.py:64-67, 133` | step runs synchronously because the external script blocks on its own internal `bsub -K` jobs | semantic (nested scheduler use) | L |
| `grit/steps/pre_curation/sex_matcher.py:99-129` | resubmit guard queries `_check_bjobs` for `PEND`/`RUN` before re-submitting | semantic | S |
| `grit/steps/optional/fastga_synteny.py:94`, `grit/scripts/busco-synteny.sh:101` | `uv run --script` must be available on compute nodes inside the bsub payload | environment | M |

**Port 1 verdict:** 24 seam rows, all but three of them S/M. The two hard ones
(`hic_remapping.py`, `microchromosome_second_shot.py`) are hard *not* because of LSF but because an
external tool owns the scheduling — any backend abstraction inherits the same blind spot, and
CLAUDE.md already documents this ("if a step instead shells out to an external script that submits
its own async work internally, grit never sees a job it can attach an epilogue to").

---

## Port 2 ToolProvider

### 2a. The `modules.py` mechanism itself

| file:line | assumption | semantic / syntactic | effort |
|---|---|---|---|
| `grit/utils/modules.py:24-32` | `MODULE_VERSIONS` — 5 logical keys collapsing to 2 real modules (`grit` ×4, `pretextgraph/0.0.7--h4ac6f70_0` ×1) | site config | S |
| `grit/utils/modules.py:44` | `_MODULES_INIT = "/etc/profile.d/modules.sh"` — Environment Modules/Lmod installed at that path | syntactic + environment | S |
| `grit/utils/modules.py:83` | `module_cmd()` returns a *shell fragment* `". … && module purge && module load X"` that callers string-concatenate with `&&` | syntactic; the string-fragment shape is the real coupling | M |
| **12 × `module_cmd()` call sites** — `hic_remapping.py:101`, `qv.py:87`, `pretext_to_asm.py:126`, `fastga.py:134,219`, `busco_synteny.py:105`, `find_reference.py:57,91`, `sex_matcher.py:152`, `add_pretext_view_tracks.py:60,91,137` | *grouped mechanical repeat*: `f"{module_cmd('X')} && <cmd>"` | syntactic | S per site |
| `grit/scripts/FastGA_dot_dgenies_stats.sh:36` | **`module load fastga/1.1-c1` bypasses `modules.py` entirely** — a 6th tool version pinned outside the "one place to update versions" registry | syntactic | S |
| `grit/scripts/sex-matcher.sh:3`, `grit/scripts/busco-synteny.sh:9` | `source /nfs/users/nfs_m/mh6/sing.bash` — a *personal home directory* provides the singularity environment | environment | M |
| `grit/steps/optional/busco_curated.py:128`, `sex-matcher.sh:20,24,28,34`, `busco-synteny.sh:82` | `singularity exec -B /lustre <sif>` — Singularity present, `/lustre` bind-mountable | environment | M |
| `grit/steps/post_curation/hic_remapping.py:102` | `curationpretext.sh -profile sanger,singularity` — Nextflow `sanger` institutional profile | site config | M |
| `grit/steps/optional/rename_and_orient.py:69-77` | `shutil.which("rename-and-orient")` resolved on the *submit* host, relying on `$HOME` being NFS-shared with compute | environment | M |

### 2b. Tools invoked *outside* `modules.py`

These are the ones the pixi draft misses. Every one is a hardcoded absolute path or a bare binary
name assumed to be on `$PATH`.

| file:line | tool / path |
|---|---|
| `grit/steps/pre_curation/find_reference.py:25` | `/software/grit/projects/vgp_curation_scripts/get_nearest_comparator.rb` |
| `grit/steps/optional/blast_contaminants.py:32` | `/software/grit/projects/vgp_curation_scripts/get_lineage_from_species.rb` |
| `grit/steps/optional/blast_contaminants.py:35` | `~mh6/git_checkouts/reblast/bin/decon_fasta` |
| `grit/steps/optional/blast_contaminants.py:192` | `~mh6/remove_contamination_bed` |
| `grit/steps/post_curation/post_processing.py:17,51,53` | `source /software/grit/projects/contamination_screen/conf/contamination_screen.conf` then the shell alias `post_process_rc` |
| `grit/steps/pre_curation/microchromosome_second_shot.py:28-31` | `/nfs/users/nfs_d/dz11/gitlab/vgp_curation_scripts/birds_microchromosomes/microchr_second_shot_curation.py` (marked TEMP; canonical location `/software/grit/projects/vgp_curation_scripts/…`) |
| `grit/steps/post_curation/microchromosome_combine.py:26-29` | `…/birds_microchromosomes/combine_curated_micros.py` (same TEMP note) |
| `grit/steps/pre_curation/add_pretext_view_tracks.py:24` | `/nfs/users/nfs_d/dz11/hap_bedgraph.py` |
| `grit/scripts/sex-matcher.sh:46` | `/software/grit/projects/vgp_curation_scripts/sex_matcher.py` |
| `grit/scripts/FastGA_dot_dgenies_stats.sh:28,30` | `/software/grit/projects/vgp_curation_scripts/dgenies_index.py` |
| `grit/scripts/FastGA_dot_dgenies_stats.sh:57,74` | `/software/grit/projects/vgp_curation_scripts/ragtag_paf2delta.py` |
| `grit/steps/post_curation/qv.py:88` | `kmer_completeness.bash` (bare name, provided by module `grit`) |
| `grit/steps/pre_curation/find_reference.py:50,54,86,90` | `reheader` (bare name, provided by module `grit`) |
| `grit/steps/post_curation/pretext_to_asm.py:126` | `pretext-to-asm` (bare name, provided by module `grit`) |
| `grit/scripts/FastGA_dot_dgenies_stats.sh:61,78` | `DotPrep.py` (bare name, on `$PATH` via module `fastga`?) |

Plus generic Unix/utility commands routed through `_run` with no provisioning at all:
`zcat` (`setup.py:166`), `gunzip` (`find_reference.py:50,85`), `pigz -p 8` (`cleanup.py:279`),
`du -sb --apparent-size` (`cleanup.py:43` — GNU-only flags), `cp`/`mv`/`mkdir`/`touch`/`rm`,
`grep -v` + `perl -anE` (`blast_contaminants.py:177-179`), `awk`/`zcat`
(`add_pretext_view_tracks.py:142-144`), `python3` (`fastga.py:220`, `add_pretext_view_tracks.py:95`),
`bash` (`post_processing.py:63`), `uv run --script`.

See **External tool table** below for bioconda status.

**Port 2 verdict:** 27 seam rows. `modules.py` is a genuine but *shallow* abstraction — it governs 2
of the ~20 externally-provided tools. The remaining ~18 have no indirection layer at all.

---

## Port 3 MetadataSource

| file:line | assumption | semantic / syntactic | effort |
|---|---|---|---|
| `grit/core/context.py:237-239` | `sys.path.insert(0, expanduser(cfg.gritjiraissue_path)); import GritJiraIssue` — a **shared server library injected by path, not a dependency** | environment + distribution | L |
| `grit/core/context.py:241-242` | `GritJiraIssue(ticket_id).yaml` returns the whole ticket YAML dict | semantic | M |
| `grit/core/context.py:243` | `issue_json["fields"]["customfield_11650"]` — a raw **Jira custom-field ID** for teloseq | syntactic (Jira schema) | S |
| `grit/core/context.py:245-247` | `jira_issue.get_custom_field("yaml")` → filesystem path of the ticket YAML | semantic | S |
| `grit/core/context.py:28,38`, `grit/config/sanger_template.yaml:17-23` | `gritjiraissue_path` is a required user-config key; default points at a **personal gitlab checkout** (`/nfs/users/nfs_d/dz11/gitlab/vgp_submission/modules/`) with a TEMP comment saying the shared `/software/grit/…` copy is mid-refactor | site config | S |
| `pyproject.toml:12` | `pymysql>=1.0` is a declared dependency but **is imported nowhere in this repo** — strong evidence `GritJiraIssue` (or something it pulls in) talks to a MySQL/ToL database | distribution | M |
| `grit/core/context.py:264-277` | `_detect_assembly_type()` — YAML must contain a top-level `hap1` **or** `primary` key; anything else raises | semantic + ToL schema | M |
| `grit/core/context.py:136-157` | required YAML keys: `specimen`, `hic_read_dir`, one of `pacbio_read_dir`/`ont_read_dir`; optional `species`, `pacbio_read_type`, `combine_for_curation`, `release_version` | ToL YAML schema | M |
| `grit/core/context.py:154` | `assembly_draft_dir = Path(yaml_data[<hap1 key>]).parent` — the assembly path *is* the layout anchor | ToL layout | M |
| `grit/core/base_command.py:107-111, 145-152` | ticket ID is a free-form string; when `--yaml` is given it is derived from the file **stem** | semantic | S |
| `grit/utils/helpers.py:930-932` | `_pick_highest_version()` prefers a pretext map filename containing the literal `"RC"` — the `RC-1234` ticket prefix leaks into file selection | syntactic (ToL naming) | S |
| `grit/steps/pre_curation/setup.py:187-197` | pretext maps on NFS are filtered by "filename contains the ticket ID" | ToL naming | S |
| `grit/core/registry.py:34-35, 47-48` | ticket registry at `~/.grit/grit_registry.json`; single flat JSON, no locking; `_save` is `write tmp + os.replace` | environment | M |
| `grit/core/registry.py:38-40` | `dry_run_root()` = `~/.grit/dry_run` | environment | S |
| `grit/core/click_cli.py:47` | user config default `~/.grit/grit_curation_config.yaml` | environment | S |
| `grit/core/status.py:424-437` | `show_ticket_history` builds a `CurationContext` via `from_ticket` — so **plain `grit status -t <ticket>` hits Jira** unless `--yaml` is passed | semantic | M |

### How complete is `from_yaml` today?

**Close, but not complete.** `from_yaml` (`context.py:108-211`) is the canonical constructor —
`from_ticket` is a thin Jira-fetch wrapper that delegates to it (`context.py:250-260`), and
`--yaml FILE` at the group level short-circuits the Jira call for *every* step
(`click_cli.py:102-125` → `from_ticket(yaml_override=…)`). `tests/conftest.py`'s `mock_ctx` and
`tests/local_smoke_test.sh` already exercise the whole step chain this way.

What is genuinely missing for a "no Jira at all" run:

1. **`teloseq` is unreachable from YAML.** It comes only from Jira `customfield_11650`
   (`context.py:243`) and is hardcoded to `""` on the `yaml_override` path (`context.py:236`).
   It feeds `curationpretext --teloseq` (`hic_remapping.py:112-113`). A YAML-only user silently
   loses telomere splitting.
2. **`yaml_path` is unreachable from YAML.** Also Jira-only (`context.py:245-247`); used purely for
   a better error message in `finalize_qc.py:63`. Cosmetic.
3. **`UserConfig` still *requires* `gritjiraissue_path`** (`context.py:28,38` — a `d["…"]` lookup,
   not `.get()`), so a YAML-only user must still put a dummy value in the config file
   (which is exactly what `tests/fixtures/test_config.yaml:7` does: `/tmp/dummy_gritjiraissue`).
4. **`grit status -t` requires Jira** unless `--yaml` is threaded through (`status.py:431-437`);
   `--yaml` is only wired at group level, so `grit --yaml f.yaml status -t X` works but
   `grit status -t X` does not.
5. **Ticket ID from filename stem** means the registry key is the YAML filename — workable but
   couples ticket identity to a path.
6. `done` / `reopen` / `remove` / `cleanup` never build a context at all, so they are already
   Jira-free.

None of these is architecturally hard. The `sys.path`-injection of `GritJiraIssue` is the *real*
Port 3 problem, and it is a distribution problem as much as a coupling one — see **Findings PORT3-01**.

---

## Port 4 StorageLayout

### 4a. Path derivation

| file:line | assumption | semantic / syntactic | effort |
|---|---|---|---|
| `grit/core/context.py:280-297` | `_derive_workdir()` — string-replace `assembly/draft` → `working`, then `/<username>_curation/<tol_id_base>`; **raises** if `assembly/draft` is absent | ToL layout, hard-coded | M |
| `grit/core/context.py:295` | version suffix stripped from tol_id by splitting on `.` (`sDipInt39.1` → `sDipInt39`) | ToL naming | S |
| `grit/core/context.py:159-162` | `assembly_curated_dir` = string-replace `assembly/draft` → `assembly/curated` + `/{tol_id}.{release_version}` | ToL layout | M |
| `grit/core/context.py:148` | ONT dir derived by `ont_dir_raw.replace("fasta", "")` — a substring hack on the YAML path | ToL layout | S |
| `grit/steps/post_curation/hic_remapping.py:107`, `microchromosome_second_shot.py:129` | long reads live at `{long_reads_dir}/fasta` | ToL layout | S |
| `grit/core/status.py:610-612` | curated dir re-derived as `workdir.parent.parent.parent / "assembly" / "curated"` — a hardcoded **3-level** ascent | ToL layout | M |
| `grit/steps/post_curation/finalize_qc.py:31-39, 154` | curated pretext maps land in a two-level prefix tree `{nfs}/{tol_id[0]}_*/{tol_id[1]}_*/` — indexing into the *characters* of the ToL ID | ToL naming | M |
| `grit/config/sanger_template.yaml:5,8` | `/nfs/treeoflife-01/teams/grit/data/{pretext_maps,curated_pretext_maps}/` | site config | S |
| `grit/core/registry.py:14` | docstring example workdir `/lustre/.../working/dz11_curation/xbLimHian1` | cosmetic | S |
| `grit/utils/helpers.py:224`, `status.py:624,657`, `setup.py:279-282`, `microchromosome_second_shot.py:155` | curator's **local** machine has `~/curations/work/{tol_id}/` | convention | S |
| `grit/steps/post_curation/hic_remapping.py:131` | uses `~/curations/{tol_id}/` — **inconsistent** with the `~/curations/work/…` used everywhere else | convention (latent bug) | S |
| `grit/core/run_tracker.py:4-16, 87-89` | run layout `{workdir}/<step>/<ISO-timestamp>[_suffix]/` and `.grit/<step>/<ts>.log`; **timestamp dirs sort alphabetically = chronologically** (relied on by `find_latest_dir`, `cleanup._latest_run_dir`) | grit-internal | S |
| `grit/utils/helpers.py:678-718` | `find_latest_dir()` — filesystem-alphabetical vs tracker comparison, plus `<step>/untracked/` legacy dir and bare-`workdir` last resort | grit-internal | M |
| `grit/steps/pre_curation/find_reference.py` / `manifests.py:25-28` | `find_reference` outputs expected under `workdir/reference/*.fa` (manifest) although the step actually writes to a tracked run dir — latent mismatch | grit-internal | S |

### 4b. ToL naming conventions baked into control flow

These are the seams the brief warns about — they are *decisions*, not strings.

| file:line | assumption | effort |
|---|---|---|
| `grit/steps/pre_curation/setup.py:23, 85-99` | `_SCAFFOLD_HEADER_RE = ^>(HAP\d+_)?SCAFFOLD_\d+` — setup **raises** if the input FASTA's first header doesn't match | M |
| `grit/steps/pre_curation/setup.py:40-45, 62-69` | draft inputs named `{tol_id}*{hap_prefix}.decontaminated.fa*`, with a `*haplotigs.decontaminated.fa*` fallback | M |
| `grit/core/context.py:58-61, 264-277` | haplotype prefixes are exactly `hap1/hap2`, `primary/alternate` (`paternal/maternal` handled in aliases but **not** producible by `_detect_assembly_type`) | M |
| `grit/utils/helpers.py:317-322, 442-447, 501-506, 586-591, 655` | **`_PTA_ALIASES` is duplicated 5×** (`primary→hap1`, `paternal→hap1`, `alternate→hap2`, `maternal→hap2`); the 5th copy (`find_hap_agp`) is a *different, smaller* dict — divergence risk | M |
| `grit/utils/helpers.py:286, 316, 441`, `finalize_qc.py:59` | **haplotig-filename keyword tuple duplicated 4×** (`all_haplotigs`, `additional_haplotigs`, `haplotigs`) | S |
| `grit/utils/helpers.py:20-22`, `status.py:161-167` | `is_single_hap` / `_canonical_haps` — "primary or paternal means no real second haplotype" | M |
| `grit/utils/helpers.py:477-560` | five distinct haplotig filename shapes enumerated in a docstring and matched by glob priority | M |
| `grit/steps/post_curation/pretext_to_asm.py:26-42` | `_OUTPUT_SPECS` encodes `{tol_id}.{hap}.{v}.curated.fa`, `.all_haplotigs.curated.fa`, `.chromosome.list.csv`, plus an unprefixed `.primary.` fallback | M |
| `grit/steps/post_curation/finalize_qc.py:168-171` | release naming: single-hap `{tol_id}.{v}.{suffix}`, dual-hap `{tol_id}.{hap}.{v}.{suffix}` | M |
| `grit/steps/post_curation/haplotig_files.py:67-75` | fabricates `{tol_id}[.hap1|.hap2].{v}.all_haplotigs.curated.fa` when absent | S |
| `grit/steps/optional/rename_and_orient.py:60, 207` | renamed prefix `{tol_id}.{hap}.primary.renamed`, mapping table `{prefix}.mapping.tsv` | S |
| `grit/steps/optional/super_to_scaffold.py:81, 98-101`, `fastga.py:54-56` | scaffolds named `SUPER_<n>`; `_is_super()` gates which rows are reported | M |
| `grit/utils/result_parsers.py:58` | chromosome-list rows containing `unloc` (in either column) are excluded | M |
| `grit/utils/result_parsers.py:60, 69-89` | sex chromosomes identified by regex `[XYZW]` in the chromosome-ID column; `Z/X` sort before `W/Y`; a lone sex chrom becomes `…O` | M |
| `grit/utils/result_parsers.py:42-66` | chromosome list is a **headerless 2+-column CSV** `scaffold,chrom_id` | M |
| `grit/utils/result_parsers.py:94-97` | pretext-to-asm log line grammar: `Curation made N cuts in … contigs, N breaks at … gaps and N joins` | M |
| `grit/core/status.py:667-676` | **`tol_id.startswith("b")` ⇒ bird genome** ⇒ suggest microchromosome second-shot | M |
| `grit/steps/pre_curation/sex_matcher.py:33, 87-95` | `_INSECT_PREFIXES = ("ic","il","id","n")`; sex-matcher **aborts with exit 1** for any other tol_id | M |
| `grit/steps/pre_curation/setup.py:334, 394-398` | `_INSECT_PREFIXES = ("ic","il","id")` — a **second, divergent copy** of the same table | S |
| `grit/scripts/sex-matcher.sh:9-35` | tol_id char 1 = `i`/`n`, char 2 = `c`/`l`/`d` selects the BUSCO lineage *and* the sex-BUSCO ID list | M |
| `grit/steps/pre_curation/setup.py:194-200`, `helpers.py:755`, `manifests.py:47,51` | pretext map filename suffixes `*hr.pretext` / `*normal.pretext` / `*ultra.pretext` and their roles | S |
| `grit/utils/helpers.py:918-937` | `_pick_highest_version()` — version is the second-to-last `_`-separated token of the filename stem | M |
| `grit/steps/post_curation/hic_remapping.py:21-27`, `finalize_qc.py:109` | curationpretext writes into `pretext_maps_processed/` | S |
| `grit/core/status.py:585, 631-638`, `registry.py:225` | curated AGP arrives as `{tol_id}*.pretext.agp_1` in the workdir | M |
| `grit/steps/post_curation/pretext_to_asm_recurate.py:141-148` | recuration AGP goes in `{workdir}/recurate/`, matched by `{tol_id}*{hap_prefix}*.agp*` | S |
| `grit/steps/post_curation/qv.py:29`, `validate_files.py:76`, `result_parsers.py:243`, `finalize_qc.py:196,307` | QV outputs live in `<curated_dir>/merquryk/` as `{tol_id}.qv` + `{tol_id}.completeness.stats` (**4 duplicated derivations**) | M |
| `grit/core/cleanup.py:76-78` | FastK per-thread index files identified by `.ktab.` / `.post.` in the name | S |
| `grit/core/cleanup.py:132`, `helpers.py:737` | reheadered reference is `*_reheader.fna` | S |
| `grit/core/cleanup.py:145-176` | Nextflow scratch = `work/` (with 2-char hash subdirs), `.nextflow/`, `.nextflow.log*` | S |
| `grit/steps/post_curation/microchromosome_combine.py:31-54` | micro workflow always uses literal `hap1`/`hap2` tokens regardless of YAML key; `{tol_id}_small.*` prefix; `*.hapN.large.fa` / `*.hapN.large.chr_list.csv` / `*_curated_small_merged.fa` | M |
| `grit/steps/pre_curation/add_pretext_view_tracks.py:122-124` | TreeVAL telomere BED at `{draft}/treeval/*/tv_output1/treeval_upload/telo_*.bed.gz` | M |
| `grit/steps/optional/fastga.py:119-121` | run prefix `{ref_prefix}_vs_{assembly_prefix}` derived from filename stems split on `.` | S |
| `grit/core/context.py:100-103` | `tol_id_versioned` = `{tol_id}.{release_version}` | S |

**Port 4 verdict:** 34 seam rows — the largest port, and the one with the most *duplication*
(5× alias dicts, 4× haplotig keyword tuples, 4× merquryk path derivations, 2× insect-prefix
tuples). Effort is mostly M because each is small but the semantics must be preserved exactly.

---

## Port 5 ReleaseTarget

| file:line | assumption | semantic / syntactic | effort |
|---|---|---|---|
| `grit/steps/post_curation/finalize_qc.py:222-232` | destination is `ctx.assembly_curated_dir` (derived, §4a) unless `--curated-dir` overrides | ToL layout | M |
| `grit/steps/post_curation/finalize_qc.py:168-171, 233-288` | release filenames `{tol_id}[.{hap}].{v}.{primary.curated.fa \| all_haplotigs.curated.fa \| additional_haplotigs.curated.fa \| primary.chromosome.list.csv}` | ToL naming contract | M |
| `grit/steps/post_curation/finalize_qc.py:254-259` | comment: the naming must satisfy **`GritJiraIssue.get_curated_file_name_for_type()`** — an out-of-repo Sanger consumer defines the release contract | distribution | L |
| `grit/steps/post_curation/finalize_qc.py:270-273` | a missing haplotig file is `touch`-ed empty rather than omitted (downstream expects the file to exist) | ToL contract | S |
| `grit/steps/post_curation/finalize_qc.py:290-304` | remapped pretext maps are copied to `curated_pretext_maps_nfs` under the 2-level prefix tree, named `{tol_id}.{v}.{hap}.curated.pretext` | site config | M |
| `grit/steps/post_curation/finalize_qc.py:306-311` | QV is auto-triggered if `<curated>/merquryk` is absent | grit-internal | S |
| `grit/steps/post_curation/finalize_qc.py:319-322` | the *only* "Jira write" is a printed reminder to the human ("don't forget Submission Text and attaching latest savestate") — **no API call** | none | S |
| `grit/steps/post_curation/finalize_qc.py:336`, `grit/core/status.py:679-681` | tip links a **personal GitHub gist** for submission notes (`gist.github.com/zilov/…`) | site/personal | S |
| `grit/steps/post_curation/post_processing.py:17, 50-55` | release handoff = `source /software/grit/projects/contamination_screen/conf/contamination_screen.conf` + `shopt -s expand_aliases` + `post_process_rc {ticket_id}` — a Snakemake pipeline behind a shell **alias** | environment | L |
| `grit/steps/post_curation/post_processing.py:66-68` | successful post-processing sets registry status `done` (`RegistryManager().mark_done`) | grit-internal | S |
| `grit/steps/post_curation/hic_remapping.py:114-115`, `grit/config/sanger_template.yaml:13-15` | the only outward notification is `curationpretext --email <addr>` | site config | S |

**Port 5 verdict:** 11 seam rows, and much lighter than expected. There are **zero** Jira
transitions, comments, attachments or API writes anywhere in the codebase — `grit` is read-only
against Jira. The heavy coupling is (a) the release *filename* contract owed to `GritJiraIssue`, and
(b) `post_process_rc`, a Sanger Snakemake pipeline reachable only via a sourced conf file.

---

## Unclassified environment assumptions

| file:line | assumption | effort |
|---|---|---|
| `grit/utils/helpers.py:100` + `_state_update_epilogue` | **`sys.argv[0]` from the submit host must resolve on the compute node** — only true because `$HOME`/install dir is a shared mount. `grit` must also be executable there. | M |
| `grit/steps/optional/rename_and_orient.py:74-77` | explicit in-code comment: *"$HOME is NFS-shared with the compute node"* — the code depends on it, documented | M |
| `grit/steps/pre_curation/sex_matcher.py:138-141` | creates a **symlink** `run_dir/original.fa → workdir/original.fa` that the compute node must follow | S |
| everything writing to `run_dir` | compute nodes and the submit host see the same `run_dir`; the epilogue re-globs it (`click_cli.py:243-248`) and `status` verifies outputs (`status.py:533`) | M |
| `grit/core/registry.py:34`, `click_cli.py:47` | `~/.grit/` on a shared home; single JSON registry with **no file locking** — two concurrent `grit` runs can lose step records | M |
| `grit/core/click_cli.py:175` | `getpass.getuser()` becomes the username baked into every workdir path | S |
| `grit/config/sanger_template.yaml:2` + `context.py:280-297` | `<username>_curation` directory naming — the *only* per-curator isolation mechanism | S |
| `grit/config/sanger_template.yaml:11` | `farm_host: tol22-head2` hardcoded default; `tests/fixtures/test_config.yaml:6` uses `farm22-login` | S |
| `grit/utils/helpers.py:194-231`, `status.py:617-626` | scp tips assume the curator can `ssh`/`scp` from a laptop to `farm_host` | S |
| any `bsub`/`bjobs` call | the host running `grit` is an LSF submit host with the cluster reachable; `_check_bjobs` swallows all exceptions (`helpers.py:132-133`) so a non-LSF host degrades **silently** | M |
| `grit/core/cleanup.py:41-51` | `du -sb --apparent-size` — GNU coreutils flags, "accurate on Lustre" per the docstring | S |
| `grit/scripts/sex-matcher.sh:3`, `busco-synteny.sh:9` | a *personal* home dir (`~mh6`) must exist and be readable by every curator | M |
| `grit/steps/optional/blast_contaminants.py:35,192` | two tools live under `~mh6/` — tilde-expansion by the shell, so they resolve only if that user's home is mounted | M |
| `.gitignore` (2 lines) | ignores only `__pycache__` and `.worktrees/` — `.venv/`, `.pytest_cache/`, `.ruff_cache/` are untracked-but-unignored (housekeeping, not portability) | S |

---

## External tool table

Bioconda column: **yes** = confirmed present on bioconda; **no** = confirmed searched and absent;
**unknown** = not established, with the check that would settle it.

| Tool / script | How provisioned today | Module version string | Bioconda? | Notes |
|---|---|---|---|---|
| `pretext-to-asm` | `module load grit` (`modules.py:26-27`) | `grit` (unversioned) | **no** (searched; only `pretext-suite`, `pretextmap`, `pretextgraph`, `pretextsnapshot` exist) | Sanger GRIT tool; documented in the public `sanger-tol/rapid-curation` repo. Settle by checking whether that repo ships an installable `pretext-to-asm` and under what licence. **Core blocker candidate.** |
| `PretextGraph` | `module load pretextgraph/0.0.7--h4ac6f70_0` (`modules.py:30`) | `pretextgraph/0.0.7--h4ac6f70_0` | **yes** (`bioconda::pretextgraph`) | The `--h4ac6f70_0` suffix is a bioconda build hash — this module is already a repackaged bioconda build. Trivially portable. |
| `curationpretext.sh` | `module load grit` + `-profile sanger,singularity` (`hic_remapping.py:101-102`) | `grit` | n/a (Nextflow pipeline) | `sanger-tol/curationpretext` is **public on GitHub, MIT-licensed**. Only the `sanger` institutional profile is site-specific. Portable with a new profile. |
| `FastGA`, `ALNchain`, `ALNtoPAF` | `module load fastga/1.1-c1` **inside** `FastGA_dot_dgenies_stats.sh:36` | `fastga/1.1-c1` (bypasses `modules.py`) | **yes** (`bioconda::fastga`; `ALNchain`/`ALNtoPAF` ship with FastGA ≥1.0) | Portable. Note the version pin is outside the "one place" registry. |
| `busco` | `singularity exec -B /lustre <busco.sif>` (`busco_curated.py:128`, `sex-matcher.sh:20…`, `busco-synteny.sh:82`) | n/a (SIF at `/nfs/treeoflife-01/teams/grit/users/mh6/singularity/busco.sif`) | **yes** (`bioconda::busco`) | Tool is portable; the **lineage database** is not — see Data dependencies. |
| `reheader` | `module load grit` (`find_reference.py:50,54,86,90`) | `grit` | **unknown** | Likely a small GRIT utility. Settle by inspecting the `grit` module's `bin/`. |
| `kmer_completeness.bash` | `module load grit` (`qv.py:88`) | `grit` | **no** (Sanger wrapper) | Wraps MerquryFK; both `merquryfk` and `fastk` **are** on bioconda, so the wrapper is re-implementable. Cleanup code (`cleanup.py:76-78`) confirms FastK `.ktab`/`.post` outputs. |
| `rename-and-orient` | pip/uv dependency, resolved via `shutil.which` (`rename_and_orient.py:77`) | n/a | n/a (PyPI/git) | **Already public**: `pyproject.toml:20` → `git+https://github.com/zilov/rename-and-orient`. |
| `get_nearest_comparator.rb` | absolute path `/software/grit/projects/vgp_curation_scripts/` (`find_reference.py:25`) | none | **no** | Sanger-internal Ruby; downloads the nearest NCBI reference. **Blocker** (functionality re-implementable against NCBI Datasets API). |
| `get_lineage_from_species.rb` | absolute path, same tree (`blast_contaminants.py:32`) | none | **no** | Sanger-internal Ruby; returns a `;`-delimited taxonomic lineage. Re-implementable via NCBI taxonomy. |
| `decon_fasta` | `~mh6/git_checkouts/reblast/bin/decon_fasta` (`blast_contaminants.py:35`) | none | **no** | Personal checkout of an internal "reblast" tool. Runs BLAST + writes `taxonomy.txt`. **Blocker; also a data dependency (BLAST nt DB).** |
| `remove_contamination_bed` | `~mh6/remove_contamination_bed` (`blast_contaminants.py:192`) | none | **no** | Personal home. Small BED-based FASTA filter; easily re-implemented. |
| `sex_matcher.py` | `/software/grit/projects/vgp_curation_scripts/sex_matcher.py` (`sex-matcher.sh:46`) | none | **no** | Sanger-internal. **Blocker.** |
| `dgenies_index.py` | `/software/grit/projects/vgp_curation_scripts/` (`FastGA_dot_dgenies_stats.sh:28,30`) | none | **unknown** | Likely vendored from the public D-GENIES project. Settle by diffing against D-GENIES upstream (GPL — check licence before vendoring). |
| `ragtag_paf2delta.py` | `/software/grit/projects/vgp_curation_scripts/` (`FastGA_dot_dgenies_stats.sh:57,74`) | none | n/a | The script's own header says it comes from **RagTag** (public, `malonge/RagTag`). Vendored copy. Licence check needed. |
| `DotPrep.py` | bare name on `$PATH` (`FastGA_dot_dgenies_stats.sh:61,78`) | unclear | **unknown** | From the public `dnanexus/dot` project. Settle by checking which module puts it on `$PATH`. |
| `microchr_second_shot_curation.py` | `/nfs/users/nfs_d/dz11/gitlab/vgp_curation_scripts/birds_microchromosomes/` (`microchromosome_second_shot.py:28-31`) | none | **no** | TEMP pointer at a personal branch checkout. Internally submits its own `bsub -K` jobs. **Blocker.** |
| `combine_curated_micros.py` | same tree (`microchromosome_combine.py:26-29`) | none | **no** | Same. **Blocker.** |
| `hap_bedgraph.py` | `/nfs/users/nfs_d/dz11/hap_bedgraph.py` (`add_pretext_view_tracks.py:24`) | none | **no** | Personal home; step is currently disabled on the CLI (`click_cli.py:155-159`). |
| `post_process_rc` | shell **alias** from `/software/grit/projects/contamination_screen/conf/contamination_screen.conf` (`post_processing.py:17,51-54`) | none | **no** | Sanger Snakemake contamination-screen + submission-prep pipeline. **Blocker.** |
| `sing.bash` | `source /nfs/users/nfs_m/mh6/sing.bash` (`sex-matcher.sh:3`, `busco-synteny.sh:9`) | none | n/a | Personal singularity env bootstrap. |
| `pigz` | bare, inside bsub (`cleanup.py:279`) | none | **yes** (conda-forge) | |
| `du`, `zcat`, `gunzip`, `cp`, `mv`, `mkdir`, `touch`, `rm`, `grep`, `perl`, `awk`, `bash`, `scp` | bare via `_run` | none | n/a | GNU coreutils flags used (`du -sb --apparent-size`) — not macOS-portable. |
| `uv` | bare, inside bsub payload (`fastga_synteny.py:94`, `busco-synteny.sh:101`) | none | **yes** (conda-forge) | PEP-723 scripts declare `pandas`, `seaborn`, `python-circos`, `biopython`, `requests`. |
| `singularity` | bare (`busco_curated.py:128` etc.) | none | n/a | Also implies `/lustre` is bind-mountable. |

---

## Data dependencies

Data coupling is often harder than code coupling; these are the embedded datasets.

| Resource | Referenced at | Nature | Portable? |
|---|---|---|---|
| BUSCO lineage database | `busco_curated.py:29` (`_BUSCO_LINEAGES = /lustre/scratch122/tol/resources/busco/latest/lineages`), `busco_curated.py:126`, `sex-matcher.sh:20,24,28,34`, `busco-synteny.sh:83` | Public data, Sanger-mirrored path | **Yes** — BUSCO can download lineages; only the path is site-specific. Note `latest` is a *mutable* symlink, so runs are not reproducible across time. |
| BUSCO singularity image | `busco_curated.py:28`, `sex-matcher.sh:4`, `busco-synteny.sh:11` (`/nfs/treeoflife-01/teams/grit/users/mh6/singularity/busco.sif`) | Container in a personal dir | **Yes** — replaceable with a bioconda env or a public biocontainer. |
| Sex-chromosome BUSCO ID lists | `sex-matcher.sh:12-14, 21, 25, 29, 35` — `coleop_X_buscos`, `lep_Z_buscos`, `nematode_X_buscos`, `dip_LG6`, all under `/nfs/users/nfs_d/da16/vgp_curation_scripts/` | **Curated ID lists in a personal home dir** | **Unknown provenance.** These are small text files but they are the substance of `sex-matcher`. Settle by asking whether they are derivable from published literature or are internal work product. Without them the step is inert. |
| NCBI reference genomes | downloaded at run time by `get_nearest_comparator.rb -d` (`find_reference.py:192`) | Public data via an internal client | **Yes** in principle — data is public, the client is not. |
| BLAST nucleotide database | implicit inside `decon_fasta` (`blast_contaminants.py:35`); the step only sees `taxonomy.txt` | Presumably a site-mirrored `nt`/`core_nt` | **Unknown size/location** — never named in this repo. Settle by reading `~mh6/git_checkouts/reblast`. This is a serious hidden data dependency (hundreds of GB). |
| Contamination-screen resources | behind `contamination_screen.conf` (`post_processing.py:17`) | Unknown | **Unknown.** Settle by reading the conf file. |
| TreeVAL telomere BED | `add_pretext_view_tracks.py:122-124` — expected under the draft assembly dir | Produced upstream by the ToL TreeVAL pipeline (public: `sanger-tol/treeval`) | **Yes**, if TreeVAL output is available. |
| Taxonomy for lineage → phylum | `get_lineage_from_species.rb` (`blast_contaminants.py:32`); the *4th* `;`-separated element is assumed to be the phylum (`blast_contaminants.py:149`) | Public taxonomy, internal client | **Yes**, re-implementable. The "index 3 = phylum" assumption is itself fragile. |

---

## Existing partial abstractions

Honest assessment of what already exists to build on.

### `CurationContext` (`grit/core/context.py`) — **strong**, ~70% of a real injection point
Every step takes `ctx` and holds no global state; this is genuinely the single place where a
different environment could be substituted. **What's missing:** `CurationContext` is a
*frozen-ish dataclass of values*, not a container of *behaviours* — it carries `farm_host`,
`pretext_maps_nfs`, `username`, `bsub_ram` as bare fields, and steps reach for module/bsub helpers
by direct import rather than through `ctx`. So there is no seam through which to swap an
executor or a tool provider. It also embeds the derivation logic itself (`_derive_workdir`,
`assembly_curated_dir`, `_detect_assembly_type`) rather than delegating it.

### `_run(cmd, print_only, capture)` (`grit/utils/helpers.py:42-59`) — **strong**, the real choke point
Genuinely every shell command goes through it; `print_only` is enforced here, once. **What's
missing:** it takes an already-assembled *string* with `shell=True`, so by the time a command
reaches `_run` the module fragment, the `cd`, the absolute script path and the LSF quoting are all
baked in. A provider abstraction must intercept *before* `_run`, not at it. There are two
documented bypasses: `subprocess.run(["du", …])` (`cleanup.py:42-47`) and
`subprocess.run(["bash"], input=script)` (`post_processing.py:63`), plus `_check_bjobs`
(`helpers.py:120`) which calls `subprocess.run` directly.

### `--print-only` — **strong for its purpose**, not a port
Uniformly respected, and the printed command is exactly what would run. That makes it an excellent
*verification* tool for any port work (diff the printed commands before/after a refactor). It is not
itself an abstraction.

### `--dry-run` / `dry_run_root()` (`registry.py:38-40`, 23 supported commands) — **strong, and underrated**
This is the closest thing in the repo to a working "run grit with no Sanger infrastructure" mode:
it isolates the registry, every workdir and the curated-release dir under `~/.grit/dry_run/`, and
each step writes placeholder outputs via `write_fake_outputs()` from the same `_OUTPUT_SPECS` the
real path uses. `tests/local_smoke_test.sh` chains real steps this way. **What's missing:** it fakes
*outputs*, never *commands* — every dry-run branch is a separate `if ctx.dry_run:` early-return
(23 of them), so it validates sequencing and canonical resolution but proves nothing about whether
a command would work elsewhere. `validate-files` is allowlisted but unreachable
(`click_cli.py:154-155, 277`), and `add_pretext_view_tracks` deliberately has no branch.

### `grit/utils/modules.py` — **weak**, covers ~2 of ~20 tools
See Port 2. It is the right *shape* (one logical key → one provisioning fragment) but its coverage
is small and one version pin already escaped it (`FastGA_dot_dgenies_stats.sh:36`). The
shell-fragment return type is the part that will need to change.

### `build_bsub_opts()` (`helpers.py:137-191`) — **moderate**
Already takes *semantic* named parameters (`queue`, `memory_mb`, `cores`, `output`, `error`,
`group`, `wait`, `run_dir`) and emits LSF syntax in one place. That parameter list is very close to
a scheduler-neutral resource request. **What's missing:** `queue` and `group` are LSF concepts
leaking into the signature, and callers pass site-specific literals (`"normal"`, `"team135"`).

### `_OUTPUT_SPECS` + `collect_outputs()` + `manifests.STEP_MANIFESTS` — **moderate**
Output discovery is declarative and shared by the epilogue path, the bjobs-recovery path,
`_step_output`'s re-glob and `write_fake_outputs`. **What's missing:** the specs are *ToL filename
patterns*, so they belong to Port 4, and `_get_step_specs` (`helpers.py:872-910`) is a hardcoded
19-entry name→module map. `STEP_MANIFESTS` is a *second*, partly-inconsistent source of the same
information (e.g. `find_reference` manifest says `reference/*.fa` while the step writes to a
tracked run dir).

### `grit/config/` — **does not exist yet**
The pixi draft's System Design block shows `grit/config/environments.py` and
`grit/config/settings.py`. **Neither file exists.** `grit/config/` contains exactly
`__init__.py` (empty), `init.py` (24 lines: writes the template) and `sanger_template.yaml`
(23 lines). This is important: the draft reads as though a config layer is half-built when in
fact nothing of it exists.

### `RunTracker` / `RegistryManager` — **moderate, and scheduler-agnostic already**
The step-history model (`start` → `record_job` → `finish`, plus `untracked`) is expressed in
neutral terms; only `job_id`'s *interpretation* and the bjobs recovery paths are LSF-aware.

---

## Assessment of `TODO/XX_pixi_portability_plan.md`

**Is the lmod-vs-pixi two-mode design sound?** Yes as far as it goes, and the auto-detection idea
(`GRIT_ENV_BACKEND` env override → `shutil.which("pixi")` → Lmod → conda) is reasonable. Keeping the
lmod path working so the Sanger distribution is unchanged is exactly right for an open-core split.

**Does it cover the seams actually found?** No — it covers roughly **one of five ports, partially.**

What it gets right:
- Correctly identifies `modules.py` as the mechanism to refactor and `tool_cmd(tool_key)` as the
  point of indirection.
- Correctly flags `curationpretext` as needing containerisation.
- Correctly notes `pixi.lock` reproducibility, which is a real improvement over `module load grit`
  (an unversioned, mutable module — `modules.py:26-32` pins nothing).
- Step 4's "move hardcoded paths into `settings.py`" points at Port 4, even if it doesn't
  enumerate it.

What it misses or gets wrong:

1. **`environments.py` and `settings.py` do not exist.** Step 2 says "заполнить" (fill in) — there is
   nothing to fill in. `grit/config/` has only `init.py` and the Sanger template. This changes
   Step 2 from "complete a stub" to "design and build a config layer".
2. **It treats `MODULE_VERSIONS` as the tool inventory.** It isn't. `MODULE_VERSIONS` has 5 keys
   covering 2 real modules; the External tool table above lists **~20 externally-provided tools**,
   ~14 of which are hardcoded absolute paths that `modules.py` never touches, including four in
   personal home directories. The Open Questions section asks "which tools from `MODULE_VERSIONS`
   are in bioconda?" — that is the wrong denominator by ~4×.
3. **No mention of Port 1 at all.** 117 `bsub`-touching lines, `-Ep`/`$LSB_JOBEXIT_STAT`, `bjobs`
   polling in `registry.py`/`status.py`, and the `TERM_MEMLIMIT` UX are entirely absent. pixi
   provisions tools; it does not submit jobs. A pixi-only port produces a `grit` that can find
   `FastGA` and then immediately fails at `bsub`.
4. **No mention of Port 3.** `GritJiraIssue` via `sys.path` is both the largest coupling and a
   distribution problem (see PORT3-01) and is not referenced.
5. **No mention of Port 5.** `post_process_rc` behind a sourced conf + shell alias, and the release
   filename contract owed to `GritJiraIssue`, are unaddressed.
6. **Data dependencies are absent.** The BUSCO lineage tree, the sex-BUSCO ID lists in `~da16`, and
   the unnamed BLAST database inside `decon_fasta` cannot be pixi-installed. This is the category
   most likely to become a late blocker.
7. **`FastGA_dot_dgenies_stats.sh:36` already escapes the registry** — a `module load fastga/1.1-c1`
   outside `modules.py`. The claim that changing one line in `modules.py` updates a tool version is
   already false for FastGA.
8. **Singularity is a third provisioning mode**, alongside lmod and pixi (BUSCO runs only via
   `singularity exec -B /lustre <sif>`, sourced from `~mh6/sing.bash`). The two-mode table needs a
   third row, or the SIF path needs to become a pixi-installed `busco`.
9. **`module_cmd`'s return type is the hard part.** Today it returns a shell fragment that callers
   `&&`-concatenate into a larger string, sometimes with a preceding `cd` and always inside bsub
   quoting (`helpers.py:79`). Making `tool_cmd()` "return either `module load …` or just the binary
   name" (Step 3) changes the string's *arity* — 12 call sites build `f"{module_cmd('X')} && …"`
   and would produce `" && …"` with a leading `&&` if the fragment becomes empty. This needs a real
   design decision, not a return-value swap.
10. **`pixi run grit` and the bsub epilogue interact.** `_state_update_epilogue` embeds
    `sys.argv[0]` (`helpers.py:100`) as the compute-node path to `grit`. Under pixi that path is
    inside a pixi env directory — it will only resolve on the compute node if the env is on shared
    storage *and* the env's activation isn't needed. Not considered.
11. **Testing/verification strategy is absent**, despite `--print-only` and `--dry-run` being
    tailor-made for it (diff printed commands across backends).

**Verdict:** a reasonable Step-1 note for Port 2 specifically; not a portability plan. It should be
scoped down explicitly to "ToolProvider, lmod↔pixi" and the other four ports raised separately.

---

## Cannot be open-sourced

**No credentials, tokens, passwords, API keys or connection strings were found anywhere in this
repository.** A targeted scan of `grit/`, `pyproject.toml` and the config template for
`password|secret|api_key|token|credential|auth` returned only false positives (`pathlib`,
"Path"). The one config template committed (`grit/config/sanger_template.yaml`) contains paths and
a hostname only.

The credential surface exists but lives **outside** the repo: `GritJiraIssue` must authenticate to
Jira somehow, and the unused `pymysql` dependency (`pyproject.toml:12`) suggests a database
connection too. Those credentials are wherever `GritJiraIssue` keeps them
(`/nfs/users/nfs_d/dz11/gitlab/vgp_submission/modules/`) — **out of scope of this repo, but must be
audited before any split**, because a public `grit` core must not accidentally document how to
reach them.

| Item | file:line | Why it can't ship publicly | Status |
|---|---|---|---|
| `GritJiraIssue` library | `context.py:237-241`, `sanger_template.yaml:17-23` | Internal ToL library, not vendored here; ticket schema + auth. Also encodes the release filename contract (`finalize_qc.py:254`). | **Blocker for Port 3.** Not in repo — the split needs a protocol, not the library. |
| Jira custom field ID `customfield_11650` | `context.py:243` | Internal Jira schema detail; meaningless and non-portable outside Sanger. Not secret. | Friction. |
| `/software/grit/projects/vgp_curation_scripts/*` (5 scripts) | `find_reference.py:25`, `blast_contaminants.py:32`, `sex-matcher.sh:46`, `FastGA_dot_dgenies_stats.sh:28,30,57,74` | Internal Sanger script tree. Licence **unknown**. Two of them (`ragtag_paf2delta.py`, `dgenies_index.py`) appear to be *vendored copies of public GPL-ish projects* — republishing those has its own licence obligations. | **Unknown — settle by reading the tree's LICENSE/headers.** |
| `/software/grit/projects/contamination_screen/conf/contamination_screen.conf` + `post_process_rc` | `post_processing.py:17,51-54` | Internal Snakemake pipeline reached via a shell alias; contents unknown, may itself contain paths/credentials. | **Blocker for Port 5.** |
| `~mh6/git_checkouts/reblast/bin/decon_fasta`, `~mh6/remove_contamination_bed` | `blast_contaminants.py:35,192` | Another person's personal checkouts; no licence, no ownership claim by this project. | **Blocker for `blast-contaminants`.** |
| `/nfs/users/nfs_m/mh6/sing.bash` | `sex-matcher.sh:3`, `busco-synteny.sh:9` | Personal env bootstrap. | Friction. |
| `/nfs/users/nfs_d/da16/vgp_curation_scripts/{coleop_X_buscos,lep_Z_buscos,nematode_X_buscos,dip_LG6}` | `sex-matcher.sh:12-14,21,25,29,35` | Curated sex-BUSCO ID lists in a personal home; provenance and ownership **unknown**. | **Unknown — ask the author.** Data, not code. |
| `/nfs/users/nfs_d/dz11/gitlab/vgp_curation_scripts/birds_microchromosomes/*.py` | `microchromosome_second_shot.py:28-31`, `microchromosome_combine.py:26-29` | Currently a personal branch checkout of an internal repo (both marked TEMP). | **Blocker for the microchromosome workflow.** |
| `/nfs/users/nfs_d/dz11/hap_bedgraph.py` | `add_pretext_view_tracks.py:24` | Personal script. Step is CLI-disabled today, so low urgency. | Friction. |
| Internal hostnames / mount points: `tol22-head2`, `/nfs/treeoflife-01/...`, `/lustre/scratch122/...`, `/lustre/scratch124/...`, `/software/grit/...` | `sanger_template.yaml:5,8,11`; `busco_curated.py:28-29`; `registry.py:14`; `tests/fixtures/*.yaml` (98 lines) | Internal infrastructure topology. Not secret (published in ToL papers) but should not be defaults in a public core. Note the test fixtures are full of real `/lustre/scratch124/tol/projects/asg/...` paths. | Friction — move to the Sanger distribution's config. |
| Personal gist URL `gist.github.com/zilov/93b1e6c68a6e2553b7c12770d6a0a3ef` | `status.py:680`, `finalize_qc.py:336` | Publicly reachable but is a personal, unversioned note; not appropriate as a core-shipped default. Also **unverified** whether its content is internal-only. | Friction — check the gist's contents before publishing a link to it. |

Not a licence problem: `sanger-tol/curationpretext` is public and MIT-licensed;
`rename-and-orient` is already a public git dependency (`pyproject.toml:20`).

---

## Findings

Records for genuine problems, beyond mere inventory.

---
**PORT1-01** | severity: **major** | confidence: **confirmed**
| `grit/utils/helpers.py:108-134` (and `registry.py:242-279`, `status.py:457-463`)
| claim: `_check_bjobs` swallows every exception and returns `"gone"` for all job IDs when `bjobs` is absent, so on a non-LSF host grit silently reports finished jobs as gone rather than reporting that no scheduler exists.
| failure scenario: A user outside Sanger runs `grit status`. `bjobs` isn't installed; `subprocess.run` raises `FileNotFoundError`; the bare `except Exception` logs at DEBUG only. Every pending job is classified `"gone"`, and `_resolve_gone_job` (`registry.py:281-297`) then marks steps `failed` purely because output files aren't there yet — corrupting the registry with false failures, with no error message explaining why.
| effort: **S** | blast radius: **cross-module** (helpers → registry → status → run_tracker)
| debt quadrant: **inadvertent-prudent** (the try/except was defensive, the "gone" default was chosen for LSF history ageing, not for a missing scheduler)
| open-source impact: **friction**

---
**PORT1-02** | severity: **major** | confidence: **confirmed**
| `grit/utils/helpers.py:100` (`grit_bin = sys.argv[0]`), used at `helpers.py:103`
| claim: The completion-callback mechanism embeds the submit host's own `argv[0]` path as the compute-node path to `grit`, so it works only when the grit installation is on a filesystem shared with compute nodes.
| failure scenario: Someone installs grit into a container, a venv on node-local disk, or a pixi environment that isn't on shared storage. Every `bsub -Ep` epilogue fails silently (LSF does not surface epilogue failures to the user), so every bsub-submitted step stays `started` forever. The only recovery is the bjobs fallback in `status.py:523-550`, which PORT1-01 shows is itself fragile off-LSF.
| effort: **M** | blast radius: **cross-module** (every `_submit_bsub` caller)
| debt quadrant: **deliberate-prudent** (the comment on `helpers.py:100` names the reason: "full path — ensures grit is found in bsub epilogue environment")
| open-source impact: **friction**

---
**PORT2-01** | severity: **critical** | confidence: **confirmed**
| `blast_contaminants.py:32,35,192`; `find_reference.py:25`; `post_processing.py:17`; `microchromosome_second_shot.py:28`; `microchromosome_combine.py:26`; `sex-matcher.sh:12-14,46`; `FastGA_dot_dgenies_stats.sh:28,30,57,74`; `add_pretext_view_tracks.py:24`
| claim: At least **14** distinct external programs are invoked by hardcoded absolute Sanger paths that `modules.py` does not manage, four of them inside individual people's home directories.
| failure scenario: A user outside Sanger installs the public core, runs `grit blast-contaminants`, and gets `/bin/sh: /software/grit/projects/vgp_curation_scripts/get_lineage_from_species.rb: No such file or directory` — from `_run`'s `check=True`, i.e. a raw `CalledProcessError` traceback with no actionable message. Same for `find-reference`, `sex-matcher`, `microchromosome-*`, `post-processing`, and `fastga`'s indexing/delta steps. That is roughly half the command surface.
| effort: **L** | blast radius: **cross-module** (9 step modules + 2 bundled shell scripts)
| debt quadrant: **inadvertent-reckless** for the `~mh6`/`~da16`/`~dz11` paths (personal homes were never a supportable dependency, even inside Sanger); **deliberate-prudent** for the `/software/grit/...` ones (a real shared tree, correctly used at the time)
| open-source impact: **blocker**

---
**PORT2-02** | severity: **major** | confidence: **confirmed**
| `grit/scripts/FastGA_dot_dgenies_stats.sh:36` vs `grit/utils/modules.py:4-8, 24-32`
| claim: `modules.py`'s stated contract — "to upgrade a tool, change the version string in this file only" — is already violated: `module load fastga/1.1-c1` is pinned inside a bundled shell script.
| failure scenario: A maintainer upgrades FastGA by editing `MODULE_VERSIONS` and observes no change, because the FastGA version actually used comes from a shell script. On a non-Lmod host, that `module load` line fails and `FastGA`/`ALNchain`/`ALNtoPAF` are simply not on `$PATH` — but the script has no `set -e`, so it continues and produces a truncated/empty PAF, and `grit fastga`'s epilogue then reports success or an unclear partial-output state.
| effort: **S** | blast radius: **module** (`fastga.py` + its script)
| debt quadrant: **inadvertent-prudent** (the script was adopted from `/software/grit/projects/vgp_curation_scripts/FastGA_dot.sh` — see its own usage line 7 — and vendored without reconciling it with `modules.py`)
| open-source impact: **friction**

---
**PORT2-03** | severity: **major** | confidence: **confirmed**
| `grit/utils/modules.py:26-32` (`"GRIT": "grit"`, `"PRETEXT_TO_ASM": "grit"`, `"CURATIONPRETEXT": "grit"`, `"FASTGA": "grit"`)
| claim: Four of five module keys resolve to a single **unversioned** module named `grit`, so the tool versions actually used are whatever that mutable module currently points at.
| failure scenario: Not a portability break so much as a reproducibility one — and it defeats the pixi plan's main selling point. Two curators on the same day can get different `pretext-to-asm`/`kmer_completeness.bash`/`reheader` behaviour with identical grit versions, and there is no record in the registry of which tool version produced a curated FASTA. Porting to pixi requires first *discovering* what the `grit` module actually contains.
| effort: **M** (discovery, not code) | blast radius: **module**
| debt quadrant: **deliberate-reckless** (convenient for the site team; the file's own docstring promises version pinning it does not deliver)
| open-source impact: **friction**

---
**PORT3-01** | severity: **critical** | confidence: **confirmed**
| `grit/core/context.py:237-239`; `grit/config/sanger_template.yaml:17-23`; `pyproject.toml:12`
| claim: `GritJiraIssue` is imported by mutating `sys.path` at call time from a user-config path, which is simultaneously a coupling problem (no interface, no version, no type) and a distribution problem (it cannot be declared, pinned, or installed).
| failure scenario: Outside Sanger the import raises `ModuleNotFoundError` from inside `CurationContext.from_ticket`, so *every* command that omits `--yaml` fails at context construction — including `grit status -t <ticket>`, which needs it only for a display summary (`status.py:431-437`). Worse for maintenance: the config template's own comment (`sanger_template.yaml:19-22`) records that the shared copy is mid-refactor and the default has been repointed at one developer's personal gitlab checkout, so today every curator's grit depends on `dz11`'s home directory. The `pymysql` dependency in `pyproject.toml:12` is imported nowhere in this repo, implying the injected library reaches a database whose access requirements are invisible to `grit`.
| effort: **L** | blast radius: **cross-module** (context → every step → status)
| debt quadrant: **deliberate-reckless** — the `sys.path.insert` was chosen to avoid packaging the shared library, and the TEMP repoint to a personal path made an already-fragile arrangement personal
| open-source impact: **blocker**

---
**PORT3-02** | severity: **minor** | confidence: **confirmed**
| `grit/core/context.py:236, 243, 248`
| claim: `teloseq` is obtainable only from Jira custom field `customfield_11650`; the `yaml_override` path hardcodes it to `""`.
| failure scenario: A YAML-driven user runs `hic-remapping`; `curationpretext` is invoked without `--teloseq` (`hic_remapping.py:112-113`), so telomere-aware splitting is silently skipped. No warning is emitted — the output looks normal but is subtly different from what a Jira-driven run produces. This is the single concrete gap between `from_yaml` and a complete Jira-free path.
| effort: **S** (accept `teloseq` as a YAML key) | blast radius: **file**
| debt quadrant: **inadvertent-prudent**
| open-source impact: **friction**

---
**PORT3-03** | severity: **minor** | confidence: **confirmed**
| `grit/core/context.py:28, 38` (`gritjiraissue_path=d["gritjiraissue_path"]`)
| claim: `UserConfig.from_dict` requires `gritjiraissue_path` unconditionally, even on the pure-YAML path where it is never read.
| failure scenario: A YAML-only user gets `KeyError: 'gritjiraissue_path'` while constructing the context, for a Jira library they will never load. The test fixture works around this with a dummy value (`tests/fixtures/test_config.yaml:7: /tmp/dummy_gritjiraissue`), which is the tell.
| effort: **S** | blast radius: **file**
| debt quadrant: **inadvertent-prudent**
| open-source impact: **friction**

---
**PORT4-01** | severity: **major** | confidence: **confirmed**
| `grit/core/context.py:280-297` (raises), `context.py:159-162`, `grit/core/status.py:610`
| claim: The workdir and curated-release directories are derived by literal string substitution on `assembly/draft`, and `_derive_workdir` **raises `ValueError`** when that substring is absent — the ToL directory convention is a hard precondition, not a default.
| failure scenario: A user points `--yaml` at a genuinely local assembly (`/data/myproject/asm/foo.hap1.fa`). `CurationContext.from_yaml` raises `ValueError: Expected 'assembly/draft' in draft path` before any step runs. There is no config knob, no override flag, and the error names an internal Sanger convention the user has never heard of. `status.py:610`'s independent `.parent.parent.parent` re-derivation of the same relationship means the assumption is encoded in two places that can drift.
| effort: **M** | blast radius: **cross-module**
| debt quadrant: **deliberate-prudent** (CLAUDE.md explicitly records dropping a separate `curations_dir` setting in favour of derivation — a real simplification at the time)
| open-source impact: **blocker**

---
**PORT4-02** | severity: **major** | confidence: **confirmed**
| `grit/utils/helpers.py:317-322, 442-447, 501-506, 586-591` (4 identical) and `helpers.py:655` (a 5th, **different**)
| claim: The `primary/paternal→hap1, alternate/maternal→hap2` alias table is duplicated five times, and the fifth copy (`find_hap_agp`) omits `paternal`/`maternal` entirely.
| failure scenario: For a paternal/maternal ticket, `find_canonical_fa` resolves via the alias but `find_hap_agp` does not, so `grit super-to-scaffold` raises `FileNotFoundError: No curated AGP for 'paternal' found` on an assembly whose FASTA resolved fine. Any port work that touches haplotype naming must find and update all five. (Note `_detect_assembly_type` at `context.py:264-277` cannot even *produce* `paternal`, so this is latent today — but the aliases exist because the naming is expected.)
| effort: **M** | blast radius: **module** (`helpers.py`), with cross-module behavioural reach
| debt quadrant: **inadvertent-reckless** (copy-paste across four functions added incrementally; the divergence in the fifth is the predictable outcome)
| open-source impact: **friction**

---
**PORT4-03** | severity: **major** | confidence: **confirmed**
| `grit/core/status.py:667-669`; `sex_matcher.py:33, 87-95`; `setup.py:334, 394-398`; `finalize_qc.py:33-39`; `sex-matcher.sh:9-35`
| claim: The ToL ID's leading characters carry taxonomic meaning that drives control flow — `b…`⇒bird, `ic/il/id/n…`⇒insect/nematode, and `tol_id[0]`/`tol_id[1]` index directly into an NFS directory tree — and the insect-prefix table is defined twice with different contents (`("ic","il","id","n")` vs `("ic","il","id")`).
| failure scenario: Any non-ToL identifier breaks these silently or loudly: `grit sex-matcher` **exits 1** for any tol_id not starting with `ic/il/id/n` (`sex_matcher.py:88-95`); `finalize_qc._resolve_nfs_dest` indexes `tol_id[0]`/`tol_id[1]` and, finding no match, warns and returns a literal path containing `?` characters (`finalize_qc.py:39`) which is then used as a `cp` destination; a genome whose ID happens to start with `b` gets an irrelevant bird-microchromosome tip. Outside ToL the ID has no such structure at all.
| effort: **M** | blast radius: **cross-module**
| debt quadrant: **deliberate-prudent** (ToL IDs really do encode clade at Sanger; encoding that in the tool was reasonable in-context) shading to **inadvertent-reckless** for the duplicated, divergent prefix tuples
| open-source impact: **blocker** for the affected steps, friction elsewhere

---
**PORT4-04** | severity: **minor** | confidence: **confirmed**
| `grit/steps/post_curation/hic_remapping.py:131` vs `grit/utils/helpers.py:224`, `status.py:624,657`, `setup.py:279`, `microchromosome_second_shot.py:155`
| claim: The curator's local download directory is `~/curations/work/{tol_id}/` in five places and `~/curations/{tol_id}/` in one.
| failure scenario: The scp tip printed after `hic-remapping` copies the remapped map into a directory that does not exist (or into the wrong one), so the curator's `scp` fails or silently lands the file outside the folder every other tip uses. Small, but it's exactly the class of convention drift a StorageLayout port has to freeze.
| effort: **S** | blast radius: **file**
| debt quadrant: **inadvertent-reckless**
| open-source impact: **none**

---
**PORT5-01** | severity: **critical** | confidence: **confirmed**
| `grit/steps/post_curation/post_processing.py:17, 50-68`
| claim: The final release step executes `source <conf> ; shopt -s expand_aliases ; cd <curated> ; post_process_rc <ticket>` through a piped-in bash script, where `post_process_rc` is a **shell alias** defined by a Sanger conf file — there is no binary, no path, and no way to substitute an implementation.
| failure scenario: Outside Sanger the `source` fails, `post_process_rc` is not found, `subprocess.run(check=True)` raises, the tracker records `failed`, and the user is told nothing about what the step even was. There is no seam here at all — not a path constant to override, not a module key, just an alias in someone else's config file. Note also that on success this step calls `RegistryManager().mark_done` (`:68`), so the terminal state of a ticket is gated on a Sanger-only pipeline.
| effort: **L** | blast radius: **module**
| debt quadrant: **deliberate-reckless** (`shopt -s expand_aliases` is a deliberate workaround to invoke something that was never meant to be invoked programmatically)
| open-source impact: **blocker**

---
**PORT5-02** | severity: **major** | confidence: **plausible**
| `grit/steps/post_curation/finalize_qc.py:254-268`
| claim: The release filenames grit writes are governed by an out-of-repo function, `GritJiraIssue.get_curated_file_name_for_type()`, and the code contains logic specifically to guess what that function will look for (`additional_haplotigs` vs `all_haplotigs`, inferred from disk rather than from the YAML flag).
| failure scenario: The public core's "correct" output naming is defined by a private library nobody outside Sanger can read. A downstream reimplementation has no specification to target, and any change on the `GritJiraIssue` side breaks `grit` silently — files are copied with names the consumer ignores, and `finalize-qc` still reports success. Marked *plausible* rather than confirmed because the assertion rests on the code comment; the library itself was not read.
| effort: **M** | blast radius: **file**, with an external contract
| debt quadrant: **deliberate-prudent** (the comment explains the reasoning and prefers on-disk truth over the YAML flag — good judgement inside a bad boundary)
| open-source impact: **blocker**

---
**DATA-01** | severity: **major** | confidence: **plausible**
| `grit/steps/optional/blast_contaminants.py:35, 167-172`
| claim: `blast-contaminants` depends on a BLAST nucleotide database that is never named anywhere in this repository — it is hidden inside `~mh6/.../decon_fasta`, and grit only ever sees the resulting `taxonomy.txt`.
| failure scenario: A porting effort resolves the *code* dependency (re-implementing `decon_fasta` against public BLAST) and only then discovers it also needs a multi-hundred-GB `nt`-class database plus taxonomy mapping, which no amount of pixi/conda work provides. This is the "data coupling is harder than code coupling" case the brief warns about, and it is completely invisible from the source. Marked *plausible* because the database's identity and size are inferred from what `decon_fasta` must do, not observed.
| effort: **L** | blast radius: **module**
| debt quadrant: **inadvertent-prudent** (hiding the DB behind a tool is good encapsulation; the cost only appears at the portability boundary)
| open-source impact: **blocker** for this step
| settles by: reading `~mh6/git_checkouts/reblast`

---
**DATA-02** | severity: **major** | confidence: **confirmed**
| `grit/scripts/sex-matcher.sh:12-14, 21, 25, 29, 35`
| claim: The entire `sex-matcher` step is driven by four curated BUSCO-ID list files living in a third party's personal home directory (`/nfs/users/nfs_d/da16/vgp_curation_scripts/`), with no provenance, licence, or ownership recorded anywhere.
| failure scenario: Without those files, `grep -f $sexFile ...` (`sex-matcher.sh:44`) matches nothing, `sex_matcher.py` produces an empty or missing `Best_match*` file, and the step's recovery path (`registry.py:294-296`) marks it `failed` with no indication that the *reference data*, not the tool, was missing. They are small text files and could plausibly be published — but that requires asking their author, and nothing in this repo records who that is beyond the path.
| effort: **M** (mostly a permissions/provenance question, not code) | blast radius: **module**
| debt quadrant: **inadvertent-reckless**
| open-source impact: **blocker** for this step
| settles by: asking `da16` about provenance and licence of `coleop_X_buscos`, `lep_Z_buscos`, `nematode_X_buscos`, `dip_LG6`

---
**DATA-03** | severity: **minor** | confidence: **confirmed**
| `grit/steps/optional/busco_curated.py:29`; `sex-matcher.sh:20,24,28,34`; `busco-synteny.sh:83`
| claim: The BUSCO lineage path embeds `latest`, a mutable symlink (`/lustre/scratch122/tol/resources/busco/latest/lineages`), in five places.
| failure scenario: Portability-wise this is easy (BUSCO downloads lineages). Reproducibility-wise, two runs months apart silently use different lineage versions, and the completeness figures recorded in `grit status` are not comparable. A public core that copies this pattern inherits the same non-reproducibility.
| effort: **S** | blast radius: **cross-module** (Python + two shell scripts)
| debt quadrant: **deliberate-prudent**
| open-source impact: **friction**

---
**ABST-01** | severity: **major** | confidence: **confirmed**
| `TODO/XX_pixi_portability_plan.md` System Design block vs `grit/config/` (actual contents: `__init__.py`, `init.py`, `sanger_template.yaml`)
| claim: The pixi plan's Step 2 and Step 4 both assume `grit/config/environments.py` and `grit/config/settings.py` already exist as stubs to be filled in. Neither file exists in any form.
| failure scenario: Anyone scoping Phase 2 from that document will under-estimate the config work — "fill in `detect_backend()`" reads as an afternoon; designing where site configuration lives (and reconciling it with `UserConfig`, `sanger_template.yaml`, `~/.grit/grit_curation_config.yaml` and `dry_run_root()`, all of which already hold pieces of it) is a design task in its own right.
| effort: **M** | blast radius: **cross-module**
| debt quadrant: **inadvertent-prudent** (a plan written from an intended structure rather than the actual tree)
| open-source impact: **friction**

---
**ABST-02** | severity: **minor** | confidence: **confirmed**
| `grit/utils/modules.py:83` and the 12 `module_cmd()` call sites (`hic_remapping.py:101`, `qv.py:87`, `pretext_to_asm.py:126`, `fastga.py:134,219`, `busco_synteny.py:105`, `find_reference.py:57,91`, `sex_matcher.py:152`, `add_pretext_view_tracks.py:60,91,137`)
| claim: `module_cmd()` returns a shell fragment that callers splice into a larger string with `&&`, so any backend that needs *no* preamble cannot simply return `""` — it would yield a command beginning `" && …"`.
| failure scenario: A naive pixi implementation of the plan's Step 3 (`tool_cmd()` returns "either `module load …` or just the binary name") produces malformed commands at 12 sites. In `_submit_bsub` those are additionally wrapped in a single `"…"` pair (`helpers.py:79`), so quoting errors surface as opaque LSF submission failures rather than Python errors.
| effort: **S** per site, **M** for the design decision | blast radius: **cross-module**
| debt quadrant: **deliberate-prudent** (string fragments were the simplest thing that worked with `_run`'s `shell=True` contract)
| open-source impact: **friction**

---
**ENV-01** | severity: **minor** | confidence: **plausible**
| `grit/core/registry.py:299-310` (`_load`/`_save`), `run_tracker.py:95-106`
| claim: The single global registry `~/.grit/grit_registry.json` is read-modify-written with no locking; `_save` is atomic per-write (`os.replace`) but the read-modify-write cycle is not.
| failure scenario: A `bsub -Ep` epilogue firing while the curator runs `grit status` (which calls `refresh_statuses` → many `_save`s) can lose the epilogue's `finish` record entirely, stranding a completed step as `started`. This is more likely under a port, not less: any scheduler with faster callbacks, or a shared-home multi-node setup, widens the window. Marked *plausible* because no corruption was observed — the mechanism is confirmed, the impact is inferred.
| effort: **M** | blast radius: **module**
| debt quadrant: **inadvertent-prudent**
| open-source impact: **none**

---
