# TODO 49: architecture & code-quality assessment (Phase 1)

Read-only assessment of `grit` at `test_and_fix_steps` (`9175121`), run as seven
parallel audits along independent axes. Per-axis reports with full evidence live
in `TODO/claude/assessment/01..07`. This file is the consolidated, deduplicated,
prioritised registry — it is the input to Phase 1's successor, `TODO/50`, which
designs the target architecture. **This document diagnoses only. No fix is
prescribed here.**

Scope measured: 9,483 LOC in `grit/`, 8,803 LOC in `tests/`, 21 steps, 356
commits since 2026-06-02. Test suite: 461 passed in 1.31s.

## Verdict

The architecture is right; several mechanisms inside it are first drafts.

`CurationContext` as an explicit value object, `_run()` as a single execution
chokepoint, `MODULE_VERSIONS` as a one-line-per-tool table, the `bsub -Ep`
epilogue as a completion callback, and the `--dry-run` sandbox are all sound
designs, used consistently, and worth preserving verbatim through Phase 2. The
choice of vanilla Python over a workflow engine is a defensible engineering
judgement, not inexperience — see "Orchestration verdict" below.

Three things undercut that architecture, and all three are input problems rather
than design problems:

1. **The tracker's central safety claim does not hold.** CLAUDE.md states that a
   tracked `success` only ever reflects verified on-disk state. It does not: the
   epilogue writes `success` from the LSF exit status and discards an empty
   output glob instead of downgrading, and four steps record success without
   ever checking their outputs. The mechanism that was built to prevent a green
   status over a broken assembly is correct; the code that consumes it is not.
2. **The registry is a single point of total data loss.** One JSON document,
   whole-file read-modify-write, no locking, a shared fixed `.tmp` path, and a
   `_load()` that maps any read or parse failure to `[]`. One corrupt file plus
   one subsequent write erases every ticket and every step record.
3. **Canonical resolution can ship the wrong genome.** The mtime-pool *policy*
   is sound and should be kept. But the three resolvers select independently
   with no coherence check, so `finalize-qc` routinely ships a FASTA and a
   chromosome list from different, mutually inconsistent runs — and on a
   `primary`/`alternate` ticket the resolvers hand back hap1's files as the
   alternate haplotype's.

The open-core split is feasible, but its difficulty is inverted from where the
existing `TODO/XX_pixi_portability_plan.md` looks: the scheduler layer is easy
(S/M), and the hard part is that roughly half the command surface bottoms out in
Sanger-internal scripts with unknown licences, several inside individual
people's home directories, behind at least one unnamed multi-hundred-GB
database.

## Counts

| Axis | Report | Critical | Major | Minor |
|---|---|---:|---:|---:|
| Architecture & modularity | `01` | 2 | 8 | 10 |
| Correctness & error handling | `02` | 7 | 9 | 10 |
| Testability & test quality | `03` | 3 | 7 | 3 |
| Portability / seam inventory | `04` | — | — | — (125 seams, 19 records) |
| Packaging, DX & security | `05` | 0 | 9 | 11 |
| Canonical domain logic | `06` | 6 | 4 | 6 |
| Build-vs-adopt orchestration | `07` | — | — | — (verdict, not findings) |

Raw total 126 records before deduplication. Deduplicated below into 7 themes.

## Convergent findings

Findings reached independently by two or more axes. These are the highest-
confidence items in the assessment, and the ordering of Phase 2 should follow
them rather than the raw severity counts.

| Theme | Axes that found it independently | IDs |
|---|---|---|
| Registry has no locking; unlocked read-modify-write from login *and* compute nodes | correctness, tests, portability, orchestration (4) | CORR-01, CORR-02, TEST-03, PORT-registry |
| `success` recorded without verifying outputs | correctness, architecture, canonical (3) | CORR-03, CORR-07, ARCH-01, DOM-01 |
| Hardcoded absolute paths in individuals' home directories | architecture, packaging, portability (3) | ARCH-06, SEC-02, PORT-03 |
| `find_canonical_haplotigs` has zero direct tests | tests, canonical (2) | TEST-07, DOM-06 context |
| `GritJiraIssue` via `sys.path` is coupling *and* distribution problem | architecture, packaging, portability (3) | ARCH-17, PKG-04, PORT-06 |
| Step identity duplicated across parallel hand-maintained registries | architecture, correctness (2) | ARCH-03, CORR-10, CORR-13 |
| Shell composition under `shell=True` with no quoting discipline | architecture, packaging, correctness (3) | ARCH-08, SEC-01, CORR-17 |
| No completion detection outside LSF's `-Ep` | portability, orchestration (2) | PORT-02, borrow-1 |

## P0 — data loss or a wrong genome shipped

Fix before any refactoring. Each of these produces the exact outcome the tool
exists to prevent.

**A. Registry integrity.**
- `CORR-01` (`registry.py:299-306`) — `_load()` maps any unreadable or malformed
  registry to `[]`; the next save wipes all tickets and all step history, with
  only a `log.warning`. *Verified directly.*
- `CORR-02` (`registry.py:161-169,308-312`) — unlocked whole-file
  read-modify-write through a shared fixed `grit_registry.tmp`. `_save` is
  atomic per write (`os.replace`) but the read-modify-write cycle is not, and
  the temp path is shared across concurrent writers. Two simultaneous epilogues
  lose a finish record or install a truncated file, which `CORR-01` then
  converts to total loss. There is no `flock`/`fcntl` anywhere in `grit/`.
- **Open question, cheap to settle, potentially worse than the race:** is
  `~/.grit/` on a filesystem visible to compute nodes? If not, the epilogue's
  `grit _state-update` writes to a *different registry file* than the login node
  reads. One command on the farm settles it. Nobody has checked.

**B. `success` without output verification.**
- `CORR-03` (`click_cli.py:228-251` + `helpers.py:89-105` +
  `scripts/sex-matcher.sh:49`) — `state_update_cmd` passes the LSF-derived
  `status` straight to `tracker.finish()`; `outputs` is best-effort and, when
  empty, is recorded as `None` without downgrading the status. `sex-matcher.sh`
  ends in an unconditional `exit 0`, so that step's success is unconditional in
  the most literal sense: a permanently green row with no `Best_match` file, and
  the step's own resubmit guard then refuses to re-run it. *Verified directly.*
- `CORR-07` (`qv.py:80-96`) — synchronous tracked step records `success` as soon
  as the submitting wrapper returns.
- `CORR-08` (`hic_remapping.py:70-84`) — the "already done, skipping" branch
  finalises a run as `success` from the mere existence of an output.
- `CORR-06` (`finalize_qc.py:232-327`) — a missing canonical FASTA is a
  `log.warning` + `continue`; missing haplotigs are `touch`ed empty; then
  success is recorded and the ticket advances to `post_processing` with an
  incomplete release directory.
- `CORR-09` — four steps call `_submit_bsub` outside any try/except after
  `tracker.start()`, stranding the record as `started` on a submission failure.

**C. Canonical resolution selects the wrong file.**
- `DOM-05` (critical, confirmed by execution) — the three resolvers select
  independently with **no compatibility check anywhere**. `blast_contaminants`
  is deliberately excluded from the chr-list pool on the premise that
  contaminant filtering does not touch the chromosome list; that premise is
  false whenever a removed scaffold was a named chromosome. `finalize_qc` copies
  fa and chr into the release dir in three independent loops with no cross-check
  of any kind. The spec itself blesses another incoherent pair at L181-185, so
  the status display cannot distinguish a legitimate split from an incoherent
  one.
- `DOM-06` (critical, confirmed) — `--hap2` is not gated by `is_single_hap` and
  the no-prefix fallbacks guard only the literal tokens `hap1`/`hap2`. On a
  `primary`/`alternate` ticket the resolvers return **hap1's** FASTA and
  chromosome list as `alternate`'s canonical files; `hic-remapping --hap2` then
  publishes hap1's Hi-C map to NFS as the alternate haplotype's.
- `DOM-02` (critical, confirmed) — `latest_run_dir` falls back to `started`
  runs, so a half-written FASTA from an in-flight bsub job is the freshest pool
  member. One `grit hic-remapping` while `rename-and-orient` is running remaps a
  truncated assembly.
- `DOM-01` (critical, confirmed) — commit `143f425` half-fixed the
  backwards-canonical bug: when the newest successful run recorded **no**
  outputs — exactly what the epilogue writes when `collect_outputs` is empty,
  i.e. the `CORR-03` path — `get_output` silently substitutes an older run of
  the same step and the re-glob never fires. A re-run's real output is ignored,
  with nothing anomalous in `grit status`.
- `CORR-04` (`helpers.py:108-134` + `registry.py:242-297`) — `_check_bjobs`
  ignores the subprocess return code and pre-seeds every job id as `gone`, so
  any `bjobs` outage makes `_resolve_gone_job` finalise still-running jobs as
  success off partially written files, which then become canonical.
- `CORR-05` (`pretext_to_asm.py:117`) — curated AGP chosen by unsorted
  `glob.glob(...)[0]`; a stale AGP in the workdir non-deterministically builds
  the wrong curated FASTA and records it as canonical. *Verified directly.*

**D. `--untracked` does not hold.**
- `DOM-03` (critical) — all three resolvers' filesystem fallbacks go through
  `find_latest_dir`, which never consults untracked status, so an `--untracked`
  run is canonical for fa, haplotigs *and* chr_list whenever it is the only run
  of its step, and gets shipped by `finalize-qc`.
- `DOM-04` (critical) — `pending_jobs()` treats only `success`/`failed` as
  terminal, so untracking an *in-flight* run is silently reverted by the next
  `grit status` via `_resolve_gone_job`, which re-`finish`es it without
  `untracked=`. CLAUDE.md asserts this is impossible.
- `DOM-11` — `cleanup`'s keep-set excludes untracked runs, so the newest run dir
  is deleted while an older tracked one is kept, making `retrack` unrecoverable.

Note: the `--untracked` overwrite bug documented in `TODO/tiny.md` **is**
correctly fixed at every `finish()` call site in the step code. What leaks is
the *recovery* and *fallback* paths, which were not part of that fix.

## P1 — structural, blocks Phase 2 from landing incrementally

- `ARCH-01` (critical) — "reconcile a finished LSF job with its outputs" is
  implemented four independent times with four different success criteria
  (`click_cli.py:230-249`, `registry.py:241-296`, `status.py:518-541`,
  `sex_matcher.py:99-128`). The same run reports differently depending on which
  path fires; `rename_and_orient` sticks on `done (check)` forever via one path
  and `success` via another. This is the single most expensive structural defect
  and it is upstream of most of theme B.
- `ARCH-02` (critical) — `helpers.py` (937 LOC, 50 commits) holds seven
  unrelated responsibilities and sits at the centre of the dependency knot. It
  cannot be split until the cycles are broken, which fixes the ordering of
  Phase 2's first steps.
- **Layers are nominal.** All four packages import from each other; the graph is
  acyclic at runtime only because 28 step modules defer
  `from grit.core.click_cli import build_context` into function bodies and
  `helpers.py` defers step imports. Three structural cycle families
  (`click_cli ↔ steps.*`, `helpers ↔ steps.*`, `context ↔ registry ↔ helpers`).
  No test guards this.
- `TEST-02` (critical) — 147 `@patch` decorators target private module-level
  imports in 17 step modules, so the port's seam *is* the tests' seam. A ports
  refactor cannot land incrementally: 123 tests fail with `AttributeError` in one
  unreviewable commit.
- `TEST-01` (critical) — the whole execution seam (`_run`'s subprocess branch,
  `_submit_bsub`, `build_bsub_opts`, `_state_update_epilogue`, `_check_bjobs`)
  has **zero** tests. Nothing can distinguish a valid `bsub` line from a
  mis-quoted one, and there is no baseline to refactor against.
- `ARCH-03` / `CORR-10` / `CORR-13` — step identity duplicated across six
  hand-maintained registries in five files, already disagreeing: six tracked
  steps have no `STEP_MANIFESTS` entry (so `verify_outputs` returns
  `not_tracked` and `ARCH-01`'s recovery silently gives up), and `STEP_TO_STATUS`
  contains a phantom `agp_copied`. Adding a 22nd step means editing six lists
  and no test fails if you miss one.
- `ARCH-09` — the "one step pattern" is copy-paste, not an abstraction: no base
  class, 40 hand-written `tracker.start/finish` call sites, 28 byte-identical
  Click wrappers, 20 inline `if ctx.dry_run:` blocks. Every invariant is
  re-satisfied by hand in every file.
- `ARCH-04` — `status.py`'s 286-line `show_ticket_history` does Jira I/O,
  `bjobs` polling, registry **writes** and table rendering in one function.
  `grit status` is not read-only.
- `ARCH-05` — every step imports `build_context` from the CLI module, inverting
  the dependency direction and making the documented "usable from
  Python/notebooks" contract drag in `rich_click` and the whole command tree.
- `TEST-09` — no contract/conformance test and nothing that could seed one; a
  Phase-2 adapter has nothing to be verified against.

## P2 — correctness and hygiene, independent of Phase 2

- `ARCH-07` — four commands are allowlisted for `--dry-run` while containing no
  `dry_run` code at all, so `grit --dry-run haplotig-files` performs real
  filesystem writes on a path advertised as safe. `validate-files` is
  allowlisted, has a `_cmd`, and is commented out of the command tree: 151 LOC
  unreachable. *Verified directly: 0 `dry_run` hits in all four files.*
- `CORR-16` (`context.py:146`) — `read_type = "hifi" if pacbio_read_type else "hifi"`,
  a tautology. *Verified directly.*
- `CORR-14` / `PORT` — `_detect_assembly_type` can never return `paternal`, so
  every `paternal`/`maternal` branch in the codebase is dead code.
- `CORR-12` — `_run` captures stderr and discards it, so a failing farm tool
  reaches the curator as an exit code plus a Python traceback with the tool's
  own diagnostic lost. This is why debugging steps is expensive.
- `CORR-22` — `_run` sets no timeout anywhere.
- `DX-01` — `tests/local_smoke_test.sh` dies at line 66 under `set -euo pipefail`
  (it invokes three commands commented out of the CLI), so the regression check
  CLAUDE.md mandates for canonical-FASTA logic is unrunnable, and CI never runs
  it.
- `DOM-08` (plausible) — mtime is compared across files written by *different
  clocks*: synchronous steps stamp with the login host's, bsub'd steps with the
  compute node's. A few seconds of negative skew silently reverses pool order,
  and the run-dir ISO timestamps — which all come from one host — are never
  consulted.
- `DOM-07` (plausible) — `haplotig-files` touches empty hap-prefixed placeholders
  *into the `pretext_to_asm` run dir*, where both the re-glob and
  `find_canonical_haplotigs`' fallback prefer them over the real combined file
  beside them.
- `ARCH-16` — two commands bypass `_run()`, so "all shell commands go through
  `_run`" is not true; `cleanup` shells GNU-only `du -sb --apparent-size`, which
  silently renders every size as `?` off-farm.
- `ARCH-11` — `CurationContext` is documented as frozen and is a plain mutable
  dataclass; `hic_remapping.py:172` even carries a comment asserting the false
  premise.
- `CORR-20` — `except Exception: pass` swallows every parse error in the
  curation-results summary.
- `CORR-21` — the telomere track's awk program is mis-escaped.

## P3 — open-source readiness

**Security: the git history is clean.** 359 commits across all refs scanned for
password/passwd/secret/api_key/apikey/PRIVATE_KEY/credential — no credential
hits. No `.pem`/`.key`/`.env`/`.netrc`/`id_rsa` ever committed at any path, no
notebook ever committed. **No `git filter-repo` pass is required.** Stated
explicitly so the publication decision does not stall on an unfounded fear. The
credential surface is entirely outside the repo (whatever `GritJiraIssue` uses
for Jira, plus the implied MySQL behind the unused `pymysql`) and must be
audited separately before a split.

**Code blockers the author can fix:**
- `SEC-01` — `shlex.quote` appears zero times in 9,483 LOC of `shell=True`
  execution; `species` from Jira/YAML reaches the shell unquoted
  (`blast_contaminants.py:143`) or in weak double quotes
  (`find_reference.py:192`). Latent today; an RCE primitive against curators the
  moment a stranger can hand them a `--yaml`.
- `PKG-01` — `rename-and-orient` sourced from an unpinned git URL on a personal
  account via uv-only `[tool.uv.sources]`: unpublishable to PyPI, `pip install
  -e .` broken, and `uv.lock` pins `1.2.0` against a `>=1.2.2` constraint.
- `PKG-02` — four of five `MODULE_VERSIONS` keys resolve to a single
  *unversioned* internal Lmod module named `grit`, documented nowhere. An
  outsider who installs successfully still cannot run one real step.
- `ARCH-06` / `PORT-03` — ~14 hardcoded absolute tool paths outside
  `modules.py`, four inside individuals' home directories (`~mh6/decon_fasta`,
  `~mh6/remove_contamination_bed`, `~da16/*_buscos`,
  `~dz11/…birds_microchromosomes/*.py`). `UserConfig` has six fields and none
  covers tool or script locations, so there is no seam to move them into. The
  pixi plan underestimates this by roughly 4×.
- `PORT-02` — the epilogue embeds the submit host's own `argv[0]` as the
  compute-node path to `grit`, so completion detection works only when the grit
  installation is on a filesystem shared with compute nodes.
- `DOC-01` / `DOC-02` — the project's architecture documentation *is*
  `CLAUDE.md`; canonical resolution, the epilogue contract, `--untracked`
  semantics and the dry-run allowlist exist in human-facing form nowhere else.
  Nothing explains what genome curation is or what the pipeline does
  conceptually.

**Organisational decisions to escalate (not code):**
- No `LICENSE` of any kind. Sanger IP policy decision; gates everything else.
- Licence and ownership of the five `/software/grit/projects/vgp_curation_scripts/*`
  scripts — **unknown**, and two look like vendored copies of public GPL-ish
  projects, which carries its own obligations.
- Consent from `mh6` / `da16`, whose home paths become public, and provenance of
  the `~da16` sex-BUSCO ID lists.
- Whether disclosure of internal topology, the farm head hostname and three
  staff usernames is acceptable — if not, that is a history rewrite, not a file
  edit.
- Citability: no `CITATION.cff`, no Zenodo DOI. For a research tool this is an
  adoption blocker, not a nicety.
- Maintainer and support commitment.

**Two hidden *data* dependencies matter more than any code:** an unnamed BLAST
`nt`-class database buried inside `~mh6/…/decon_fasta` (invisible from source —
grit only ever sees the resulting `taxonomy.txt`), and the `~da16` BUSCO ID
lists. Neither can be published or silently reproduced.

**One seam has no substitution point at all:** `post_process_rc`
(`post_processing.py:17,50-68`) is a **shell alias** defined by a sourced Sanger
conf, invoked via `shopt -s expand_aliases`. No binary, no path, no module key —
and it gates a ticket's `done` state.

## Orchestration verdict

**Stay on vanilla Python. The decision is not close.**

The hypothesis was confirmed by the code: grit has no DAG, no "run the pipeline"
entry point (`post_curation.py:36-44` is a three-line straight-line call),
dependencies are resolved at call time by `find_canonical_fa()`
(`helpers.py:425`) rather than by graph edges, canonicality is a runtime
`max`-by-mtime over a pool of mutually substitutable producers, and the branch
conditions in `recuration-canonical-priority.md` are questions only a human can
answer. Every candidate engine's core competence — drive a DAG to completion and
terminate — is the part of the problem grit does not have.

Decisive axis: operational requirements × human-in-the-loop, jointly. Either
alone is survivable; together they eliminate everything. Airflow 3 requires a
metadata DB + scheduler + API server; self-hosted Temporal is a four-service
cluster on Cassandra/Postgres via Helm. Nextflow passes the operational axis
easily (single binary, 15+ executors) but fails human-in-the-loop structurally:
there is no primitive for "exit here, a human curates for three days on their
laptop". The Snakemake LSF plugin's own page states it is not maintained or
reviewed by the Snakemake organisation — for the one scheduler grit runs on.

Estimates: stay + write the executor port, **2–4 person-weeks** (+3–5 for the
borrowed patterns). Full Nextflow port 14–22 pw, and the registry, `RunTracker`,
canonical resolution and the CLI would still be hand-maintained because no
engine models them. Snakemake 12–18, Dagster 20–32, Airflow 22–32, Temporal
25–40. Test coupling (~30%) adds +3–5 pw uniformly and does not change the
ranking.

**The class-D hybrid is already the de-facto architecture** — `hic_remapping.py:99-116`
invokes the Nextflow pipeline `curationpretext`. (Corrected 2026-09-03: report 07
also credited `find_reference.py` with this; it does not. `curationpretext`
appears in `grit/` only in `hic_remapping.py`, plus a comment in `status.py` and
the config template — verified by grep. `find_reference.py`'s whole Sanger
surface is two small internal executables: `get_nearest_comparator.rb` at
`find_reference.py:25` and the `reheader` tool loaded via `module_cmd('GRIT')`,
which makes it easier to port than assessed.) Phase 2
should declare it intentional in CLAUDE.md: engines own within-step data flow,
grit owns between-step human sequencing.

**Patterns to borrow instead of migrating** (each fixes a real defect above):
1. Nextflow-style executor contract, four verbs (submit/status/kill/workdir),
   **with completion detection inside the contract** — today it is welded to
   `-Ep` plus a `bjobs` sweep, and a `SlurmExecutor` has neither. That seam, not
   the abstraction, is Phase 2's real risk.
2. Snakemake-style unified rerun triggers (`input`/`params`/`software-env`).
   There are currently five different hand-written staleness checks, and a
   `MODULE_VERSIONS` bump invalidates **nothing** — a correctness gap, not a
   convenience one.
3. Dagster-style named asset + explicit `supersedes` edge in the tracker. Making
   "the hap1 FASTA" an asset with multiple possible producers turns the pool
   (hardcoded three times in `helpers.py`) into data, and an explicit
   supersession edge would have *prevented* `143f425` rather than patching
   around it.
Plus two to schedule regardless: transactional state (a per-ticket append-only
JSONL fits the existing fold-forward reader) and retry/backoff.

## Canonical policy verdict

**The mtime-pool design is sound. Keep it.** Every priority-list design encodes
an assumption about *order of intent* that a curator is free to violate — which
is exactly how the earlier designs broke when chaining forward from recurate.
"Freshest tracked output for this haplotype wins, uniformly, with `untrack` as
the one escape hatch" is a rule a curator can hold in their head, and the
tie-break is deterministic (first-listed step, verified). The defects are in the
policy's **inputs**: what counts as a step's current output, and what counts as
finished. Phase 2 should not redesign the rule.

## Test-suite verdict

The feared failure mode is **not** present. 48 of 451 tests (10.6%) assert on
command or option strings; `module load` is touched by 2 assertions out of 839.
Per file: 20 behaviour-oriented, 5 mixed, 3 string-oriented. A ports refactor
turns ~123 tests red, but ~102 of those break purely on the `@patch` target, not
on any assertion about LSF; only ~21 assertions in 10–12 tests encode real LSF
semantics, and rewriting those is desirable anyway. Worst offenders:
`test_bsub_ram_override.py` (100% LSF-flag), `test_post_curation.py`,
`test_rename_and_orient.py`, `test_find_reference.py` (hardest — production
offers no seam but the shell string).

Shape: **well-tested pure core, unexamined boundary.** Right way round, but
Phase 2 lives on the boundary. `test_helpers_canonical.py` (26 mock-free tests
against real registry/tracker/files), `test_run_tracker.py`, `test_registry.py`
and `test_result_parsers.py` are good work at the right altitude and survive the
refactor untouched. Highest value-per-effort CI gate available: a type checker,
against the existing ~75%/77% annotation coverage that nothing currently
enforces.

## Preserve through Phase 2

Explicitly listed so a refactor does not destroy them:

- `CurationContext` as an explicit value object — all 21 steps take it first,
  zero module-level mutable state, derivation centralised in `from_yaml`, and
  `gritjiraissue_module` is already a real (if undocumented) injection seam.
- `RunTracker.start/finish` handling `print_only` internally, so a step cannot
  pollute the registry in preview mode even if it forgets a guard — the
  invariant is enforced at the right layer.
- The `bsub -Ep` epilogue *concept*. The semantics are right for fire-and-forget
  HPC; the fallbacks are what is broken.
- `MODULE_VERSIONS` / `module_cmd()` — a clean, complete abstraction, and the
  model the rest of the site-specific configuration should follow.
- `--print-only` and `--dry-run` as onboarding affordances: `grit --help` works
  with no config at all, and `--dry-run` lets a stranger drive the whole
  pipeline on a laptop. Unusually strong for a tool of this kind. (README
  currently mislabels `--print-only` as "Dry run" next to the real flag.)
- `collect_outputs()` / spec tuples — sound mechanism; only registration and
  call sites are the problem.
- `utils/output.py` + `utils/result_parsers.py` — the display/logic split
  `status.py` should have had.
- Release discipline: accurate Keep-a-Changelog `CHANGELOG.md` with six matching
  tags.
- `recuration-canonical-priority.md` as a genuine human-facing design doc.
- CLAUDE.md's candour: it documents the epilogue's limitation, the `untracked=`
  footgun and the `validate-files` gap rather than hiding them. Most drift found
  here is in areas it does *not* claim.

## Inputs Phase 2 must decide (not decided here)

1. **Which steps are in the public core.** This determines how much of the
   ToolProvider and ReleaseTarget ports needs designing at all. Realistic core:
   `setup`, `pretext-to-asm`, `haplotig-files`, `hic-remapping`,
   `fastga`/`fastga-synteny`, `rename-and-orient`, `super-to-scaffold`, `qv`,
   plus the whole tracking and canonical-resolution engine.
   Sanger-distribution-only until their dependencies are re-implemented or
   released: `blast-contaminants`, `sex-matcher`, `find-reference`, the
   microchromosome pair, `post-processing`.
2. Whether P0 lands before or alongside the ports work. The registry and the
   verification themes are independent of the split and could ship first.
3. How the cycles are broken, since `helpers.py` cannot be split before that.
4. Whether the test seam moves to injected collaborators before the ports land,
   given `TEST-02`.
5. Distribution shape: two packages in one repo with entry points, or two repos.
6. Is `~/.grit/` shared with compute nodes. Settle this first; it is one command
   and it changes the registry design.

## Verified directly (not taken on an agent's word)

`CORR-01` `_load` → `[]` and `_save`'s shared `.tmp` path; `CORR-03`
`state_update_cmd` passing LSF status through without downgrading on empty
outputs; `sex-matcher.sh` ending in `exit 0`; `ARCH-07` zero `dry_run`
occurrences in all four allowlisted modules; `CORR-16` the `"hifi" if x else
"hifi"` tautology; `CORR-05` the unsorted `glob.glob(agp_pattern)`. Also
observed in passing: `registry.py:296` calls `tracker.finish(...)` without
`untracked=`, consistent with `DOM-04`.

Working tree was unchanged by the audit (`HEAD` = `9175121`, `git status` clean
apart from the new report directory).
