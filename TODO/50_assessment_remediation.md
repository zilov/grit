# TODO 50: remediation queue for the Phase 1 assessment

Working checklist for the findings in `TODO/49_architecture_assessment.md`.
Evidence per finding is in `TODO/claude/assessment/01..07`.

Phase 2 (open-core / ports design) is `TODO/51`, deliberately numbered after
this file: several items here are prerequisites for it, and one whole batch is
deliberately deferred *into* it.

## Problem

126 raw findings is too many to work one-by-one, and a flat list is the wrong
shape for three reasons:

1. **Findings form causal chains.** `CORR-03` → `DOM-01` → `DOM-05`/`CORR-06` is
   one bug with four symptoms. Fixing the root deactivates the children; fixing
   a child leaves the root live and produces a half-fix — exactly what commit
   `143f425` was.
2. **Some findings will be moved or deleted by Phase 2.** Splitting
   `helpers.py`, relocating `build_context`, or moving the test seam now means
   doing that work twice. They belong in the ports design, not here.
3. **One ordering constraint is hard.** `TEST-02`: the port's seam and the
   tests' seam are the same 147 lines. If the ports refactor starts before the
   test seam moves to injected collaborators, 123 tests fail in one
   unreviewable commit.

So: batches, in order, each one branch per the project's stacked-branch gitflow,
each closed by a test rather than by inspection.

## Design

**Method per item.** Write the failing test first, then fix. This is not
ceremony: the boundary that most P0 findings live on has *zero* tests
(`TEST-01`), so for these items the test is the deliverable that keeps the fix
from silently regressing. An item is `[x]` only when a named test proves it —
record the test in the item.

**Method per batch.** Fix the root item first, then re-check the children before
touching them; several will already be gone. Do not close a batch on the
strength of a reasoning chain — re-run the relevant assessment axis against the
branch.

**Rule for the deferred bucket.** If a fix would touch a file that Phase 2 is
going to restructure, and the finding is not P0, it goes to `## Deferred into
Phase 2`. Resist fixing it early.

---

## Batch 0 — one blocking question — ANSWERED

- [x] **Is `~/.grit/` on a filesystem visible to compute nodes? YES** — the
      registry file is reachable from all nodes (confirmed by the author,
      2026-09-03). So the epilogue's `grit _state-update` does write to the same
      registry the login node reads; no systematic divergence.

      **Consequence for Batch 2:** the shared-filesystem answer is the *worse*
      one for concurrency. Every login node and every compute node writes the
      same file, over NFS, with no locking and through a shared fixed
      `grit_registry.tmp` — so `CORR-02` stands at full severity, and the writer
      set is larger than a single machine's processes. NFS also weakens the one
      guarantee the code does have: `os.replace` is atomic locally, but
      concurrent writers on different hosts plus NFS attribute caching mean a
      reader can still observe a stale document and then write it back. This
      makes the per-ticket append-only JSONL option (borrowed pattern, report
      07) more attractive than adding `flock`, since NFS file locking is
      notoriously unreliable across implementations.

---

## Batch 1 — make the safety net real (all S, do before anything else)

Everything after this batch is verified through these mechanisms, so they have
to be trustworthy first. This is also where the missing boundary tests get
written, because Batches 2-5 need them.

- [ ] `ARCH-07` — four commands allowlisted for `--dry-run` with zero `dry_run`
      code: `haplotig_files`, `validate_files`, `post_curation`,
      `post_curation_recurate`. `grit --dry-run haplotig-files` does real
      filesystem writes. Either implement the branch or remove from
      `_DRY_RUN_SUPPORTED_COMMANDS`. *Verified: 0 `dry_run` hits in all four.*
- [ ] `ARCH-07b` — `validate-files` is allowlisted, has a `_cmd`, and is
      commented out of the command tree (`click_cli.py:280`): 151 LOC
      unreachable. Register it or delete it.
- [ ] `DX-01` — `tests/local_smoke_test.sh` dies at line 66 under `set -euo
      pipefail` (invokes three commands commented out of the CLI). The
      regression check CLAUDE.md mandates for canonical-FASTA logic is
      unrunnable. Fix, then add to CI (`TEST-11`).
- [ ] `CORR-12` — `_run` captures stderr and discards it; a failing farm tool
      reaches the curator as an exit code plus a traceback with the tool's own
      diagnostic lost. Surface it. This is the single biggest improvement to
      debugging cost in the report.
- [ ] `CORR-22` — `_run` sets no timeout anywhere.
- [ ] `TEST-01` — write the missing boundary tests: `_run`'s subprocess branch,
      `_submit_bsub`, `build_bsub_opts`, `_state_update_epilogue`,
      `_check_bjobs`. Nothing currently distinguishes a valid `bsub` line from a
      mis-quoted one. These are the baseline for Batches 2-4.
- [ ] `TEST-08` — no test of any kind covers `_state_update_epilogue` or the
      `_state-update` command. The function is pure string-building; the command
      is invocable via `CliRunner`. (`effort: S`.)
- [ ] `TEST-04` — `_check_bjobs`'s output parsing is untested; it is a pure
      function over an injectable string.
- [ ] `PKG-06` — add a type checker to CI against the existing ~75%/77%
      annotation coverage that nothing enforces. Highest value-per-effort gate
      available; the work is already done.

*Batch done when:* the smoke test runs green in CI, and the five boundary
functions have tests that fail if their command strings are wrong.

---

## Batch 2 — registry integrity (data loss)

Root cause: fail-open load + unlocked whole-file read-modify-write + a shared
temp path, now known to be shared across every login *and* compute node
(Batch 0).

**Split, deliberately.** `CORR-01` is a pure bug with no architectural
implication — fix it now. `CORR-02`'s *fix shape* is an architecture decision
(locking vs per-ticket append-only JSONL) and belongs to Phase 2 as an ADR;
NFS-wide file locking is unreliable enough that the JSONL option is probably the
answer, and that is not a call to make in a hurry.

Fixing `CORR-01` alone removes the catastrophic amplification: a lost update
then strands one run as `started` (recoverable via `untrack`/`retrack`) instead
of erasing every ticket and all step history. That is an S-sized change buying
most of the severity reduction, which is why it does not wait for the ADR.

- [ ] `CORR-01` (root) — `registry.py:299-306`: `_load()` maps any unreadable or
      malformed registry to `[]`, and the next save wipes every ticket and all
      step history with only a `log.warning`. Fail closed: distinguish "no file"
      from "cannot read". *Verified directly.*
- [ ] `CORR-02` — **fix shape deferred to Phase 2 as an ADR; do not improvise
      it here.** `registry.py:161-169,308-312`: unlocked read-modify-write of
      the whole document through a shared fixed `grit_registry.tmp`. `_save` is
      atomic per write (`os.replace`); the read-modify-write cycle is not, and
      the temp path collides across writers. No `flock`/`fcntl` exists anywhere
      in `grit/`. Six steps can fire epilogues concurrently, and per Batch 0 the
      writer set spans every login and compute node over NFS.
      *Candidates for the ADR:* per-ticket append-only JSONL (borrowed pattern,
      report 07 — fits the existing fold-forward reader and removes the cycle
      entirely) vs locking (weak: NFS file locking is unreliable across
      implementations). One cheap interim mitigation that does not prejudge the
      ADR: give each writer its own temp path so concurrent writers cannot
      install a spliced file.
- [ ] `CORR-19` — `latest_run_dir` picks `success_runs[-1]` by append order in
      the registry, not by time. Depends on the storage decision above.
- [ ] `TEST-03` — no test opens two `RegistryManager`s on one path. Add the
      concurrency test; without it this batch cannot be shown to work.
- [ ] `SEC-03` — `~/.grit/` files written with default permissions; set `0600`.

*Batch done when:* a test proves a corrupt registry is not silently emptied, and
a test proves two concurrent writers do not lose a record.

---

## Batch 3 — truthful completion

Root cause: `success` is recorded from the scheduler's exit status, not from
verified outputs. Fixing the root deactivates the trigger for `DOM-01` in
Batch 4, so do this batch first.

- [ ] `CORR-03` (root) — `click_cli.py:228-251`: `state_update_cmd` passes the
      LSF-derived `status` straight to `tracker.finish()`; `outputs` is
      best-effort and, when empty, becomes `None` without downgrading the
      status. Rule to enforce: `success` requires outputs; empty outputs
      downgrade. *Verified directly.*
- [ ] `CORR-03b` — `grit/scripts/sex-matcher.sh:49` ends in an unconditional
      `exit 0`, so the step's success is unconditional: a permanently green row
      with no `Best_match` file, and the step's own resubmit guard then refuses
      to re-run it. *Verified directly.*
- [ ] `CORR-07` — `qv.py:80-96`: synchronous tracked step records `success` as
      soon as the submitting wrapper returns. No `job_id`, so bjobs recovery can
      never repair it.
- [ ] `CORR-08` — `hic_remapping.py:70-84`: the "already done, skipping" branch
      finalises a run as `success` from the mere existence of an output.
- [ ] `CORR-09` — four steps (`busco_curated.py:153`, `busco_synteny.py:119`,
      `fastga_synteny.py:108`, `sex_matcher.py:158`) call `_submit_bsub` outside
      any try/except after `tracker.start()`; a submission failure strands the
      record as `started` with no `job_id` and no recovery path but `untrack`.
- [ ] `CORR-11` — `pretext_to_asm_recurate.py:163-172`: the guard that should
      fail loudly on a missing recurate FASTA runs *after* the actions it was
      meant to prevent.
- [ ] `CORR-25` — when bsub's stdout lacks `Job <`, `_submit_bsub` returns that
      stdout as the job id; a non-numeric "job_id" then reaches the registry and
      `bjobs`.
- [ ] `CORR-18` — the epilogue rests on two unguarded assumptions: `sys.argv[0]`
      being a path valid on the compute node (see also Phase 2 / `PORT-02`), and
      `$LSB_JOBEXIT_STAT` being set.

*Batch done when:* a test proves an empty output glob cannot produce a `success`
record, for both the epilogue path and the synchronous-step path.

---

## Batch 4 — canonical resolution inputs

**The mtime-pool policy is sound and is not being changed** (report 06). Every
item here is about its *inputs*: what counts as a step's current output, and
what counts as finished.

- [ ] `DOM-06` (critical) — `--hap2` is not gated by `is_single_hap`, and the
      no-prefix fallbacks guard only the literal tokens `hap1`/`hap2`. On a
      `primary`/`alternate` ticket the resolvers return **hap1's** FASTA and
      chromosome list as `alternate`'s canonical files; `hic-remapping --hap2`
      then publishes hap1's Hi-C map to NFS as the alternate haplotype's.
- [ ] `DOM-02` (critical) — `latest_run_dir` falls back to `started` runs, so a
      half-written FASTA from an in-flight bsub job is the freshest pool member.
- [ ] `DOM-01` (critical) — when the newest successful run recorded no outputs,
      `get_output` substitutes an older run of the same step and the re-glob
      never fires; `143f425` covers the other half only. Re-check after Batch 3:
      the trigger should be gone, but the code path remains and should still be
      closed.
- [ ] `DOM-03` (critical) — the filesystem fallbacks of all three resolvers go
      through `find_latest_dir`, which never consults untracked status, so an
      `--untracked` run becomes canonical for fa, haplotigs *and* chr_list and
      is shipped by `finalize-qc`.
- [ ] `DOM-04` (critical) — `pending_jobs()` treats only `success`/`failed` as
      terminal, so untracking an in-flight run is silently reverted by the next
      `grit status` via `_resolve_gone_job`, which re-`finish`es it without
      `untracked=`. CLAUDE.md asserts this is impossible.
- [ ] `CORR-04` (critical) — `helpers.py:117` pre-seeds every job id as `"gone"`
      and never checks the subprocess return code, so a `bjobs` outage makes
      `_resolve_gone_job` finalise still-running jobs as success off partially
      written files. Also the reason grit silently pretends jobs finished on a
      non-LSF host. *Verified directly.*
- [ ] `CORR-05` (critical) — `pretext_to_asm.py:117`: curated AGP chosen by
      unsorted `glob.glob(...)[0]`; a stale AGP in the workdir
      non-deterministically builds the wrong curated FASTA. *Verified directly.*
- [ ] `DOM-07` — `haplotig-files` touches empty hap-prefixed placeholders into
      the `pretext_to_asm` run dir, where the re-glob and
      `find_canonical_haplotigs`' fallback prefer them over the real combined
      file beside them.
- [ ] `DOM-11` — `cleanup`'s keep-set excludes untracked runs, so the newest run
      dir is deleted while an older tracked one is kept, making `retrack`
      unrecoverable.
- [ ] `DOM-10` — `untrack` excludes only the named run dir, so canonical passes
      to an earlier run of the *same* step before any other pool member, not to
      "the next-freshest pool member" as the spec says (L147-149).
- [ ] `DOM-12` — the unrecorded-file credit matches `Path(path).parent ==
      run_dir`, so it misses steps whose outputs live in a subdirectory — i.e.
      the spec's "the two tables can't disagree" (L188-191) fails exactly for
      `blast_contaminants`.
- [ ] `DOM-14` — both `rename_and_orient` and `rename_and_orient_hap2` sit in
      the pool for every haplotype; cross-hap contamination is prevented only by
      their output keys happening to differ, not by any hap check.
- [ ] `DOM-16` — `_latest_tracked_output` stats candidates unguarded and
      `_resolve_canonical_files` catches only `FileNotFoundError`, so a stale
      NFS handle (`OSError`/ESTALE) crashes the resolver.
- [ ] `DOM-08` (plausible) — mtime is compared across files written by different
      clocks (login host vs compute node); a few seconds of negative skew
      reverses pool order. The run-dir ISO timestamps, all from one host, are
      never consulted.
- [ ] `DOM-09` (plausible) — the "already done" skip decides whether a curator's
      new curation round runs, from input-vs-output mtime alone, so any
      mtime-preserving copy of the AGP (`cp -p`, `rsync -a`, archive extraction)
      makes grit print "Already done", run nothing, and write no tracker record.
- [ ] `TEST-07` — `find_canonical_haplotigs` (86 LOC) has zero direct tests and
      is mocked out in all its consumers. Write them; `DOM-06`/`DOM-07` had
      nothing that could catch them.
- [ ] `CORR-23` — `grit retrack` promotes a run to `success` without checking
      that its recorded outputs still exist (see `DOM-11`).
- [ ] `CORR-24` (plausible) — `cleanup` keeps the latest run dir per step while
      canonical resolution picks by mtime across the pool, so cleanup can delete
      the canonical run.
- [ ] `CORR-26` (plausible) — run dirs keyed to whole-second timestamps with no
      uniqueness check.

*Batch done when:* the scenario traces in report 06 §"Scenario traces" are
encoded as tests and pass.

---

## Batch 5 — coherence at the release boundary

The one finding that ships a broken genome even when every individual resolver
is behaving.

- [ ] `DOM-05` (critical) — the three resolvers select independently with **no
      compatibility check anywhere**. `blast_contaminants` is excluded from the
      chr-list pool on the premise that contaminant filtering does not touch the
      chromosome list; false whenever a removed scaffold was a named chromosome.
      Confirmed by execution: fa from the decontaminated run, chr from
      `pretext_to_asm`. `finalize_qc` copies both in three independent loops
      with no cross-check.
- [ ] `CORR-06` (critical) — `finalize_qc.py:232-327`: a missing canonical FASTA
      is a `log.warning` + `continue`; missing haplotigs are `touch`ed empty;
      then `success` is recorded and the ticket advances to `post_processing`
      with an incomplete release directory.
- [ ] `DOM-15` — `recuration-canonical-priority.md` is accurate about everything
      it describes and documents none of the ways the answer can be wrong, so a
      curator has no reason to distrust it. Update alongside this batch; a stale
      spec on load-bearing logic is itself a defect.
- [ ] Spec conflict to resolve while here: the spec blesses an incoherent pair at
      L181-185 (rename-and-orient fa + newer recurate chr list), which is why
      the status display cannot distinguish a legitimate split from an
      incoherent one. Decide which pairs are legal before writing the check.

*Batch done when:* `finalize-qc` refuses to ship a set whose chromosome list
names scaffolds absent from the FASTA, and a test proves it.

---

## Batch 6 — reconcile-once — MOVED INTO PHASE 2 SCOPE

**Re-sequenced 2026-09-03. Do not do this before Phase 2; do it *as* Phase 2's
first structural task.** It was originally queued here, ahead of the ports
design, which was a mistake: report 07's borrowed pattern #1 requires completion
detection to live *inside* the executor contract, because a `SlurmExecutor` has
neither `-Ep` nor `bjobs`. "Collapse the four reconcile implementations into
one" and "design `ExecutionBackend`" are therefore the same piece of work.
Doing it here means doing it twice.

What still belongs to the remediation queue is only the *rules* the reconcile
path must obey — those are in Batch 3 and they survive the refactor, since the
rule moves location but not meaning.

Kept below as the specification of what Phase 2 must absorb.

- [ ] `ARCH-01` (critical) — "reconcile a finished LSF job with its outputs" is
      implemented four independent times with four different success criteria:
      `click_cli.py:230-249`, `registry.py:241-296`, `status.py:518-541`,
      `sex_matcher.py:99-128`. `rename_and_orient` sticks on `done (check)`
      forever via one path and `success` via another. Collapse to one.
- [ ] `ARCH-03` — step identity duplicated across six hand-maintained registries
      in five files (`STEP_MANIFESTS` 19, `STEP_TO_STATUS` 17, `_get_step_specs`
      map 14, `_SCP_TIP_STEPS` 6, `_STEPS_KEEP_LATEST` 7,
      `_DRY_RUN_SUPPORTED_COMMANDS` 24), already disagreeing: six tracked steps
      have no `STEP_MANIFESTS` entry (so `verify_outputs` returns `not_tracked`
      and `ARCH-01`'s recovery silently gives up), and `STEP_TO_STATUS` contains
      a phantom `agp_copied`. One source of truth + a consistency test.
- [ ] `CORR-10` / `CORR-13` — the same drift seen from the correctness side,
      plus three different assumed locations for `sex_matcher`'s output.
- [ ] `ARCH-19` — steps disagree on whether outputs live in `run_dir` or
      `workdir`, so `core` carries an `elif step == "sex_matcher":` branch. Make
      the location part of the step's declaration.
- [ ] `CORR-15` — one `grit status -t` applies two different and contradictory
      rules (`registry.py:290-292` vs `status.py:540-551`). Should fall out of
      `ARCH-01`.
- [ ] `ARCH-14` — `is_single_hap` reimplemented inline in `status.py:161`.
- [ ] `DOM-13` — the display layer re-implements the single-hap test and a
      partial copy of `_step_output`'s run-dir attribution rule, so it can drift
      from the resolvers it reports on. Keep the display thin.
- [ ] `ARCH-04` — `status.py`'s 286-line `show_ticket_history` does Jira I/O,
      `bjobs` polling, registry **writes** and table rendering in one function:
      `grit status` is not read-only. Separating the reconcile call out of it is
      most of the fix.

*Batch done when:* one reconcile implementation, one step registry, a test that
fails if a step is registered in one place and not another, and `grit status`
performs no registry writes.

---

## Batch 7 — before any publication (independent of everything else)

- [ ] `SEC-01` — `shlex.quote` appears zero times in 9,483 LOC of `shell=True`
      execution; `species` from Jira/YAML reaches the shell unquoted
      (`blast_contaminants.py:143`) or in weak double quotes
      (`find_reference.py:192`) — weak quotes still expand `$`, backticks and
      `$(...)`. Latent today; an RCE primitive against curators the moment a
      stranger can hand them a `--yaml`. **Must precede publication, not follow
      it.**
- [ ] `CORR-17` — Jira values (`customfield_11650`, `species`) interpolated
      verbatim into commands at `hic_remapping.py:108`, `find_reference.py:196`,
      `context.py:243-248`. Same class as `SEC-01` from the trusted-source side:
      an apostrophe in a species name is enough to break the command.
- [ ] `ARCH-08` — `_submit_bsub` builds `f'bsub… "{inner_cmd}"'` with one outer
      quote pair, so correct quoting is the caller's unwritten obligation: any
      legitimate double quote in `inner_cmd` silently truncates the job's
      command while bsub still reports success. Enforce it in code, not in
      institutional knowledge. (Batch 1's tests are what make this checkable.)
- [ ] `PKG-01` — `rename-and-orient` sourced from an unpinned git URL on a
      personal account via uv-only `[tool.uv.sources]`: unpublishable to PyPI,
      `pip install -e .` broken, and `uv.lock` pins `1.2.0` against a `>=1.2.2`
      constraint.
- [ ] `PKG-05` — `pymysql` declared and imported nowhere; two other declared
      deps unused. Also a hint of a credential surface to audit before a split.
- [ ] `PKG-06b` — CI never builds or installs the package, so nothing verifies
      that `grit/config/sanger_template.yaml` ships in the wheel.
- [ ] `PKG-07` — README and `examples.md` give mutually inconsistent install
      instructions.
- [ ] `DOC-03` — README mislabels `--print-only` as "Dry run" next to the real
      `--dry-run` flag; `--dry-run` (the strongest onboarding affordance in the
      project) is documented only in `CLAUDE.md`.
- [ ] `.gitignore` covers only `__pycache__` and `.worktrees/`; `.claude/` and
      `.superpowers/` are not covered.

---

## Batch 8 — cheap correctness cleanups (no ordering constraint)

Do these whenever a related file is open.

- [ ] `CORR-16` — `context.py:146`: `read_type = "hifi" if pacbio_read_type else
      "hifi"`. Tautology; the YAML field is effectively ignored.
      *Verified directly.*
- [ ] `CORR-14` — `_detect_assembly_type` can never return `paternal`, so every
      `paternal`/`maternal` branch is dead code that *looks* like support for
      those assembly types. Delete or implement.
- [ ] `CORR-20` — `except Exception: pass` swallows every parse error in
      `result_parsers.py:180-259`; the curator sees an incomplete summary and
      does not know why.
- [ ] `CORR-21` — the telomere track's awk program is mis-escaped
      (`add_pretext_view_tracks.py:143`, `92-97`, `62`).
- [ ] `ARCH-16` — two commands bypass `_run()`, so "all shell commands go
      through `_run`" is false. `cleanup._size_bytes` shells GNU-only `du -sb
      --apparent-size`, silently rendering every size as `?` off-farm;
      `post_processing.py:63` hand-rolls its own `print_only` guard and echo.
- [ ] `ARCH-11` — `CurationContext` is documented (and commented at
      `hic_remapping.py:172`) as frozen but is a plain mutable dataclass. Freeze
      it or fix the docs; one `ctx.workdir = …` would silently change the
      workdir for every later step of a composite command.
- [ ] `ARCH-12` — `--dry-run` precedence is derived twice (`base_command.py`
      pre-callback and `context.py:127`); `GlobalState` is assembled across
      three files.
- [ ] `ARCH-15` — the dry-run fixture writer exists twice; the recurate copy
      cannot express a 4-element "multi" spec and raises `ValueError` at dry-run
      time only.
- [ ] `ARCH-20` — `grit/__init__.py` re-exports private helpers (`_run`,
      `_submit_bsub`, …) as public surface; `grit/steps/__init__.py` eagerly
      imports all 21 step modules.
- [ ] `TEST-05` — mocking `_run` removes `check=True`, so every mock signals
      success and no test distinguishes "ran" from "succeeded";
      `CalledProcessError` is caught in exactly one place in all of `grit/`.
- [ ] `TEST-06` — `print_only` used as a de-facto test mode makes output-parsing
      logic unreachable by tests (e.g. `blast_contaminants` phylum parsing
      silently yielding `"Unknown"`).
- [ ] `TEST-10` — 45.7% duplicate non-trivial test lines; nine copy-pasted
      tracker fixtures under three names.
- [ ] `TEST-11`/`TEST-12`/`TEST-13` — CI: one unpinned Python against `>=3.10`,
      no coverage measurement, no dependency audit, smoke test not run.
- [ ] `PORT` (cheap subset) — `module load fastga/1.1-c1` pinned inside a
      bundled shell script, breaking `modules.py`'s stated single-source
      contract; the BUSCO lineage path embeds the mutable `latest` symlink in
      five places; the insect-prefix tuple is defined twice with different
      contents (`("ic","il","id","n")` vs `("ic","il","id")`); the curator
      download dir is `~/curations/work/{tol_id}/` in five places and
      `~/curations/{tol_id}/` in one; the haplotype alias table is duplicated
      five times and the fifth copy omits `paternal`/`maternal`.

---

## Scope decision — 2026-09-03

**The public core is all 21 steps except `post-processing`.** The
author rejected the narrower hypothesis (core = the 8 steps whose dependencies
are already public; `blast-contaminants`, `sex-matcher`, `find-reference`, the
microchromosome pair and `post-processing` left Sanger-distribution-only). Those
six steps are to be *adapted* for open source instead.

Consequence for Phase 2: `ToolProvider` is no longer an lmod-vs-pixi
abstraction. Six steps need **substitution**, which is four distinct kinds of
work and must be decided per step:

- **Vendor into the repo** — the microchromosome pair depends on
  `~dz11/…birds_microchromosomes/*.py`, which is the author's own code. Moving
  it into `grit/scripts/` removes the seam entirely. Easiest case.
- **Swap for a public equivalent** — `blast-contaminants` bottoms out in an
  unnamed BLAST `nt`-class database inside `~mh6/decon_fasta`. Needs a decision,
  not an abstraction: name the database and document how to obtain it, or move
  to a public contamination-screening tool.
- **Recover the data** — `sex-matcher` is driven by four BUSCO-ID lists in a
  third party's home directory with no recorded provenance. Either derivable
  from public BUSCO lineages (generate them) or manual curation work (needs
  release permission). Only `da16` can say which.
- **Reimplement from scratch** — `post-processing` invokes `post_process_rc`, a
  shell alias from a Sanger conf. No public equivalent, no substitution point,
  and **nobody in this repo knows what it does**. Phase 2 must carry it as an
  explicit placeholder with a documented contract, not a design.

New design element this forces, absent from the original plan: **per-step
capability declaration**. If every step must run off-Sanger, a step has to be
able to state "I require tool X and database Y; they are absent; here is how to
obtain them" and be checked before launch — rather than failing mid-run.
Today `sex-matcher` simply `exit 1`s on an unrecognised ToL-ID prefix.

**Author's answers, 2026-09-03** — these resolve most of the above:

- `blast-contaminants`: the database is **`core_nt`, held in RAM** for speed; an
  on-disk local mode is acceptable. So this is a *reimplementation with no
  behaviour change*, not a swap, and FCS-GX/ASCC become opt-in tiers.
- `sex-matcher`: the BUSCO ID lists **will be published**. No regeneration needed.
- `post-processing`: **stays Sanger-only for now** — the one exception to the
  scope decision above.
- microchromosome scripts: the author will **adapt them for open source**,
  including lifting out the embedded `bsub -K`.
- `find-reference`: the author can supply `get_nearest_comparator.rb`'s source;
  Ruby is not worth keeping, so the **algorithm gets ported, not reinvented**.

Remaining hard unknowns: what `post_process_rc` does (now blocks only
`grit-sanger`, not publication); which `core_nt` release today's runs used, since
nothing pins it.

## Deferred into Phase 2 (do NOT fix now)

These are real findings. Fixing them before the ports design means doing the
work twice, because Phase 2 moves the code they live in.

- `ARCH-02` — split `helpers.py` (937 LOC, seven responsibilities). Blocked
  anyway: it cannot be split until the import cycles are broken.
- Import cycles — three families (`click_cli ↔ steps.*` ×21, `helpers ↔
  steps.*`, `context ↔ registry ↔ helpers`), survivable only via function-local
  imports, with no test guarding them. Breaking them is Phase 2's first
  structural step and it fixes the ordering of everything else.
- `ARCH-05` — every step imports `build_context` from the CLI module, inverting
  the dependency direction; the "usable from notebooks" contract drags in
  `rich_click` and the whole command tree.
- `ARCH-09` — no step base class; 40 hand-written `tracker.start/finish` sites,
  28 identical Click wrappers, 20 inline `if ctx.dry_run:` blocks. The
  abstraction that removes this is part of the ports design.
- `ARCH-10` — domain operations (`retrack`, `_state-update`'s re-glob) living in
  Click command bodies, so they cannot be reused by the recovery paths.
- `ARCH-13` — `SystemExit(1)` in library code (29 sites); needs the domain-error
  hierarchy that the ports design introduces.
- `ARCH-18` — `finalize_for_qc` (258 LOC) and `setup.py` mixing orchestration
  with unrelated concerns.
- `TEST-02` — **the ordering constraint.** Move the test seam to injected
  collaborators *as part of* introducing the ports, not before and not after:
  147 `@patch` decorators target private module-level imports in 17 step
  modules, and ~123 tests fail on the patch target alone if the ports land
  first.
- `TEST-09` — the adapter conformance/contract suite. Cannot exist before the
  port contract does.
- All five ports and 125 seams (report 04): `ExecutionBackend` (24),
  `ToolProvider` (27), `MetadataSource` (16), `StorageLayout` (34),
  `ReleaseTarget` (11), plus 13 unclassified environment assumptions.
- `PORT-02` — completion detection welded to LSF's `-Ep` plus a `bjobs` sweep; a
  `SlurmExecutor` has neither. Report 07 calls this the real risk of Phase 2,
  not the abstraction itself. Completion detection must live *inside* the
  executor contract.
- `ARCH-06` / `PORT-03` — ~14 hardcoded absolute tool paths outside
  `modules.py`, four in individuals' home directories. Needs the config seam
  that Phase 2 designs (`UserConfig` has six fields, none for tool locations).
- `PORT-09` — `_derive_workdir` raising `ValueError` when `assembly/draft` is
  absent, making the ToL directory convention a hard precondition.
- `PORT-11` — ToL-ID-as-taxonomy driving control flow and indexing into an NFS
  tree.
- `PORT-12` — `post_process_rc` as a shell alias with no substitution point at
  all, gating a ticket's `done` state.
- `PORT-13` — release filenames governed by the out-of-repo
  `GritJiraIssue.get_curated_file_name_for_type()`, with code that guesses what
  it will look for.
- `PORT-19` — `module_cmd()` returns a fragment callers splice with `&&`, so a
  backend needing no preamble cannot return `""`.
- `ARCH-17` / `PKG-04` — `GritJiraIssue` via `sys.path.insert`: coupling *and*
  distribution problem; the `MetadataSource` port.
- `PORT-07`/`PORT-08` — the gaps that stop `--yaml` being a complete Jira-free
  path: `teloseq` obtainable only from `customfield_11650`,
  `gritjiraissue_path` required unconditionally, `--yaml` not threaded into
  `status`.
- Patterns to borrow (report 07): Nextflow-style four-verb executor contract with
  completion detection inside it; Snakemake-style unified rerun triggers
  (currently five hand-written staleness checks, and a `MODULE_VERSIONS` bump
  invalidates nothing — a correctness gap); Dagster-style named assets with an
  explicit `supersedes` edge (would have *prevented* `143f425`); retry/backoff.
- Declare the class-D hybrid intentional in CLAUDE.md: engines own within-step
  data flow, grit owns between-step human sequencing.
- `DOC-01`/`DOC-02` — human-facing architecture documentation, and something
  explaining what genome curation is. Write once the target architecture exists,
  or it needs rewriting immediately.

## Organisational — escalate, not code

Not blocked on any engineering above; start the conversations in parallel
because they have long latency.

- [ ] **`PKG-03` — no `LICENSE` of any kind.** Sanger IP policy decision. Gates
      everything else about publication.
- [ ] Licence and ownership of the five
      `/software/grit/projects/vgp_curation_scripts/*` scripts — **unknown**,
      and two look like vendored copies of public GPL-ish projects, which
      carries its own obligations.
- [ ] Consent from `mh6` / `da16`, whose home directory paths become public.
- [ ] Provenance and licence of the `~da16` sex-BUSCO ID lists.
- [ ] Whether disclosure of internal topology, the farm head hostname
      `tol22-head2` and three staff usernames is acceptable (`SEC-02`). If not,
      that is a history rewrite, not a file edit — note that the history is
      otherwise **clean of credentials** (359 commits scanned; no
      `git filter-repo` needed for secrets).
- [ ] `PKG-08` — citability: `CITATION.cff` + Zenodo DOI. For a research tool
      this is an adoption blocker, not a nicety.
- [ ] Maintainer and support commitment.
- [ ] The two hidden **data** dependencies, which matter more than any code: the
      unnamed BLAST `nt`-class database inside `~mh6/…/decon_fasta` (invisible
      from source; grit only sees `taxonomy.txt`), and the `~da16` BUSCO ID
      lists. Neither can be published or silently reproduced.
- [ ] `TODO/` is simultaneously the only written design-decision record and a
      set of internal planning notes, some in Russian. Decide what is published.

## Preserve — do not let a refactor eat these

Copied from `TODO/49` so it stays in front of whoever does the work.
`CurationContext` as an explicit value object; `RunTracker.start/finish`
enforcing `print_only` at the right layer; the `bsub -Ep` epilogue *concept*
(the fallbacks are what is broken, not the mechanism); `MODULE_VERSIONS` /
`module_cmd()` as the model for site-specific config; `--print-only` and
`--dry-run` as onboarding affordances (`grit --help` works with no config);
`collect_outputs()` / spec tuples; the `utils/output.py` +
`utils/result_parsers.py` split; the Keep-a-Changelog release discipline with
six matching tags; `recuration-canonical-priority.md` as a human-facing design
doc; and the mtime-pool canonical policy itself, which report 06 assessed as
sound and correct for this problem.
