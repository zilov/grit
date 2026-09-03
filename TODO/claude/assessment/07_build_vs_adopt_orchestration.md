# 07 — Build vs adopt: the orchestration layer

Read-only evaluation. No code changed. Written against branch `test_and_fix_steps`.

## Verdict

**Stay on vanilla Python for the orchestration layer. Do not adopt Airflow, Dagster, Prefect, Temporal, Snakemake, or Cromwell as grit's top-level engine.**

The decision is not close, and it is not sunk cost. `grit` is not a pipeline. It is a
**per-ticket, human-in-the-loop case-management tool** whose central artifact is a durable
record of what a named curator did to one genome over days-to-weeks, with the *human* deciding
what runs next. Every candidate engine's core competence — build a DAG, drive it from inputs to
outputs, terminate — is the part of the problem `grit` does not have. The parts `grit` actually
has (wait indefinitely on a GUI session outside the system; retrospective canonicality by mtime;
selective re-run driven by a curator's judgement; one `pip install` and no server) are the parts
those engines either do not do or do only by adding infrastructure that a shared HPC farm and a
lone external user cannot carry.

Two qualifications that keep this from being a comfortable answer:

1. **The hybrid in class D is already the real architecture, and it should be made explicit
   rather than left as an accident.** `hic_remapping.py:99-116` and `find_reference.py` shell out
   to the Nextflow pipeline `curationpretext`. That is the correct shape: Nextflow owns
   *within-step* data-flow parallelism; grit owns *between-step* human-paced sequencing and
   provenance. Name it in CLAUDE.md as the intended architecture.
2. **The "stay" verdict covers orchestration, not execution portability.** Phase 2's executor
   port is real work that engines do give away for free, and the `TODO/XX_pixi_portability_plan.md`
   direction (pixi/conda-forge for tool provisioning, backend detection in `environments.py`)
   is the right half of that answer. See "What to borrow instead".

The decisive axis is **axis 4 (operational requirements) combined with axis 1
(human-in-the-loop)**. Either one alone would be survivable; together they eliminate every class
except D. Axis 2 (provenance) is where the *most* is genuinely lost by staying, and axis 3
(executor portability) is where the second-most is lost.

---

## grit's actual execution model

The central hypothesis is **confirmed**, with three corrections worth stating precisely, because
two of them matter for the verdict.

### Confirmed: no DAG, no run, no scheduler

- There is **no "run the pipeline" entry point**. `click_cli.py:258-290` registers ~24 independent
  subcommands on a flat Click group. The nearest thing to a pipeline is
  `run_post_curation()` (`post_curation.py:36-44`), which is a three-line straight-line function
  calling `run_pretext_to_asm` → `run_haplotig_files` → `run_hic_remapping`. That is a shell
  script, not a DAG: no dependency graph, no topological sort, no failure propagation, no
  fan-out. The same for `post_curation_recurate`.
- **Dependencies are resolved at call time by looking at the filesystem, not by graph edges.**
  A step asks `find_canonical_fa(ctx, hap_prefix)` (`helpers.py:425`) for "the current assembly"
  and gets back whatever is freshest, computed at that instant. `hic_remapping.py:94`:
  `input_fa = assembly if assembly else find_canonical_fa(ctx, hap_prefix)`. There is no
  declared producer→consumer edge anywhere in the codebase.
- **Canonicality is retrospective and mtime-ordered.** `_latest_tracked_output()`
  (`helpers.py:400-422`) walks a flat pool of six step names and returns
  `max` by `p.stat().st_mtime`, with the list order used *only* as a tie-break
  (`candidate = (p.stat().st_mtime, -idx, p)`). `recuration-canonical-priority.md:14-58`
  states this explicitly: "whichever of these steps you ran most recently for a haplotype is
  canonical for it, full stop." This is precisely the inverse of a DAG, where the graph decides
  which output supersedes which *before* anything runs.
- **The human is the scheduler.** `recuration-canonical-priority.md:59-153` is a nine-step
  decision flowchart whose branch conditions are questions only a curator can answer: "Is
  curation in PretextView finished?", "Does it need a contaminant check?", "Does the remapped
  map need re-curating?". Step 8's loop (curate in PretextView → drop AGP into
  `{workdir}/recurate/` → `pretext-to-asm-recurate` → `hic-remapping` → repeat) is an unbounded
  cycle whose exit condition is human aesthetic judgement about a Hi-C contact map.
- **State is per-Jira-ticket and lives indefinitely.** `RegistryManager`
  (`registry.py:43-48`) keeps every ticket ever seen in a single `~/.grit/grit_registry.json`;
  `mark_done()` (`registry.py:110-113`) only flips a status field — "Ticket stays in
  grit_registry.json" — so history is queryable months later
  (`status.py` computes done-counts by week/month/quarter from it).
- **Wait-for-external-event is the norm, not an exception.** The event grit waits on is a human
  copying a `.pretext` AGP file onto the farm. `setup.py`'s `print_pretext_scp_commands` and
  `hic_remapping.py:129-134` both end by printing an `scp` line for the curator to run *on their
  own laptop*. grit's "await" primitive is: the process exits, and a human runs the next command
  hours or days later.

### Correction 1 — grit is not fire-and-forget-only; it has a real, working async completion mechanism

The submission path is non-blocking, but completion is genuinely tracked. `_state_update_epilogue()`
(`helpers.py:89-106`) builds a `bsub -Ep '<grit binary> _state-update ... --status $([ $LSB_JOBEXIT_STAT
-eq 0 ] && echo success || echo failed)'` epilogue; LSF runs it on job exit, and
`state_update_cmd` (`click_cli.py:210-255`) re-globs the run dir with the step's `_OUTPUT_SPECS`
before writing the terminal record. So "success" means *files verified on disk*, not
"submission returned zero". There is a second, independent recovery path:
`_refresh_pending_jobs()` (`registry.py:242-279`) bulk-queries `bjobs` on every `grit status`
and resolves `EXIT` → failed, `gone` → success/failed by output presence
(`_resolve_gone_job`, `registry.py:281-297`).

This matters because it is the single most engine-like piece of grit, and it is *good*. But it
is also the piece most obviously hand-rolled: two overlapping recovery mechanisms, a documented
class of steps for which neither applies (`fastga_stats`, which must `try/except` and finish
itself — CLAUDE.md is explicit that a crash there "strands the record as 'started' forever with
no recovery path but `grit untrack`"), and a documented failure mode where a step that shells out
to something that submits its own jobs (`hic_remapping.py`, `curationpretext`) gets no epilogue
at all and can report success "long before the real work finishes" (CLAUDE.md, Command execution).

### Correction 2 — `RunTracker` + canonical resolution *is* a hand-rolled provenance system, and it is under strain

`RunTracker` (`run_tracker.py`) is an append-only event log: `start` writes `{step, timestamp,
status, run_dir, job_id}` (`run_tracker.py:95-106`), `finish` appends a terminal record
(`run_tracker.py:139-152`), and every query folds the log forward
(`_untracked_dirs`, `run_tracker.py:32-43`; `pending_jobs`, `run_tracker.py:231-250`). Outputs
are recorded as a `{semantic_key: absolute_path}` dict — `("hap1_fa", "{tol_id}.{hap1}.*.curated.fa",
["all_haplotigs", ...])` in `pretext_to_asm.py:26-42`. `untrack`/`retrack`
(`click_cli.py:310-359`) are manual lineage overrides.

This is an asset catalog with materialisation events, output metadata, and a manual
supersession override — built by hand. The strain is visible: `_step_output()`
(`helpers.py:364-397`) exists *only* because a run whose outputs were recorded incompletely
would otherwise "silently hand the canonical slot to an older step, moving canonical
*backwards* in time" (that is commit `143f425` on this branch), and the `Canonical` column in
`grit status` had to be rebuilt from a bare `★` to per-type `fa(1)`/`hap(1),chr(1)` codes
because the single marker "collapsed genuinely distinct facts into one symbol"
(`recuration-canonical-priority.md:166-185`). Both are provenance-display problems that a
lineage engine would not have.

### Correction 3 — the JSON registry has no concurrency control at all

`RegistryManager._save()` (`registry.py:308-312`) writes to `.tmp` and `os.replace`s, which is
atomic *per write* — but every mutation is an unsynchronised read-modify-write of the entire
file: `append_step` (`registry.py:161-169`) calls `self._load()`, appends, `self._save()`.
There is **no `flock`, no `fcntl`, no lock file anywhere in `grit/`** (verified by grep). Two
concurrent writers therefore lose an update.

This is not theoretical. The `-Ep` epilogue runs `grit _state-update` **on an LSF compute node**,
writing to `~/.grit/grit_registry.json` over NFS. A curator who submits `hic-remapping --hap2`
(two jobs) plus `fastga` and then runs `grit status` has up to four processes on three machines
performing read-modify-write on one JSON file with no lock, over a filesystem whose `rename`
atomicity guarantees are weaker than local POSIX. A lost `_state-update` shows up as a run
stranded in `started` — recoverable via the `bjobs` path, so the bug is masked rather than
absent. This is the single strongest concrete argument on the "adopt" side, and it should be
fixed regardless of the verdict.

### Where the hypothesis is slightly too strong

"Steps are re-run selectively" is true, but grit also has *ad hoc* idempotency that a real
engine would give uniformly: `hic_remapping.py:44-84` hand-writes a "skip if the previous
`hr.pretext` is newer than the canonical FASTA" check, and `fastga.py:199-203` hand-writes a
"reuse existing results" check. Each step invents its own staleness rule. Snakemake's
`--rerun-triggers {mtime,code,params,input,software-env}` (default: all five, verified in the
Snakemake 9 CLI docs) is exactly this, once, for every rule.

---

## Candidate evaluation

### Axis scoring

Scale: ●●● strong fit / ●●○ partial / ●○○ weak / ✗ disqualifying.

| Axis | A. Bioinf WFM (Nextflow / Snakemake 9 / WDL) | B. DAG orchestrators (Airflow 3 / Dagster / Prefect 3) | C. Durable execution (Temporal / Prefect durable) | D. Hybrid: grit CLI + engine inside steps |
|---|---|---|---|---|
| 1. Human-in-the-loop, days-long wait | ✗ — no pause/await primitive; the workflow must exit and be re-invoked, i.e. exactly what grit already does | ●●○ — Airflow sensors/deferrable ops and Prefect `suspend_flow_run` exist; Dagster does it by splitting into separate jobs. All require the server to stay up for the whole wait | ●●● — this is Temporal's literal purpose (signals, indefinite waits, durable timers) | ●●● — the wait is *between* CLI invocations; nothing has to stay alive |
| 2. Selective re-run + supersession lineage | ●●○ — Snakemake `--rerun-triggers` is excellent for staleness; neither Snakemake nor Nextflow models "output X supersedes output Y" | ●●● for Dagster (assets, materialisation events, catalog, lineage graph) — the best fit on this axis of anything evaluated | ●○○ — Temporal tracks execution history, not data lineage | ●○○ — stays hand-rolled |
| 3. Executor portability (LSF/Slurm/local/cloud) | ●●● Nextflow: `process.executor` covers local, lsf, slurm, k8s, awsbatch, google-batch, azurebatch, sge, pbs, condor, flux + more (verified, docs.seqera.io/nextflow/executor). Snakemake 9: plugin catalog covers slurm/k8s/cloud; **the LSF plugin is community-maintained and its own page carries "This plugin is not maintained and reviewed by the official Snakemake organization"** (verified) | ●●○ — Airflow/Prefect/Dagster have no first-class LSF executor; you write a `bsub` operator yourself, i.e. the same work as Phase 2 | ●○○ — Temporal has no concept of an HPC scheduler; activities would shell out to `bsub` anyway | ●○○ — grit hand-writes it (Phase 2) |
| 4. Operational requirements | ●●● — Nextflow and Snakemake are **`pip install` / single binary, no daemon** | ✗ — Airflow 3 requires a metadata DB, a scheduler process and an API server (verified, airflow.apache.org architecture overview); on HPC the documented pattern is a separate VM + CeleryExecutor with workers on compute nodes. Dagster needs a daemon+DB for schedules/sensors; Prefect 3 needs a server/API for suspend-resume. **Nobody at a curation team is going to run and page for a database so one curator can remap Hi-C reads.** | ✗ — self-hosted Temporal is a 4-service cluster on Cassandra or Postgres, deployed via Helm on Kubernetes (verified, docs.temporal.io). Cited realistic small-production cost ~$1.2–1.8k/month | ●●● — nothing new; `curationpretext` already ships with the farm |
| 5. CLI/UX quality retained | ●○○ — you keep `grit` as a wrapper, so the CLI survives only because you kept building it. `--print-only` has no Nextflow analogue (`-preview`/`-stub` are not the same); `grit status`'s per-ticket history would have to be rebuilt over `.nextflow.log`/trace files | ●○○ — the UI moves to a web UI; `grit status`, `--dry-run`, `--print-only`, `untrack`/`retrack` all get rebuilt on top, or lost | ●○○ — CLI is entirely yours to rebuild; `tctl` is not a curator tool | ●●● — untouched |
| 6. Audience familiarity | ●●● — Nextflow/Snakemake are the lingua franca of the field; a Sanger bioinformatician reads a Nextflow process without training | ●○○ — Airflow/Dagster are data-engineering culture; near-zero penetration among genome curators | ✗ — culturally alien; a curator has never heard of a workflow worker | ●●● — a curator learns `grit <verb> -t <ticket>` |
| 7. Migration cost | 14–22 pw (see below) | 20–32 pw | 25–40 pw | 2–4 pw (Phase 2 only) |
| 8. What is lost | `--print-only`, `--dry-run`, the ticket registry, `untrack`/`retrack`, per-ticket status — none have engine equivalents | all of the above + zero-infra install | all of the above + the field's ability to maintain it | nothing |

### A. Bioinformatics workflow managers — the strongest "adopt" case, and it still fails

Nextflow is the closest cultural fit and the best executor story in the entire evaluation
(verified list above; `process.executor = 'lsf'` is one config line, and grit currently
hand-writes `bsub` string assembly in `_submit_bsub`, `build_bsub_opts`, `_check_bjobs`, and
`_state_update_epilogue`). If grit were a batch pipeline, this section would say "you should have
used Nextflow" without hedging.

It fails on axis 1, and the failure is structural, not a missing feature. A Nextflow run is a
JVM process driving a channel dataflow graph to completion. There is no primitive for "stop here;
a human will open a GUI on their laptop, work for three days, and produce a file". The only
implementations are (a) block a process on a file-watch — which pins a JVM and an LSF slot for
days, and (b) split into two workflows joined by `-resume` — which is *exactly* grit's current
model, with Nextflow's cache-hash semantics added on top as a liability rather than a benefit
(`-resume` invalidates on input path/timestamp/task-hash changes; grit's whole recurate loop is
"the input file deliberately changed, and the human decided that is fine"). I could not find
authoritative documentation of a Nextflow pause/await-external-event primitive, and searches
returned only community threads about polling for file existence — flagged in Unverified claims.

Snakemake 9 is technically the better *provenance* fit of the two (`--rerun-triggers` including
`code`, `params` and `software-env` is genuinely better than every staleness check grit
hand-writes), but its DAG is defined by output-file wildcards, and grit's output filenames are
resolved by mtime across a *pool* of alternative producers — which is not expressible as a
Snakemake rule graph without inventing a single canonical filename per haplotype and having every
step overwrite it, destroying the run history that is grit's main product. And its LSF executor
is explicitly community-maintained (verified quote above) — for the one scheduler grit runs on
today, Snakemake gives less assurance than Nextflow does.

WDL/Cromwell and CWL are worse on every axis here (heavier, no CLI-first ergonomics, Cromwell
wants a server for anything beyond `run` mode) and add nothing the other two do not.

### B. General DAG orchestrators — disqualified on axis 4

Airflow 3 requires a metadata database plus a scheduler plus an API server (verified). The
documented HPC integration pattern is a separate always-on host running scheduler+webserver with
Celery workers on compute nodes. That is a *service* with an owner, an upgrade path, credentials,
and a pager. grit's install story today is `pip install grit && grit init`. The gap is not
"harder", it is a different category of software, and it destroys the "external user runs it on
their own farm" goal that `TODO/XX_pixi_portability_plan.md` is explicitly working toward.

**Dagster deserves the honest answer the brief asked for: the asset match is real, not
superficial — and it is still the wrong trade.** `RunTracker`'s
`{step, run_dir, outputs: {key: path}, status}` records are materialisation events; the
`_OUTPUT_SPECS` tuples are asset definitions; `find_canonical_fa`'s pool is a lineage query;
`untrack`/`retrack` is a manual supersession override; `grit status -t`'s Canonical column is an
asset catalog view. Dagster has all of that as a product, hardened, with a UI. Verified: Dagster
external assets went stable in 1.8 and source assets are deprecated, with an REST API for
recording `AssetObservation` events — so grit could report LSF-executed work into a Dagster
catalog *without* Dagster executing anything (this is the "observability without changing your
scheduler" pitch). That is the one adoption path in class B that is not absurd.

It still loses, for three reasons. (i) Dagster's asset model is *declarative and
graph-shaped*: an asset has fixed upstream deps. grit's canonical resolution is a runtime
`max`-by-mtime over a pool of *mutually substitutable* producers of the same logical asset — five
different steps can all be the parent of "hap1 FASTA", and which one is depends on what the human
did last. You would model this as a single asset with a manual observation for each producer, at
which point Dagster is storing the same records grit stores, and `find_canonical_fa` is still
your code. (ii) The catalog needs the Dagster webserver+daemon to be worth anything, which is
axis 4 again. (iii) Curators do not have and will not get a Dagster deployment.

Prefect 3 is the least-bad of the three (Python-native decorators, `suspend_flow_run` for human
approval — the docs confirm "Pause flows for human intervention or approval"; I could not verify
the suspension duration limits or the exact infra requirement, flagged below). But suspension
implies a server holding the run's state, and a suspended run is a poor model for "the curator
might come back in three weeks, or never, or might decide to `grit remove` the ticket".

### C. Durable execution engines — technically closest, operationally impossible

Temporal is the only system evaluated whose *core semantics* match the hypothesis exactly:
a workflow that runs for weeks, waits on an external signal, survives process restarts, and
replays deterministically. If grit's problem existed inside a company with a platform team, this
would be a genuine contender.

It is disqualified by axis 4 and axis 6 together. Self-hosting is a four-service cluster
(frontend/history/matching/worker) on Cassandra or PostgreSQL, Helm-deployed on Kubernetes
(verified). Temporal Cloud removes the ops but puts a commercial SaaS dependency between a
Sanger curator and their genome. And axis 6 is not a soft concern: the maintenance population for
this code is genome curators and Tree-of-Life bioinformaticians. A Temporal workflow worker in
that setting is a bus factor of one, forever.

Note also that Temporal solves the *wrong half*. grit's durability requirement is
"remember what happened to RC-1234 for years", which is a small append-only log — grit already
has it. It is not "keep a running process alive across a restart", which is what Temporal is for.
grit's processes are *supposed* to exit.

### D. The hybrid — this is already the architecture; recognise it

`hic_remapping.py:99-116` invokes `curationpretext.sh -profile sanger,singularity ... -resume`,
and `find_reference.py` does the same. Nextflow is already doing the heavy within-step
data-flow work (Hi-C alignment, map generation, telomere splitting), with its own executor,
retry, caching and `-resume`. grit contributes: which assembly to feed it, where to put the
output, what that output means for canonicality, and how to tell the curator what to do next.

That division is correct and should be stated as intentional. The one caveat, which CLAUDE.md
already documents, is that this is exactly the case where the `-Ep` epilogue cannot attach — the
`bsub`/nextflow-launcher relationship means grit "never sees a job it can attach an epilogue to,
and the step's tracked status can go 'success' long before the real work finishes". Making the
hybrid explicit means owning that seam deliberately (e.g. treating a Nextflow-backed step's
completion as "read the pipeline's own trace/report", not "the launcher exited").

---

## What we lose by staying vanilla Python

This is the real cost, stated without softening. Every item below is work grit's maintainers now
own forever, that a mature engine has already solved, hardened, and tested against thousands of
users.

**1. You own an executor abstraction that does not exist yet, and Nextflow would have handed you
15 backends for one config line.** Today LSF is not abstracted at all — it is hardcoded string
assembly spread across `_submit_bsub` (`helpers.py:62-87`), `build_bsub_opts`
(`helpers.py:134+`), `_check_bjobs` (`helpers.py:108-131`), `_state_update_epilogue`
(`helpers.py:89-106`), plus `-Ep`, `bjobs`, `$LSB_JOBEXIT_STAT` and per-step `bsub_ram`/queue
knobs threaded through `GritCommand`. Phase 2 will hand-write what
`process.executor = 'slurm'` already is. And the abstraction is not the hard part — the hard part
is the *long tail per backend*: Slurm has no `-Ep` epilogue (you need `--dependency=afterany` or
`sacct` polling), local execution has no job ID at all, cloud has neither. grit's completion
model is structurally LSF-shaped, and that is the piece that will hurt.

**2. Concurrency safety on the JSON registry is a real, currently-unfixed bug you own.** No lock
of any kind exists (verified by grep). Read-modify-write on `~/.grit/grit_registry.json`, from
multiple processes, some of them on compute nodes over NFS. Every engine in classes B and C
solved this in 2015 by putting state in a transactional database. You will fix it with `flock`
and hope NFS honours it, or by moving to SQLite (which has its own NFS caveats), or by making the
log a directory of per-record files. It is a day of work and a class of silent corruption you
will be diagnosing for years.

**3. Retry, backoff and failure classification: you have none.** `_run()`
(`helpers.py:42-60`) is `subprocess.run(..., check=True)`. A transient NFS stall, a queue
rejection, a licence-server hiccup — all become a Python traceback and a `failed` record the
curator must notice and re-issue by hand. Nextflow's `errorStrategy 'retry'` with
`maxRetries`/dynamic resource escalation (retry with more memory on exit 137) is a one-line
directive; grit's answer is `--bsub-ram` and a human.

**4. Provenance is hand-rolled, and it has already bitten.** `_step_output()`'s re-glob
(`helpers.py:364-397`) exists solely to stop canonical moving backwards in time (commit
`143f425`, "don't let a run with incomplete outputs move canonical backwards"). The Canonical
column had to be redesigned once because one symbol conflated distinct facts
(`recuration-canonical-priority.md:166-185`). Dagster ships this as a product. You will keep
finding these.

**5. Idempotency/staleness is per-step and inconsistent.** Compare `hic_remapping.py:44-84`
(compare `hr.pretext` mtime against canonical FA mtime, plus a special case for a stranded
`started` record) with `fastga.py:199-203` (glob for a previous result and reuse). Snakemake's
`--rerun-triggers` does this once, uniformly, including on *code and parameter changes* — grit
cannot currently detect that a step's shell command changed and its outputs are therefore stale.
That is a correctness gap, not just a convenience gap.

**6. Observability is `grit status` and LSF logs.** No run timeline, no resource-usage
report, no per-task trace, no way to answer "why did RC-4833 take five weeks" without reading
JSON. Nextflow gives `-with-report`/`-with-trace`/`-with-timeline` for free; Dagster and Airflow
give a UI. `status.py` is 681 lines of hand-written Rich tables — good ones, but 681 lines you
maintain.

**7. Two overlapping completion-recovery mechanisms with documented holes.** The `-Ep`
epilogue and the `bjobs` sweep cover different cases; synchronous steps (`fastga_stats`) are
covered by neither and must self-report or strand forever; Nextflow-launching steps
(`hic_remapping`) can report success before the work finishes. Each hole is individually small
and individually documented — collectively they are the kind of thing a durable execution engine
makes structurally impossible.

**8. Bus factor and hiring.** "We use Nextflow" is a transferable skill. "We use a bespoke
9.5k-LOC Python orchestrator with an mtime-ordered canonical pool" is onboarding cost for every
future maintainer, and it is not on anyone's CV.

None of these is fatal. Items 2, 3 and 5 are the ones that should be scheduled, not merely noted.

---

## What we lose by adopting an engine

**1. `--print-only`.** There is no equivalent in any candidate. `_run()`
(`helpers.py:52-57`) prints the exact shell command and returns. For a curator debugging why a
`curationpretext` invocation failed, "here is the literal command line, copy it and run it
yourself" is the single most valuable affordance grit has. Nextflow `-preview`/`-stub-run`,
Snakemake `-n`, and Airflow's dry-run all show *tasks*, not the resolved command line. This
would be lost outright.

**2. `--dry-run`.** The sandbox at `~/.grit/dry_run/` with `write_fake_outputs()` and per-step
dry-run branches across 24 commands exists to exercise *step sequencing, tracking and canonical
resolution* without HPC or NFS. In an engine, the equivalent is "test the DAG", which is easy —
but grit's dry-run tests the part that would *not* be in the engine (the ticket state machine),
so you would rebuild it anyway.

**3. `untrack` / `retrack`.** A curator-facing "make this run non-canonical / promote it back"
override with full semantics (`run_tracker.py:218-229`, `click_cli.py:310-359`, and the
`untracked=` invariant threaded through every `start`/`finish` pair). Only Dagster has anything
in this shape (asset wipe / manual materialisation), and it is not the same operation.

**4. The Jira-ticket-as-unit-of-work model.** `CurationContext.from_ticket`
(`context.py:213-260`) pulls the YAML from Jira, derives every path
(`_derive_workdir`, `context.py:280-296`), and the registry is keyed by ticket. No engine has a
concept of "a case that belongs to a curator and a Jira issue and lives for weeks". You would
keep this layer under any engine — which is the point: **adoption does not remove grit's state
model, it adds an engine underneath it.**

**5. Zero-infrastructure install.** `pip install grit && grit init` on any farm. Classes B and C
destroy this. Class A preserves it (both are single-binary/pip installs).

**6. The CLI as the product.** `rich-click`, ~24 discoverable commands, `grit status` with
per-ticket history and a Canonical column, `print_tip`/`print_done` guidance printed at exactly
the point the curator needs to run an `scp`. This is not decoration — for a tool whose users are
biologists mid-curation, it *is* the tool. Under any engine you keep writing it, so the engine
buys you nothing here and costs you the integration.

**7. Roughly 9,500 LOC and 451 tests of embedded domain knowledge.** Not "sunk cost" — the
knowledge is in the code and would have to be re-encoded: `_detect_assembly_type`'s
hap1/primary/paternal mapping, `is_single_hap` gating hap2 fabrication in six steps, the
blast-contaminants-after-rename-and-orient known limitation
(`recuration-canonical-priority.md:96-104`), the `_OUTPUT_SPECS` fallback patterns for primary
assemblies (`pretext_to_asm.py:33-41`). Every line of that is a re-migration risk.

---

## What to borrow instead

Patterns, not dependencies. In rough priority order.

**1. Nextflow-style executor abstraction, but borrow the *shape*, not the code.** Nextflow's
executor interface is essentially four operations: submit, get status, kill, and derive a job's
work dir. Design Phase 2's port against that four-verb shape rather than around grit's current
LSF-specific surface. Concretely, the thing to steal is that Nextflow makes *completion detection*
part of the executor contract, not part of the step — grit currently has completion detection
split between `_state_update_epilogue` (LSF-only) and `_check_bjobs` (LSF-only) with
per-step exceptions. A `LocalExecutor` (run in a subprocess, completion is the exit code) and a
`SlurmExecutor` (`--dependency=afterany` or `sacct` polling) should slot in without any step file
changing. That is the real test of the port.

**2. Snakemake-style rerun triggers, unified.** Replace the five hand-written "is this stale"
checks with one shared helper taking the triggers Snakemake uses: `input` mtime, `params`
(the resolved command string — grit could hash the `inner_cmd` it already builds), and
`software-env` (the `MODULE_VERSIONS` entry the step resolved). Store the hash in the run record
alongside `outputs`. This closes gap 5 above, is maybe 150 lines, and directly improves
correctness — today a `MODULE_VERSIONS` bump does not invalidate anything.

**3. Dagster-style asset semantics for the tracker.** Not Dagster itself — its vocabulary.
Specifically: (a) make "the hap1 FASTA" a named *asset* with multiple possible producers, so
`find_canonical_fa`'s pool becomes data rather than a hardcoded list in three near-identical
functions (`helpers.py:425`, `:477`, `:563`); (b) record an explicit `supersedes` /
`superseded_by` edge when a run wins canonicality, so the history is a lineage graph rather than
something re-derived by `max(mtime)` on every call — that alone would have prevented the
"canonical moves backwards" bug rather than patching around it; (c) keep `untrack`/`retrack` as
what they already are, a manual lineage override.

**4. Nextflow-style `errorStrategy` as a step-level declaration.** A small retry/backoff wrapper
around `_run`/`_submit_bsub`, declared per step (`retries=2`, `retry_on=('137',)`,
`memory_escalation=2x`), rather than nothing. This is cheap and removes the most common curator
annoyance.

**5. pixi/conda-forge for tool provisioning — proceed as planned.** `TODO/XX_pixi_portability_plan.md`
is the right answer to the half of portability that is *not* the scheduler, and it is orthogonal
to this verdict. `detect_backend() -> lmod | pixi | conda` plus a `tool_cmd()` that returns either
a `module load` fragment or a bare binary name is exactly Snakemake's conda-directive idea
scoped to grit. Note the doc's own open question about `curationpretext` needing a container —
that one is real, and it is another argument for treating Nextflow as the *inner* engine
(nf-core-style container-per-process) rather than the outer one.

**6. Transactional state, borrowed from every engine in class B.** Move the registry off a single
read-modify-write JSON blob. Cheapest correct option: one append-only JSONL file per ticket
(`{workdir}/.grit/history.jsonl`) opened `O_APPEND` — appends under `PIPE_BUF` are atomic even
over most NFS setups, and the fold-forward query logic in `run_tracker.py` already treats the
store as an append-only event log, so the reader barely changes. Do this before the executor port,
because a Slurm/local backend multiplies the number of concurrent writers.

**7. Keep and formalise the Nextflow-inside-steps hybrid.** Add a sentence to CLAUDE.md saying
this is deliberate: engines own within-step data flow; grit owns between-step human sequencing.
And treat "step whose real work is submitted by an external tool" as a first-class category with
its own completion contract, rather than a documented footnote.

---

## Migration cost estimate

Baseline measured on this branch: **9,483 LOC** in `grit/`, **8,803 LOC / 451 test functions** in
`tests/`, ~24 registered CLI commands (21 pipeline steps plus registry commands). Assume one
experienced developer with full domain context, and add the pessimistic test-coupling case
described below.

**Test coupling, measured.** 135 assertion/inspection sites across 12 of 26 test files reference
resolved command strings or mock call args (`"FastGA_dot_dgenies_stats.sh" in inner_cmd`,
`tests/test_fastga.py:52`). Concentrated in `test_post_curation.py` (42),
`test_rename_and_orient.py` (22), `test_find_reference.py` (18), `test_microchromosome.py` (17),
`test_bsub_ram_override.py` (10), `test_status.py` (11). So roughly **30% of the suite is coupled
to shell-command construction** and would need rewriting under any adoption that changes how
commands are built; the other ~70% asserts on tracker state, output dicts and canonical
resolution, and survives *only if the tracker survives* — i.e. it survives in the hybrid and dies
in a full port. The pessimistic case (the other agent's assessment finding heavy coupling) adds
roughly **+3 to +5 person-weeks** to every option below, because in that case even
`--print-only`-style behavioural tests must be re-expressed.

| Option | Estimate | Reasoning |
|---|---|---|
| **D. Stay + Phase 2 executor port** (recommended) | **2–4 pw** | Extract 4 LSF call sites into an executor interface (~3 days); write `LocalExecutor` (~2 days) and `SlurmExecutor` incl. completion detection without `-Ep` (~1 week, this is the risky part); fix registry concurrency (~2 days); update the ~30 tests that assert on `bsub` strings (~1 week). No step logic changes. |
| **+ borrow items 2, 3, 4, 6** | **+3–5 pw** | Unified rerun triggers ~1 pw; asset/supersedes model in the tracker ~1.5–2 pw (touches `find_canonical_*`, `status.py`, and the tests that cover them); retry wrapper ~0.5 pw; JSONL store ~0.5–1 pw. |
| **A. Full Nextflow port** | **14–22 pw** | 21 steps → processes/workflows at 1–2 days each incl. containerising or `module`-wrapping each tool = 5–8 pw. Re-implement the ticket registry + `RunTracker` + canonical resolution — Nextflow has **no** equivalent, so this stays Python: 0 pw saved, but the seam between Nextflow's work dirs and grit's run dirs must be built = 2–3 pw. Rebuild `--print-only`, `--dry-run`, `grit status` over Nextflow trace files = 2–3 pw. Test rewrite = 4–6 pw (the 30% coupled tests all die; another chunk needs re-expressing against nf-test). Plus 1–2 pw of learning-curve and `-resume` semantics debugging. **You end up with the same CLI, the same state model, and Nextflow underneath — which is what option D gives you incrementally for a tenth of the cost.** |
| **A. Snakemake 9 port** | **12–18 pw** | Cheaper than Nextflow (Python-native, less impedance) but requires forcing grit's mtime-pool canonicality into wildcard-based output paths — a genuine modelling problem with no clean answer, budget 2–3 pw of design alone. And the LSF executor plugin is community-maintained, so the one backend you need today is the least assured. |
| **B. Dagster** | **20–32 pw** | 21 steps → assets (6–10 pw); stand up webserver + daemon + Postgres and get it approved on Sanger infrastructure (2–4 pw of engineering, unbounded calendar time for the approval); rebuild CLI as a thin client over the GraphQL API (3–5 pw); test rewrite (6–8 pw); plus permanent ops. The *observability-only* variant — keep grit exactly as-is and push `AssetObservation` events to a Dagster instance via its REST API — is far cheaper at **2–3 pw**, but only pays off if someone is already running Dagster. |
| **B. Airflow** | **22–32 pw** | As Dagster, minus the asset model that was the only reason to consider class B. Not recommended under any assumption. |
| **C. Temporal** | **25–40 pw** | Rewrite every step as workflow/activity with determinism constraints (8–12 pw); stand up or buy a cluster (2–6 pw + ongoing); rebuild the entire CLI (4–6 pw); test rewrite against the Temporal test framework, essentially from scratch (8–12 pw). Then maintain it with a team of genome curators. |

**The asymmetry is the whole argument.** Option D delivers the concrete Phase 2 goal (LSF
swappable for local/Slurm/cloud) in 2–4 person-weeks. The cheapest full adoption that also
delivers it costs 12+ person-weeks and *still leaves you maintaining the ticket registry,
canonical resolution and the CLI by hand*, because no engine models them.

---

## Answer to "is this inexperience?"

No. Choosing vanilla Python here is a defensible engineering judgement, and the evidence is in the
shape of the code rather than in its polish. The tell is that grit has no DAG, no run entry
point, and no scheduler — because the problem has none. What it has instead is a per-ticket
durable log, retrospective mtime-based canonicality, and a CLI whose job is to tell a human what
to do next; a workflow manager would have given you nothing for the first two and would have
fought you on the third. Where inexperience *does* show is narrower and more fixable: no locking
on a JSON file that is written concurrently from compute nodes over NFS, no retry/backoff, five
different hand-written staleness checks, and a completion model welded to LSF's `-Ep` epilogue.
Those are the places to go and read how Nextflow, Snakemake and Dagster solved the same problems,
and borrow their patterns. The architecture is right; some of the mechanisms inside it are
first-drafts.

---

## Unverified claims

Things I could not confirm from authoritative sources, and how to settle each:

1. **Nextflow has no pause/await-external-event primitive.** Asserted from the absence of any such
   directive in the executor and process documentation plus community threads that only discuss
   polling for file existence. Searches returned no authoritative statement either way. *Settle
   by:* searching the Nextflow docs for `exec`/`onComplete`/workflow-level await, or asking on the
   nf-core Slack. My confidence is high but this is the single most load-bearing negative claim in
   the report — if Nextflow shipped a durable human-approval primitive, class A's axis-1 score
   changes from ✗ to ●●○ (though the axis-2 and axis-5 losses would still stand).
2. **Prefect 3 `suspend_flow_run` duration limits and infrastructure requirements.** The docs page
   fetched confirms "Pause flows for human intervention or approval" but the fetched content
   did not include timeout values or whether a server/API is strictly required for suspension
   (as opposed to in-memory pause). *Settle by:* reading
   `docs.prefect.io/v3/advanced/interactive` and the `suspend_flow_run` API reference directly.
3. **Airflow 3 deferrable-operator behaviour over multi-day waits.** I verified the architecture
   requires a metadata DB + scheduler + API server, but did not verify how deferrable
   operators/sensors behave across scheduler restarts over a multi-week wait. Does not change the
   verdict (axis 4 is already disqualifying) but would sharpen the axis-1 score.
4. **Dagster external-assets REST API stability and whether it can run without the webserver.**
   Verified that external assets are stable as of 1.8 and that an `AssetObservation` REST API
   exists; did not verify whether the observability-only variant genuinely works against a
   Dagster+ / OSS instance without a full deployment. *Settle by:* reading
   `docs.dagster.io/apidocs/external-assets`. This matters only if the cheap 2–3 pw
   observability-only variant is ever considered.
5. **Whether `os.replace` on the Sanger NFS mount holding `~/.grit/` is genuinely atomic.** I
   verified there is no locking in grit's code; I did not verify the filesystem's semantics.
   *Settle by:* checking whether `~/.grit` is on NFS or local disk on the farm login nodes, and
   whether compute nodes mount the same path. If `~/.grit` is on a local disk that compute nodes
   do *not* share, then the `-Ep` epilogue's `_state-update` is writing to a *different* registry
   file than the login node reads — which would be a considerably more serious bug than the race,
   and should be checked first.
6. **Snakemake LSF plugin maintenance status.** I verified the `lsf-jobstep` plugin page carries
   "This plugin is not maintained and reviewed by the official Snakemake organization". I did not
   separately check the plain `lsf` plugin's page (the fetch resolved to the same catalog
   content), nor its recent commit activity. *Settle by:* checking
   `github.com/snakemake/snakemake-executor-plugin-lsf` commit history.
7. **Test-coupling percentage.** The ~30% figure is a grep-based proxy (135 sites matching
   `in cmd` / `in inner_cmd` / `call_args` across 12 files, against 451 test functions), not a
   per-test classification. The other agent's dedicated assessment supersedes this number.
