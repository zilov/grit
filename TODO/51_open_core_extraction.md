# TODO 51: open-core extraction — target architecture, decisions, roadmap

Phase 2 design. Consolidates `TODO/claude/phase2/A|B|C` into one coherent target
and a sequence to get there. Phase 1's assessment is `TODO/49`; the remediation
queue is `TODO/50`.

Nothing here is implemented. This document is the thing to argue with before
code moves.

**Status: paused (2026-09-03).** Open-sourcing is not currently planned, so this
phase is not being executed. It is committed because the analysis behind it —
the port contracts, the seam inventory and the per-step capability work — stands
on its own and would be expensive to redo. Batches in `TODO/50` that were
deferred *into* this phase come back into that queue while it is paused; in
particular Batch 6 (collapse the four reconcile implementations, one step
registry) was moved here only because a non-LSF executor needed completion
detection inside the executor contract, and with no such executor planned it is
an ordinary refactor again.

## Problem

`grit` works, and only at Sanger. The goal is a public `grit` that a genome
curator anywhere can install and run, without losing anything the Sanger team
depends on today. Phase 1 found the architecture sound and the mechanisms inside
it first drafts; Phase 2 decides the shape those mechanisms take.

## Settled inputs (do not relitigate)

From Phase 1, with evidence in `TODO/49`:

- **Vanilla Python is kept.** No workflow engine. grit has no DAG, no run entry
  point and no scheduler because the problem has none; every engine's core
  competence is the part of the problem grit does not have. Verdict was decisive
  (report 07), estimates ranged 12–40 person-weeks against 2–4 for the executor
  port.
- **The mtime-pool canonical policy is kept** (report 06). Its defects are in its
  inputs, not the rule.
- **The `TODO/49` preserve list survives.** Ports agent checked each item
  explicitly; two are modified deliberately and named in ADR-06 and ADR-04.

Decided during Phase 2:

- **The public core is all 21 steps** (`TODO/50` § Scope decision). Sanger-only
  dependencies are substituted, not fenced off.
- **ToL naming conventions stay in core, as data with profile override**
  (author, 2026-09-03). What is site-specific is the *roots* those conventions
  hang off, and those are settings.
- **Rerun triggers are hybrid:** content hash for small inputs (AGP, chromosome
  lists, configs, tool versions), mtime+size for multi-GB assemblies (author,
  2026-09-03).
- **Preflight blocks, with an explicit `--skip-preflight` escape** (author,
  2026-09-03).
- **The supersession edge is rejected; the pool becomes data** (consolidation).
  Report C proposed recording a `supersedes` edge on the run record and was
  itself least confident about it: it introduces derived state that can disagree
  with the live filesystem, and its "warn when the rule now resolves older than
  the last edge" behaviour was inferred rather than read off a finding. The
  pool-as-data half delivers the value — the rule stops being hardcoded three
  times (`helpers.py:425/:477/:563`) — without that risk. Revisit only if
  backwards-canonical recurs after `DOM-01` is closed.

## Target architecture

### One-way dependencies, enforced by a test

```
grit/cli/        composition root — the ONLY module that constructs adapters
    │
    ▼
grit/steps/*     step functions + StepDecl; take ctx, call ctx.env.*
    │
    ▼
grit/domain/     reconcile, canonical resolution, RunTracker, step catalog,
                 fingerprints, release planning
    │
    ▼
grit/ports/   ◄──  grit/adapters/   lsf/ local/ slurm/ lmod/ path/ container/
 (stdlib only)                       jira/ yamlfile/ tol/ sanger_release/
```

Rules, checkable by one import-linter/AST test that nothing guards today:
`ports/` imports nothing from `grit/`; `adapters/*` imports `ports/` only;
`domain/` imports `ports/` only; `steps/*` imports `ports/` and `domain/`, never
`cli/` and never another step module; `cli/` may import everything.

Today all four packages import each other, and the graph is acyclic at runtime
only because 28 step modules defer `from grit.core.click_cli import
build_context` into function bodies. Each cycle family is broken by a specific
port — see ADR-02. `helpers.py` (937 LOC, seven responsibilities) can only be
split after all three are broken, which is why the ports fix the ordering.

### The single seam

`CurationContext` gains one field, `env: Environment`, holding the five
adapters. Steps reach the environment through `ctx`, never by module-level
import. This preserves `CurationContext` as the project's one injected value
object — Phase 1's best existing abstraction — and it is simultaneously the
answer to `TEST-02`: the tests' seam becomes `ctx.env.*` instead of 147 private
module attributes.

---

## Decisions

### ADR-01 — grit stays a CLI over an engine-free core; the hybrid is declared intentional

`hic_remapping.py:99-116` already invokes the Nextflow pipeline
`curationpretext`. That is the architecture, not an accident: **engines own
within-step data flow; grit owns between-step human sequencing.** Record it in
`CLAUDE.md` so the next person does not "fix" it. Patterns are borrowed from
Nextflow/Snakemake/Dagster instead of migrating to them (ADR-03, ADR-12,
ADR-14).

### ADR-02 — ports and adapters, five ports, injected through `ctx.env`

Five ports: `ExecutionBackend`, `ToolProvider`, `MetadataSource`,
`StorageLayout`, `ReleaseTarget`. A sixth candidate collapsed (ADR-05) and two
were rejected (ADR-15).

Cycle-breaking is a property of the ports, not extra work:

| Cycle | Broken by | How |
|---|---|---|
| `click_cli ↔ steps.*` (×21) | MetadataSource | `build_context` exists only because context construction needs the Jira fetch. Once metadata is a port, the context is constructible without any CLI type; `build_context` moves to `cli/` and `ARCH-05` closes with it |
| `helpers ↔ steps.*` | StepDecl + StorageLayout | resolvers and reconciler stop importing step modules for `_OUTPUT_SPECS`; they read an injected `StepCatalog` passed *down* |
| `context ↔ registry ↔ helpers` | ExecutionBackend + StorageLayout | reconcile leaves `registry` for `domain/`; the tracker becomes part of `Environment` |

### ADR-03 — `ExecutionBackend` owns completion detection

Verbs: `submit`, `poll`, `kill`, `job_workdir`, `render` (+ `describe_failure`).
`render` is a fifth verb beyond report 07's four, justified solely by preserving
`--print-only` — which then doubles as the equivalence check for the whole
migration (see Roadmap).

`submit` takes a scheduler-neutral `JobSpec` plus a `CompletionHook` that is
**pure data, never a shell string**. Each adapter declares
`completion_modes ∈ {SYNCHRONOUS, CALLBACK, POLL_ONLY}` and
`requires_shared_install`. The LSF adapter renders `-Ep` from a
**constructor-supplied launcher argv, never `sys.argv[0]`** — that is how
`PORT-02` (the epilogue only works when grit is on a filesystem shared with
compute nodes) becomes a declared, preflight-checkable requirement instead of a
hidden assumption. The local adapter reconciles in-process. A Slurm adapter
declares `{CALLBACK-in-payload, POLL_ONLY}` honestly.

The contract-level split of `FORGOTTEN` / `UNKNOWN` / raised
`BackendUnavailable` kills `CORR-04`: a `bjobs` outage can no longer look like
"the job vanished".

`poll` is **read-only by contract**. That is what makes `grit status` stop
writing to the registry (`ARCH-04`).

### ADR-04 — reconcile-once, enforced structurally

One function, `grit/domain/reconcile.py::reconcile(decl, run, tracker, *,
evidence, untracked)`. Callers supply **`Evidence`** (a `JobStatus`, a local exit
code, or `probe_only`) and **never a verdict**. One table maps (job state ×
outputs) to a terminal status:

| Evidence | Outputs complete | Outputs empty/partial |
|---|---|---|
| `SUCCEEDED` / exit 0 | `success` | **`failed`** — never success |
| `FAILED` / non-zero | `failed` | `failed` |
| `FORGOTTEN` | `success` | `failed` |
| `UNKNOWN` / `BackendUnavailable` | `unchanged` | `unchanged` |
| `probe_only` (externally scheduled) | `success` | `unchanged` |

Row 1 right is `CORR-03`. Row 4 is `CORR-04`. Row 5 keeps
`hic_remapping`/`curationpretext` from being called failed while still running.
`untracked` is honoured in exactly one place, which is the bug from
`TODO/tiny.md` that currently has to be fixed at 40 call sites by hand
(`DOM-03`, `DOM-04`). `reconcile` is idempotent, which is why the port needs only
at-least-once callback delivery.

**Why a fifth path cannot grow:** `RunTracker.finish` becomes domain-private and
an AST test scans `grit/` for `.finish(` outside `reconcile.py`; steps have only
two available shapes (`SCHEDULED` → `ctx.env.exec.submit`, or `SYNCHRONOUS` →
`reconcile(evidence=Evidence(local_exit=rc))`), so there is no third shape in
which a step could write a terminal status itself. This also deletes CLAUDE.md's
documented footgun that a synchronous tracked step must remember its own
try/except or strand the record forever.

**Deliberate modification to the preserve list:** steps lose the right to call
`tracker.finish`. `start`/`finish` still enforce `print_only` at the same layer,
so the preserved invariant is unchanged; what changes is who may call it, and
that restriction is the mechanism.

### ADR-05 — capability declaration is data, not a port

`StepDecl` — outputs, output location, completion kind, required tools, required
data, traits, status label, rerun triggers, dry-run support — read by ports 1/2/4.
It has no alternative implementation, so it is not a port.

It **deletes all six duplicated step registries and `STEP_MANIFESTS` outright**
(`ARCH-03`, `CORR-10`, `CORR-13`), and with them `core`'s `elif step ==
"sex_matcher":` branch and the three different assumed locations for that step's
output (`ARCH-19`).

`preflight()` runs **before `tracker.start()`**, so a blocked step leaves no
record at all. Per the author's decision it **blocks**, with `--skip-preflight`
for cases where the check itself is wrong (a module that only loads on a compute
node). Surfaced via `grit doctor`, a `--check` flag, static `--help` text and a
status column. This is what turns `sex-matcher`'s `exit 1` on an unrecognised
ToL-ID prefix into a sentence a curator can act on.

### ADR-06 — `ToolProvider` returns a `Provision`, not a string

Verbs: `resolve`, `check`. `Provision.preamble` is a **tuple of statements**,
joined by one domain `compose()`. This fixes `PORT-19` by arity rather than by
value: a backend needing no preamble returns an empty tuple and simply vanishes,
instead of producing a command starting `" && …"`.

`Provision.versions` is mandatory (concrete, or the literal `"unpinned"`),
because it is the `software-env` rerun trigger (ADR-12). The 14 hardcoded tool
paths outside `modules.py` and the escaped `module load fastga/1.1-c1` pinned
inside a bundled shell script become `ToolRequirement`s; a grep test bans
provisioning verbs from `grit/scripts/**`.

**`compose()` is the single home for `shlex.quote`.** Agents B and C reached
this independently. It means `SEC-01` (zero uses of `shlex.quote` in 9,483 LOC of
`shell=True`) and `ARCH-08` (correct quoting as the caller's unwritten
obligation) stop being separate tasks and become properties of this port.

**Deliberate modification to the preserve list:** `module_cmd()`'s return type
changes from `str` to `Provision`. The preserved property is the *shape* — one
logical key, one line per tool version — kept as the Lmod adapter's config table.
The string return is the defect itself and cannot be preserved.

### ADR-07 — `MetadataSource`, and `from_yaml` becomes the primary constructor

One verb: `fetch(ticket) -> TicketMetadata`. `from_ticket` dissolves into two
composition-root lines. The Jira adapter owns `sys.path`, `customfield_11650`
and `gritjiraissue_path` — which retires `context.py:237-239` and removes
`gritjiraissue_path` from core's required config (`PORT-08` closes as a side
effect). `teloseq` becomes a motif rather than a CLI fragment, closing
`PORT-07`.

Consequence worth stating: the Jira-free path stops being "a testing aid" and
becomes the default. That is what makes `--dry-run` a genuine onboarding route
for an outsider rather than an internal convenience.

### ADR-08 — `StorageLayout` stays narrow; ToL conventions live in core as data

Seven pure functions covering anchoring paths, release filenames, haplotype
roles/aliases and taxonomy. It deliberately does **not** own step output specs
(those are `StepDecl`) or file-format grammars (those stay in
`result_parsers.py`) — that restraint is what keeps it from becoming a
34-method god object.

`workdir()` becomes **total**: no `ValueError` when `assembly/draft` is absent
(`PORT-09`), so the ToL directory convention becomes a default rather than a
precondition. `classify()` returns `Optional[Taxon]` from a prefix table, so
taxonomy-from-identifier becomes data instead of control flow (`PORT-11`).
`deposit_dir` may never return a glob.

Per the author's decision, `SUPER_`/`SCAFFOLD_` naming, the
`hap1/hap2 ↔ primary/alternate` alias table (currently duplicated five times,
with the fifth copy omitting `paternal`/`maternal`) and the chromosome-list
grammar stay in core: they are load-bearing in every step's `_OUTPUT_SPECS`, and
moving them to a site package would move half the step code with them,
contradicting the scope decision. What moves to the profile is the *roots* —
`/nfs/treeoflife-01/…`, the `assembly/draft` → `working` rewrite.

### ADR-09 — `ReleaseTarget` may never fabricate an artifact

Verbs: `validate`, `publish`, `finalize`. A `ReleasePlan` must be complete and
validated **before the first `cp`**, and `publish` is atomic. That structurally
removes `finalize_qc`'s warn-and-continue on a missing canonical FASTA and its
empty `touch` of missing haplotigs (`CORR-06`) — they become impossible rather
than fixed.

`finalize` is the documented `post_process_rc` placeholder. The reference adapter
returns `skipped` and **does not mark the ticket done**. Three unknowns are
recorded, not invented (§ Escalations).

`validate()` is where Batch 5's coherence rule lands (`DOM-05`) — which is why
this port is sequenced last: it cannot be written before the policy question
"which fa/chr pairs are legal" is answered.

### ADR-10 — one repository, two distributions

`grit` (all 21 steps, all generic adapters, profile machinery, built-in
`local`/`generic-lsf`/`generic-slurm`) and `grit-sanger` (the `sanger` profile,
the `GritJiraIssue` adapter, the ToL release target, the path/module/queue
table), as a uv workspace: `src/grit/` + `packages/grit-sanger/`.

One repository because a sole maintainer cannot afford two PRs for every
cross-cutting change. Two distributions rather than one package with a
`[sanger]` extra because an extra cannot be withheld, and the disclosure
decision is not the author's to make.

**Revisit trigger:** if Sanger's disclosure answer is permissive, one package
with an extra becomes defensible. This is cheap to revise *before* the ports
land and expensive after — so decide it at M2 at the latest.

### ADR-11 — site profiles via entry points

Group `grit.site_profiles`, value = a **zero-argument factory returning a
`SiteProfile`** whose five adapter slots are themselves callables. Discovery
reads metadata only; `.load()` happens once, for the selected profile, inside
`build_context()`. pytest's eager `pytest11` import is the named anti-pattern;
JupyterHub's `jupyterhub.spawners` is the model.

Selection precedence: `--profile` > `GRIT_PROFILE` > config key > **the single
installed non-built-in profile** > `local`. That fourth rule is the only magic in
the design and it exists so today's curators' configs keep working untouched.
Auto-detection rejected. Comma-composed profiles rejected (Nextflow's
declaration-order-vs-CLI-order pitfall, fixed only in 25.04).

Profiles live both packaged and as pure-config `~/.grit/profiles/<name>.yaml`
with a `base:` key.

### ADR-12 — rerun triggers: hybrid fingerprint

Home: `StepDecl.rerun_triggers` + a `RunFingerprint` on the run record. Replaces
five different hand-written staleness checks (`hic_remapping.py:44-84` vs
`fastga.py:199-203` and three others).

Per the author's decision: **content hash for small inputs** — AGP, chromosome
lists, configs, and `Provision.versions` — and **mtime+size for multi-GB
assemblies**, so no `grit status` reads a genome off NFS. Hashing the AGP is what
closes `DOM-09`, where a `cp -p`/`rsync -a` of the AGP makes grit print "Already
done", run nothing, and write no tracker record. Which input falls in which class
must be documented per step, since two rules are harder to reason about than one.

Note this also closes a correctness gap Phase 1 named: today a `MODULE_VERSIONS`
bump invalidates **nothing**.

### ADR-13 — preflight blocks

Per the author's decision, a missing tool or dataset stops the step before
`tracker.start()`, prints what is required and how to obtain it, and leaves no
record. `--skip-preflight` exists for when the check is wrong. Rationale: it
matches the line the whole assessment takes — better not to start than to strand
a record in `started` or write a false `success`.

### ADR-14 — the canonical pool becomes data; no supersession edge

The mtime-pool rule is untouched. Its three hardcoded pools become one asset
table read by one generic resolver. The supersession edge report C proposed is
**rejected** — see § Settled inputs for the reasoning. `recuration-canonical-priority.md`
gets one edit describing the pool as a table, plus the `DOM-15` honesty pass
(documenting how the answer can be wrong) that Batch 5 owns.

### ADR-15 — `RegistryStore` is not a port

It has one implementation at a time, so it is a remediation decision, not a
portability axis. The registry's storage shape (per-ticket append-only JSONL vs
locking) stays an ADR in `TODO/50` Batch 2, informed by the now-confirmed fact
that `~/.grit/` is shared across every login and compute node over NFS — which
makes `flock` unattractive and JSONL likely.

Also rejected: a separate `JobRenderer` (folded into `render`), a `Notifier`
port (the only "Jira write" is a printed reminder → `receipt.followups`),
splitting `NamingConvention` out of `StorageLayout`, `Clock`/`Filesystem` ports,
any job-dependency verb (grit has no DAG), and `JobSpec.blocking`/`-K`
(declared, no caller).

### ADR-16 — dependencies and publication channels

`rename-and-orient` is **not a Python dependency**: it is only ever
`shutil.which`'d (`rename_and_orient.py:77`, verified). Delete it from
`[project.dependencies]` and `[tool.uv.sources]` and move it to the
`ToolProvider` table — which fixes all three `PKG-01` symptoms at once
(PyPI-unpublishable, broken `pip install -e .`, lock/constraint mismatch).

Drop `pymysql` and `requests` (zero imports each, verified). **Keep
`biopython`** — report B recommends dropping it, and that is wrong: it is used at
`grit/scripts/busco_synteny_format_and_plot.py:22`. Open sub-question: if
`grit/scripts/*` always runs under the farm tool environment rather than grit's
own interpreter, `biopython` belongs in an extra.

PyPI first, bioconda (`noarch: python`) second. The evidence is two-tiered: the
*tools* are on bioconda (pretextmap/graph, gfastats, fastga, merqury, yahs) but
the *orchestration* tier is not — PretextView, curationpretext, and
`agp-tpf-utils`, which sanger-tol itself installs via `pixi add --pypi` from a
git URL. Keep manual `version =` + Keep-a-Changelog and gate it in CI; reject
hatch-vcs; Trusted Publishing gives PEP 740 attestations free.

### ADR-17 — CI, including how to test a profile CI cannot see

Five jobs: pinned 3.10–3.13 matrix + macOS; build-and-`pip install`-the-wheel
asserting `grit --help` works with **no config and no profile installed**; the
`local` profile driven end-to-end via subprocess under `--dry-run` with `HOME` in
a tmpdir (this converts the currently-broken `local_smoke_test.sh` dry-run
section into pytest); **cross-profile `--print-only` golden files** as the way to
exercise the Sanger profile from a runner that cannot see Sanger; a ratcheted
mypy baseline against the existing ~75%/77% annotation coverage.

The golden-file job must ship with an explicit statement of what it does *not*
prove — it checks command construction, not that the command works — covered by
capability declarations (`grit doctor`) and a manual farm checklist in
`RELEASING.md`. The conformance suite lives in `src/grit/testing/` as plain
importable classes, **not** a pytest plugin.

### ADR-18 — documentation and repository hygiene

`CLAUDE.md` keeps its name and loses its architecture-documentation role to
`docs/design/`. `recuration-canonical-priority.md` and the cited `TODO/done/44`,
`45`, `46` are promoted to `docs/design/` in English. The pixi draft is retired.

**`TODO/49`, `TODO/50` and `TODO/claude/assessment/*` stay internal until the
disclosure question is settled — they are now the most complete map of Sanger
internal topology in the repository.** We produced that map; it should not be the
thing that leaks.

`.gitignore` gains `.claude/`, `.superpowers/`, `dist/`, `.venv/`, `*.egg-info/`
(nothing is currently tracked, but only one machine's `.git/info/exclude` is
holding).

---

## Capability parity

All 21 steps are public core, so every Sanger-internal dependency is substituted.
Full table and evidence in `TODO/claude/phase2/A_capability_parity.md`.

Author's answers, 2026-09-03, folded in:

| Step | Kind | Replacement |
|---|---|---|
| `blast-contaminants` | **reimplement (M), no behaviour change** | **Database identity settled: `core_nt`, held in RAM at Sanger for speed.** So `decon_fasta` is `blastn` against `core_nt` plus a taxonomy join, and a public reimplementation reproduces today's results exactly — this stops being a swap with a comparability caveat. RAM-residency becomes a profile setting (`db_location: shm | disk`), giving the "local mode" the author asked for. ASCC and FCS-GX drop to **opt-in alternative tiers**, not the default. `remove_contamination_bed` → `seqkit grep -v -f` (exact). Lineage script → NCBI Datasets/taxonkit |
| `sex-matcher` | **recover-data, resolving on its own** | The four BUSCO ID lists **will be published**. So: declare them as a required data dependency (ADR-05), point the public default at the published URL once it exists, and have the `sanger` profile point at the NFS path until then. No regeneration, which removes the "marginal calls change" risk entirely. `sex_matcher.py` ≈30 lines; BUSCO from bioconda with a **pinned** lineage |
| `find-reference` | reimplement ×2, **algorithm recovered not guessed** | The author can supply `get_nearest_comparator.rb`'s source, and agrees Ruby is not worth keeping — so the selection heuristic gets **read and ported**, rather than replaced by a new rule. That removes report A's stated risk that "nearest" would rank differently from an undocumented heuristic. `reheader` ≈20 lines |
| `microchromosome-second-shot` | vendor + **author refactors the script** | It currently submits its own `bsub -K` internally, which is invisible to the executor seam. The author will adapt the script for open source, so the embedded LSF calls get lifted out at the source rather than worked around |
| `microchromosome-combine` | vendor (S) | pure file-merge CLI |
| `post-processing` | **Sanger-only — the one exception to the scope decision** | Stays Sanger-only for now (author). The design already accommodates this without special-casing: `finalize`'s reference adapter returns `skipped` and does not mark the ticket done (ADR-09), while `grit-sanger` implements the real thing. The 12 questions in report A stay open but block nothing else |

Licence findings: `ragtag_paf2delta.py` is RagTag's, **MIT** — the feared GPL
obligation does not exist. `DotPrep.py` is MIT (`dnanexus/dot`), vendor with
notice. `dgenies_index.py` **does not exist in D-GENIES upstream**, so its
provenance is genuinely unknown — reimplement the index (~15 lines) and sidestep
GPL-3.0 entirely. `pretext-to-asm` resolves to the public MIT
`sanger-tol/agp-tpf-utils` and is **not** a blocker.

### The product constraint, stated rather than averaged away

12 steps are outsider-runnable on code fixes alone; 3 more after a single-GB
public download; `microchromosome-second-shot` and `hic-remapping` need a real
cluster; `post-processing` is Sanger-only by decision; and `blast-contaminants`
needs **~220 GB of storage for `core_nt`**, which is the floor for reproducing
today's screening. `sex-matcher`'s gate is dissolving on its own once the BUSCO
lists are published.

Two refinements the author's answers make possible. First, **RAM-residency is a
performance choice, not a requirement**: Sanger keeps `core_nt` in RAM for speed,
and an on-disk mode is a profile setting, so the step degrades in *speed* rather
than in *capability* off-farm. Second, because the database is `core_nt` rather
than something unnamed, **today's runs are reproducible and the public path
produces the same answers** — provided the `core_nt` release is pinned, which it
is not today.

The README must still say the 220 GB part. "All 21 steps work outside Sanger" is
true with two sentences attached: this step assumes a large public database, and
`post-processing` is Sanger-only.

One live finding, now pointing the other way: the author's workspace contains an
ASCC/FCS-GX/sourmash-vs-HiC benchmark showing FCS-GX at sensitivity 0.41 /
precision 0.99 on one sample. Given that the current path is `blastn`+`core_nt`,
that number is an argument **against** promoting FCS-GX to the default — it would
remove a different set of scaffolds than curators expect. Keeping `core_nt` as
the default and FCS-GX as an opt-in tier is both the cheaper and the more
conservative choice. The sourmash line remains the only plausible route to a
laptop-scale screen (a signature database is orders of magnitude smaller than a
nucleotide one); still research, not a design input.

---

## Roadmap

Strangler fig: ports are introduced beside the existing code, steps move one at a
time, `--print-only` goldens are the equivalence check throughout. Each milestone
is one stacked feature branch per the project's gitflow.

**M0 — safety net.** `TODO/50` Batch 1 + `CORR-01`. Non-negotiable prerequisite:
no port implementation begins until the execution seam has tests and
`local_smoke_test.sh` runs in CI. Also `--dry-run`'s four lying allowlist entries
(`ARCH-07`) and stderr surfacing (`CORR-12`).

**M1 — correctness on production tickets.** `TODO/50` Batches 2–5. Independent of
the ports; they act on live tickets today, so they should not wait for a design.
Batch 3 (`CORR-03`) must precede Batch 4, since it deactivates `DOM-01`'s
trigger. Batch 5's policy answer — which fa/chr pairs are legal — is an input to
ADR-09.

**M2 — Port 1 + reconcile-once.** Together, never sequentially: writing reconcile
against `bjobs` first means writing it twice. Commit shape below. Decide ADR-10's
revisit trigger by the end of this milestone.

**M3 — StepDecl + step catalog.** Second, because `reconcile`'s output probe needs
one source of truth, and because it deletes six registries whose drift would
otherwise have to be carried through every later port.

**M4 — Port 2 (ToolProvider), then rerun triggers.** 12 sites, self-contained.
Must precede the trigger work because the `software` fingerprint comes from
`Provision.versions`. `shlex.quote` lands here (ADR-06).

**M5 — Port 3 (MetadataSource).** Small, and it breaks the `click_cli ↔ steps`
cycle that every later refactor benefits from.

**M6 — Port 4 (StorageLayout).** Deliberately late: the `glob.glob` +
`find_canonical_*` patches are the largest test-coupling cluster (~60
decorators) and migrate far more cheaply once `mock_ctx.env` exists and the
resolvers already read an injected catalog.

**M7 — Port 5 (ReleaseTarget).** Last, because `validate()` depends on M1's
policy answer.

**M8 — packaging split, profiles, publication.** ADR-10/11/16/17/18, plus
`TODO/50` Batch 7. Gated on the organisational answers, which is why the
conversations start now rather than here.

**M9 — capability parity implementation.** Per-step substitutions from the table
above. Can overlap M4–M7 per step, since each is independent; `post-processing`
is blocked on Sanger answers indefinitely and must not block anything else.

Only after M2–M6 can `ARCH-02` (split `helpers.py`) proceed.

### Per-port commit shape (how `TEST-02` is respected)

Each port lands as **A → one B per step module → C**:

- **Commit A — the port exists, nothing uses it.** Protocol + value objects in
  `ports/`; today's behaviour implemented as the site adapter, no behaviour
  change; composition root defaults to it; **the conformance suite**; and
  `mock_ctx` extended with a recording `FakeEnvironment`. No production call site
  changes, no existing test changes. Green by construction.
- **Commits B₁…Bₙ — one step module each**, replacing that module's private
  imports with `ctx.env.*` **and** migrating that module's tests in the same
  commit. Two files, one reviewer, green at every commit.
- **Commit C — delete the old free functions** (`_submit_bsub`,
  `build_bsub_opts`, `_check_bjobs`, `_state_update_epilogue`, `module_cmd`) and
  add the AST test that stops them coming back.

Two hard constraints: **the baseline lands in commit A** — the conformance suite
plus a `--print-only` golden snapshot for every step, captured before the first B
commit and diffed after each; and **reconcile-once lands with Port 1**.

The test migration is strictly an improvement, not a tax: assertions move from
"a private function was called with this string" to "a job was requested with
these semantics". Of ~123 tests that go red, ~102 break on the patch target
alone; only ~21 assertions in 10–12 tests encode real LSF semantics, and those
were worth rewriting anyway.

---

## Escalations (start now — long latency, blocks M8)

- **LICENSE.** Sanger IP policy. Gates publication and nothing else — every other
  milestone proceeds without it.
- **Repository location.** Currently a personal account; `sanger-tol` is the
  natural home and changes the governance conversation.
- **May `grit-sanger` be published at all**, and is the internal topology in
  *history* publishable? If not: a fresh repository from one squashed commit, not
  `filter-repo` over 359 commits. Carry the verified fact that the history is
  **clean of credentials** into that conversation.
- **Consent from `mh6` and `da16`**, whose home directory paths are in the code
  and in history. (The `~da16` lists' own licensing resolves with their planned
  publication; the *paths* are a separate disclosure question.) What `dip_LG6`
  denotes is still unrecorded.
- **Licence of the `/software/.../vgp_curation_scripts/` tree.**
- **What `post_process_rc` does** — 12 questions in report A. Deprioritised by
  the scope answer: the step stays Sanger-only, so this blocks only `grit-sanger`'s
  own `finalize`, not publication. Still worth answering, because grit currently
  verifies nothing about it (`exit 0` is the whole success criterion, and it has
  no `STEP_MANIFESTS` entry).
- ~~The identity of `decon_fasta`'s BLAST database~~ — **settled: `core_nt`,
  RAM-resident at Sanger** (author, 2026-09-03). Remaining sub-question: which
  `core_nt` release, since nothing pins it today and that is what makes past runs
  irreproducible across time.
- **Publication timeline for the `~da16` sex-BUSCO ID lists** — the author reports
  they will be published. Until then the `sanger` profile carries the NFS path; the
  public default needs the eventual URL.
- **Citability**: `CITATION.cff` + Zenodo DOI. For a research tool this is an
  adoption blocker.
- **Can a Sanger-visible CI runner ever exist?** The single largest available
  confidence win, and it changes ADR-17.
- **Can `GritJiraIssue` itself be packaged?** Deletes the last `sys.path` hack.

## Deliberately not decided here

Which fa/chr pairs are legal (M1/Batch 5 owns it, feeds ADR-09). The registry's
storage shape (`TODO/50` Batch 2, ADR-15). Whether `paternal`/`maternal` survive
at all — `CORR-14` shows `_detect_assembly_type` can never produce `paternal`, so
those branches are dead code, but Port 4's totality invariant needs the answer.
Whether the `_state-update` callback argv may change shape, given in-flight jobs
submitted by an older grit will call a newer CLI. How a `POLL_ONLY` backend gets
polled now that `status` is read-only. Whether `--bsub-ram` is renamed.
