# 06 — Canonical assembly resolution & step sequencing: domain-logic correctness

Read-only assessment of `find_canonical_fa` / `find_canonical_chr_list` /
`find_canonical_haplotigs`, `_step_output` / `_latest_tracked_output`, `RunTracker`,
`_canonical_mark`, and the step-sequencing behaviour around them, on branch
`test_and_fix_steps` (HEAD `9175121`). Verified against
`recuration-canonical-priority.md` claim by claim. Every trace below was either
read out of the code or **executed** against the real `RunTracker` /
`RegistryManager` / resolvers in a temp workdir (marked *confirmed*).

## Summary

**The mtime-pool design is the right call for this problem.** Every alternative
that was tried (tiered priority lists, an "unconditional top" step for recurate)
encodes an assumption about *order of intent* that a curator is free to violate,
and each one broke the moment a curator chained forward from recurate
(`TODO/done/44_*`). "Whichever of these steps you ran most recently for a
haplotype is canonical for it" is a rule a curator can hold in their head, it is
uniform across all pool members, and `grit untrack` is a coherent, uniform escape
hatch. The mtime *policy* is sound. The tie-break is deterministic and correct
(first-listed step wins; verified in `_latest_tracked_output`).

The defects are not in the policy — they are in the **inputs** to the policy:

1. **What counts as "a step's current output"** is decided by
   `RunTracker.get_output()`, which silently substitutes an *older run of the same
   step* whenever the newest successful run recorded no outputs at all. Commit
   `143f425` fixed the "outputs recorded but this key missing" case; the "no
   outputs recorded at all" case — which is exactly what the bsub epilogue
   produces when `collect_outputs` comes back empty — is still open (**DOM-01**,
   confirmed).
2. **A file being written right now counts as a finished output.** `_step_output`
   re-globs `latest_run_dir()`, which falls back to `status="started"` runs, so a
   half-written FASTA from an in-flight bsub job is the freshest thing in the pool
   (**DOM-02**, confirmed). grit is fire-and-forget, so this is one keystroke away.
3. **`--untracked` / `untrack` are not airtight.** The filesystem fallbacks
   (`find_curated_fa`, `find_canonical_haplotigs`'s glob) go through
   `find_latest_dir`, which prefers the alphabetically-last directory on disk and
   does not consult untracked status at all (**DOM-03**, confirmed). And untracking
   an in-flight bsub run is silently undone by the next `grit status`
   (**DOM-04**, confirmed) — CLAUDE.md explicitly claims this cannot happen.
4. **The three resolvers are independent by design and there is no cross-check
   whatsoever**, so an incompatible FASTA + chromosome-list pair is not merely
   possible, it is the *normal* outcome of the documented `blast-contaminants`
   path (**DOM-05**, confirmed).

**Definitive answer to the FASTA-vs-chr-list question: YES — a curator can and
routinely will ship a FASTA and a chromosome list from different, mutually
incompatible runs, and nothing in the codebase detects it.** See DOM-05 and
trace T6.

Findings: 6 critical, 4 major, 6 minor. The spec document itself is accurate on
everything it describes (the pool, the mtime rule, the tie-break, the per-type
status column) — its defect is *omission*: it documents none of the failure modes
above, so a curator reading it has no reason to distrust the answer.

---

## Spec-vs-implementation conformance

`recuration-canonical-priority.md`, claim by claim.

| # | Spec claim (line) | Code | Verdict |
|---|---|---|---|
| 1 | Everything is per haplotype; recurating hap1 doesn't affect hap2 (L9-12) | `_recurate_step_name` picks `pretext_to_asm_recurate` vs `_hap2` from `hap_prefix`; keys are `{hap_prefix}_fa` etc. | **Conforms.** Tested (`test_recurate_is_per_hap_independent`). |
| 2 | Pool = `pretext_to_asm, microchromosome_combine, blast_contaminants, rename_and_orient, rename_and_orient_hap2, pretext_to_asm_recurate[_hap2]` (L19-22) | `helpers.py:459-466` — identical, except only *this* haplotype's recurate step is in the pool (the `[_hap2]` notation covers that) | **Conforms.** But both `rename_and_orient` *and* `rename_and_orient_hap2` are in the pool for *every* haplotype — inert only because the specs are hap-keyed (DOM-14). |
| 3 | Freshest existing mtime wins outright (L24-26) | `_latest_tracked_output` compares `(st_mtime, -idx)` | **Conforms** — for whatever `_step_output` decides the step's file is. That decision is where the bugs live (DOM-01, DOM-02). |
| 4 | A tie (or a single candidate) goes to the first-listed step (L26-27) | `candidate[:2] > best[:2]` with `-idx`, iterating in list order | **Conforms**, deterministic. Tested (`test_pool_tie_break_favors_first_listed_step`). |
| 5 | "When that step's latest successful run recorded no such output key, its latest run dir is re-globbed … instead of dropping the step" (L29-36) | `_step_output` (`helpers.py:364-395`) | **Partially conforms.** True when the run recorded an outputs dict lacking the key. **False when the run recorded no outputs at all** — `get_output` then skips that run and returns an *older run's* path, which exists, so the re-glob never runs (DOM-01). |
| 6 | "otherwise … moving canonical *backwards* in time with nothing in `grit status` to show it" (L33-36) | same | **Still reachable** by the DOM-01 path, and worse: because it's the *same* step, the `Canonical` column shows nothing anomalous at all. |
| 7 | Fallback for fa: glob `{workdir}/rename_and_orient/`, then `find_curated_fa` (L38-40) | `helpers.py:468-482` — globs `rename_and_orient*` (also matches `rename_and_orient_hap2/`, harmless: filenames are hap-tokenised) | **Conforms** in effect. Undocumented: these fallbacks **ignore untracked status entirely** (DOM-03). |
| 8 | `find_canonical_chr_list` = same shape minus `blast_contaminants` (L42-44) | `helpers.py:594-601` | **Conforms.** The consequence — the contaminant-filtered FASTA is canonical while the *unfiltered* chromosome list stays canonical — is not documented anywhere (DOM-05). |
| 9 | `find_canonical_haplotigs` pool = `pretext_to_asm` + this hap's recurate, fallback = glob in latest `pretext_to_asm` run dir (L44-48) | `helpers.py:508-556` | **Conforms.** Zero direct unit tests. The fallback glob can return an empty placeholder created by `haplotig_files` (DOM-07) or an untracked run's file (DOM-03). |
| 10 | "whichever of these steps you ran most recently for a haplotype is canonical for it, full stop" (L50-52) | — | **Conforms as intent; violated in practice** by DOM-01 (a re-run whose outputs weren't captured), DOM-08 (compute-node clock behind the login node), and DOM-09 (the "already done" skip means "ran it" ≠ "it ran"). |
| 11 | No special case for recurate; re-running blast/rename after recurate makes that rerun canonical (L52-57) | confirmed by tests 284-350 and by trace T1 | **Conforms.** This is the design's main win and it works. |
| 12 | Step 2/3: "these steps replace the default canonical_fa" (L64-73) | — | **Conforms.** |
| 13 | Step 4: second-shot depends on the pretext-to-asm output, combine output becomes canonical (L76-88) | `microchromosome_second_shot.py:106-111` resolves fa **and** chr_list; `microchromosome_combine` records `hap1_fa`/`hap1_chr_list` | **Conforms.** Undocumented: second-shot consumes fa+chr from potentially *different* runs (same class as DOM-05). |
| 14 | Step 5 known limitation: blast after rename finds no `SCAFFOLD_N` headers, warns, copies unchanged (L96-104) | `_blast_contaminants_for_hap` returns `None` when the bed is empty → `outputs={}` → `finish(outputs=None)`; canonical is genuinely left alone | **Conforms, and better than documented** (it produces no output at all rather than an unfiltered copy). But that `outputs=None` finish is the DOM-01 trigger shape. |
| 15 | Step 6/8: recurate resolves the current canonical fa itself as input (L106-133) | `pretext_to_asm_recurate.py:136-140` | **Conforms.** |
| 16 | Recurate output "is now the freshest pool member … no special protection" (L134-138) | plus an explicit `FileNotFoundError` when no `{hap}_fa` was recorded (`pretext_to_asm_recurate.py:165-172`) | **Conforms, with an extra safety check the spec doesn't mention** — this is the *only* pool step that verifies its own canonical output landed. |
| 17 | `untrack --step <step>` marks that step's latest run non-canonical, "which lets the next-freshest pool member take over" (L142-151) | `RunTracker.untrack` + `_untracked_dirs` exclude only *that run_dir*, so an **earlier run of the same step** takes over first | **Diverges** (DOM-10). Also: untrack works on an in-flight (`started`) run and is then silently reverted (DOM-04). |
| 18 | Status column shows per-type `fa`/`hap`/`chr` codes with a 1-based hap index shown only when >1 haplotype (L157-164) | `_canonical_mark` + `_canonical_type_index` | **Conforms.** Well covered by `test_status.py`. |
| 19 | Recurate can own `hap`+`chr` while a later rename-and-orient owns `fa` — both correct (L166-185) | true, because `rename_and_orient` has no haplotigs spec | **Conforms.** |
| 20 | "both tables are computed from the same `_resolve_canonical_files` call, so they can't disagree" (L188-191) | `_canonical_mark`'s run-dir branch matches on `Path(p).parent == run_dir` | **Diverges** for any step whose outputs live in a *subdirectory* of the run dir — i.e. `blast_contaminants` (`{run_dir}/{hap}/…decontaminated.fa`) (DOM-12). |
| 21 | Flowchart (L195-226) | — | **Conforms** to the prose. |
| — | **Not in the spec at all** | `--untracked` runs; in-flight jobs; the "Already done → skip" behaviour of `pretext-to-asm`/recurate/`hic-remapping`; that fa and chr-list can come from different runs; that `cleanup` deletes non-canonical run dirs; `paternal`/`maternal` being unreachable | **Omissions** (DOM-15). |

---

## Scenario traces

`tolX` = tol_id, dual-hap `hap1/hap2` unless stated. "Expected" = what
`recuration-canonical-priority.md` promises a curator.

### T1 — the documented happy chain (baseline)
`pretext-to-asm` (t1) → `blast-contaminants` (t2, contaminants found) →
`pretext-to-asm-recurate` (t3) → `rename-and-orient` (t4).

- **Expected:** fa = rename output (t4); chr = rename output (t4); haplotigs =
  recurate's merged file (t3, since `rename_and_orient` has no haplotigs spec).
- **Actual:** identical. Verified by `test_rename_and_orient_after_recurate_with_newer_mtime_wins`
  and the pool composition.
- **Agree: yes.** `grit status` shows `pretext_to_asm_recurate → hap(1)` and
  `rename_and_orient → fa(1),chr(1)` — exactly the spec's L181-185 example.

### T2 — a re-run whose outputs were not captured (confirmed, DOM-01)
`pretext-to-asm` (t1, fa A) → `rename-and-orient` run 1 (t2, fa B recorded) →
`rename-and-orient` run 2 (t3, fa C written on disk; the bsub `-Ep` epilogue's
`collect_outputs` returns `{}` → `_state-update` records `success` with
`outputs=None`).

Why `collect_outputs` can come back empty for a *successful* rename-and-orient
run: its spec is `{tol_id}.{hap1}.*.fa` with `haplotigs` excluded, globbed
non-recursively in the run dir. Any of — the tool writing `.fasta`, writing into
a subdir, `--plot-alignments` changing the layout, an NFS attribute-cache lag at
epilogue time, or a `{tol_id}`/prefix mismatch — produces `{}`.

- **Expected (spec L24-36):** C is on disk in the step's latest run dir and is the
  freshest thing in the pool, so **fa = C**. The whole point of L29-36.
- **Actual:** `get_output("rename_and_orient","hap1_fa")` skips run 2 (no
  `outputs` key) and returns **B** from run 1. B exists → `_step_output` returns
  it and never re-globs. **fa = B (t2)** — a superseded assembly. Executed and
  confirmed.
- **Agree: NO.** And nothing in `grit status` hints at it: the row for run 2 says
  `success`, and the `Canonical` column marks *the run-1 row*, which a curator
  reading a table of same-named rows will not register as wrong. The next
  `hic-remapping` / `finalize-qc` uses B.

### T3 — downstream step launched while a bsub job is in flight (confirmed, DOM-02)
`pretext-to-asm` (t1, fa A) → `grit rename-and-orient` submits a bsub job (t2);
grit does not block, so the curator immediately runs `grit hic-remapping`.

- **Expected:** rename-and-orient has produced nothing yet, so **fa = A**;
  remapping runs against the curated assembly.
- **Actual:** `_step_output("rename_and_orient", …)` → `get_output` returns None
  (no success record) → `latest_run_dir` **falls back to the `started` run**
  (`run_tracker.py:176-186`) → the re-glob finds the FASTA the job is *currently
  writing*, mtime = now, freshest in the pool. **fa = the partially-written
  file.** Executed and confirmed.
- **Agree: NO.** `curationpretext` then remaps against a truncated FASTA. There
  is no size check, no completeness check, no "a job for this step is in flight"
  guard, and no error — the run just produces a Hi-C map for an assembly that
  never existed. If the job later fails, canonical silently reverts to A, so the
  bad map is the only surviving evidence.

### T4 — `--untracked` does not stay untracked (confirmed, DOM-03)
Curator runs `grit pretext-to-asm --untracked -t RC-x` to test an AGP without
disturbing canonical (the documented purpose of the flag), then later
`grit finalize-qc`.

- **Expected:** an untracked run is "non-canonical from the start"
  (`RunTracker.start` docstring) and `latest_run_dir` "never returns it".
- **Actual:** the tracker pool is empty (correctly), so all three resolvers fall
  through to their filesystem fallbacks, which call `find_latest_dir` —
  and that prefers *the alphabetically-last directory on disk*, untracked or not
  (`helpers.py:692-707`). **fa, haplotigs and chr_list all resolve into the
  untracked run dir.** Executed and confirmed (all three).
- **Agree: NO.** `finalize-qc` copies the experimental assembly into the curated
  release directory. Same mechanism makes `grit untrack -s pretext_to_asm`
  a no-op whenever it is the only `pretext_to_asm` run.

### T5 — untracking an in-flight run is undone by `grit status` (confirmed, DOM-04)
Curator submits `rename-and-orient`, realises it used the wrong reference, runs
`grit untrack -s rename_and_orient` (which succeeds — `untrack` accepts a
`started` run via `latest_run_dir`'s fallback), then runs `grit status`.

- **Expected (CLAUDE.md):** "the recovery paths that finish *without* `untracked`
  … only act on records with `status="started"`, which an untracked run never
  has."
- **Actual:** the run *does* have a `started` record (it was untracked *after*
  starting). `RunTracker.pending_jobs()` filters on `latest not in
  {"success","failed"}` — `"untracked"` is not in that set — so the run is
  returned. `grit status` → `RegistryManager.refresh_statuses` →
  `_refresh_pending_jobs` → `_resolve_gone_job` → `tracker.finish(step, run_dir,
  "success", outputs=…)` **with no `untracked=`** → the untracked marker is
  overwritten with `success` and the run becomes canonical again. Executed and
  confirmed end to end.
- **Agree: NO.** This is precisely the bug class CLAUDE.md and `TODO/tiny.md`
  claim is closed, reachable through the `untrack`-after-start door rather than
  the `--untracked`-from-start door.

### T6 — the FASTA/chr-list coherence question (confirmed, DOM-05)
`pretext-to-asm` (t1: fa A + chr list A′ listing SCAFFOLD_1…N) →
`blast-contaminants` (t2: contaminants found, decontaminated fa B with SCAFFOLD_7
removed) → `finalize-qc`.

- **Expected per spec:** "canonical_fa = the decontaminated FASTA" (L91-93). The
  spec says nothing about the chromosome list here, and deliberately excludes
  `blast_contaminants` from that pool (L42-44) because "contaminant filtering
  doesn't touch the chromosome list".
- **Actual:** `fa = B` (blast run), `chr_list = A′` (pretext_to_asm run).
  Executed and confirmed.
- **Agree: yes with the letter of the spec, NO with the domain requirement.**
  A′ still lists the scaffold that B no longer contains. `finalize-qc` copies
  both into the curated release dir (`finalize_qc.py:239` and `:281`) with no
  comparison of any kind. The premise "contaminant filtering doesn't touch the
  chromosome list" is wrong whenever a *removed* scaffold was a named chromosome
  — the two files are then inconsistent by construction, and this is the ordinary
  documented path, not an edge case.

### T7 — `--hap2` on a primary/alternate ticket fabricates hap2 from hap1 (confirmed, DOM-06)
Ticket YAML has a `primary` key → `hap1_prefix="primary"`,
`hap2_prefix="alternate"`, and `is_single_hap(ctx)` is **True**. pretext-to-asm
produced the unprefixed `tolX.1.primary.curated.fa` (the normal, matching case —
`_raise_if_yaml_pta_mismatch` does not fire). Curator runs
`grit hic-remapping --hap2` (or `grit rename-and-orient --hap2`) — neither command
gates `--hap2` on `is_single_hap`.

- **Expected:** the ticket has no second haplotype; the command should refuse.
- **Actual:** `find_canonical_fa(ctx, "alternate")` → tracker pool has no
  `alternate_fa`/`hap2_fa` → `rename_and_orient*` glob misses → `find_curated_fa`
  fallback #3 fires, because its guard is `hap_prefix not in ("hap1","hap2")` and
  `"alternate"` passes it → globs `{tol_id}.*.primary.curated.fa` → **returns
  hap1's FASTA as hap2's canonical FASTA.** `find_canonical_chr_list(ctx,
  "alternate")` does the same via its own no-prefix fallback. Executed and
  confirmed (both).
- **Agree: NO.** `hic-remapping --hap2` then builds a `hic_remapping_hap2` map
  from hap1's assembly, and `finalize-qc`'s hap2-map copy is gated only on
  "`hic_remapping_hap2` dir has any content" (`finalize_qc.py:295-302`), **not**
  on `is_single_hap` — so hap1's Hi-C map is copied to NFS as the alternate
  haplotype's map. `is_single_hap` gates the six sites CLAUDE.md names; the two
  `--hap2`-flag steps that resolve canonical per haplotype are not among them.

### T8 — `haplotig-files` placeholder outranks the real haplotigs (plausible, DOM-07)
Dual-hap. `grit post-curation` → `pretext-to-asm` then `haplotig-files` in one go.
pretext-to-asm's dual-hap haplotig output is the combined, unprefixed
`tolX.1.haplotigs.fa` (per `find_canonical_haplotigs`' own docstring), which no
`_OUTPUT_SPECS` haplotigs pattern matches — so `pretext_to_asm` records **no**
`hap1_haplotigs`. `haplotig-files` then `touch`es empty
`tolX.hap1.1.all_haplotigs.curated.fa` / `hap2…` into that same run dir
(`haplotig_files.py:88-96`).

- **Expected:** haplotigs = the real combined file.
- **Actual:** `_step_output` re-globs the run dir with pretext-to-asm's specs;
  `{tol_id}.{hap1}.*.all_haplotigs.curated.fa` now matches the **empty
  placeholder**, which wins (and the L44-48 fallback glob tries hap-specific
  patterns before the no-prefix combined one, so it picks the same empty file).
- **Agree: NO** — if pretext-to-asm's dual-hap haplotig output really is named
  `*.haplotigs.fa`. I could not verify the external tool's naming from this repo,
  hence *plausible*. If it holds, `finalize-qc` ships a 0-byte haplotigs FASTA
  with the real haplotigs sitting beside it in the same directory.

### T9 — compute-node clock behind the login node (plausible, DOM-08)
`pretext-to-asm` runs **synchronously on the submit/login host** (`_run`, no
bsub) at t=12:00:00. `rename-and-orient` runs **on a compute node** via bsub and
writes its FASTA at compute-node-local 11:59:40 (a 20 s negative skew, well within
what an un-NTP'd or leap-smeared node exhibits; the file lands on Lustre/NFS with
the *writer's* clock).

- **Expected:** rename-and-orient ran last, so fa = its output.
- **Actual:** its mtime is 20 s *older* than the pretext-to-asm FASTA, so
  `pretext_to_asm` keeps the fa slot. Undetected: nothing compares mtimes against
  run-dir names (which *are* submit-host ISO timestamps and would be a consistent
  clock), and nothing warns when the newest-*started* pool member is not the
  newest-*mtime* one.
- **Agree: NO.** The one genuine mitigation: `grit status`'s `Canonical` column
  puts `fa(1)` on the `pretext_to_asm` row rather than the `rename_and_orient`
  row, so an attentive curator *can* see it. That is a real virtue of the
  per-type column and worth keeping in mind when judging the design.

### T10 — `scp -p` of a recuration AGP silently skips the recuration (plausible, DOM-09)
Round 1 recurate finished at t3. Curator curates the remapped map locally, then
copies the new AGP with `scp -p` (or `cp -p`, or `rsync -a` — all preserve mtime)
into `{workdir}/recurate/`; the AGP's local mtime is t2 (it was saved before t3,
or the laptop clock is behind).

- **Expected:** recurate runs on the new AGP; its output becomes canonical.
- **Actual:** `_run_pretext_to_asm_core`'s guard calls
  `inputs_newer_than_curated_fa(...)` → `max(input mtimes) > min(curated fa
  mtimes)` is false → logs "Curated FASTA already exists — skipping", prints
  `Already done → <prev run dir>`, **writes no new tracker record**, and returns
  the previous run dir. Canonical is unchanged.
- **Agree: NO.** The curator's second round of manual curation is silently
  discarded; `grit status` shows a recurate `success` (the old one) and correct
  canonical marks. This skip behaviour is documented nowhere in
  `recuration-canonical-priority.md`, which tells the curator step 8 is simply
  "run `grit pretext-to-asm-recurate`". Same guard shape in `hic_remapping`
  (`hic_remapping.py:48-83`).

---

## mtime failure modes

For each vector: can it make mtime lie, does the code detect it, what does the
curator see?

| Vector | Can it lie? | Detected? | Curator observes |
|---|---|---|---|
| **Clock skew, submit host vs compute node** (login-host `pretext_to_asm` vs bsub'd `rename_and_orient`) | Yes — the writer's clock stamps the file; a negative skew of seconds is enough | **No.** No skew check, no comparison against the run-dir ISO timestamp | `Canonical` column marks the *older* step's row. Visible if read carefully; no warning. (T9, DOM-08) |
| **`cp` vs `mv` vs `rsync`** inside grit | `cp` (no `-p`) → mtime=now (correct); `mv` within a filesystem preserves mtime — `blast_contaminants` `mv`s `<canonical>_cleaned` → `…decontaminated.fa`, but that file was just written, so the preserved mtime is still "now" | N/A — benign today | Nothing. Fragile: adding `cp -p`/`rsync -a` anywhere in a pool step would break ordering silently |
| **`cp -p` / `scp -p` / `rsync -a` of an *input*** (the AGP) | Yes | **No** — and worse, it flips the "already done" skip the wrong way | "Already done → …"; the curation round is discarded (T10, DOM-09) |
| **`touch`** on any pool output | Yes — instantly makes any file canonical | No | Silent. Arguably a feature (a manual escape hatch), but undocumented |
| **Re-write in place by a re-run** | Steps write into fresh timestamped run dirs, so in-place rewrite is not normal. `blast_contaminants` *does* write its `_cleaned` intermediate into another step's run dir; the name doesn't match any spec glob, so it can't be picked up | Not needed | — |
| **Equal mtimes (same granularity tick)** | Yes on 1-second-granularity mounts (NFSv3, some Lustre configs) | **Deterministic**: first-listed step wins (`-idx` tie-break) — i.e. `pretext_to_asm` beats everything, `microchromosome_combine` beats `blast_contaminants`. Correct per spec, but note the tie-break favours the *semantically earlier* step, so a genuine same-tick pair resolves *backwards* | Nothing visible. Low practical risk (steps are minutes apart), but a chained command on a coarse-granularity mount could hit it |
| **Partially-written file globbed mid-write** | Yes — mtime is now, content is truncated | **No.** No size, no `.fa` sanity check, no in-flight-job guard; `latest_run_dir` deliberately returns `started` runs | Nothing at all until a downstream tool errors on a short FASTA (T3, DOM-02) — **the most dangerous vector** |
| **Interrupted job leaving a truncated FASTA** | Yes: a `TERM_MEMLIMIT` kill mid-write leaves a truncated file. The epilogue records `failed`, so `get_output` skips it — **but** `latest_run_dir` returns the last `success` *or* the last `started`, and if the epilogue never fired (LSF restart, `grit` not on the node's `$PATH`) the run stays `started` forever and its truncated file stays canonical | Partially: `grit status`'s bjobs recovery calls `verify_outputs` (presence-only, no size) before finishing as success; `pretext_to_asm_recurate` is the only step that verifies its own canonical output exists | `grit status` shows `running` indefinitely (or `unknown (gone)`); canonical silently points into the dead run |
| **File deleted between `exists()` and `stat()`** (concurrent `grit cleanup`, NFS ESTALE) | — | `_latest_tracked_output` calls `p.stat()` unguarded. `FileNotFoundError` is caught by `_resolve_canonical_files`; a bare `OSError` (ESTALE) is **not** | `grit status` traceback (DOM-16) |

The honest summary: mtime is a *good enough* ordering signal for a
single-curator, single-filesystem workflow, and the design correctly refuses to
encode step priority. Its two real weaknesses are (a) it cannot distinguish
"finished" from "being written", and (b) it trusts a clock that is not the same
clock for every pool member.

---

## Cross-resolver coherence

**Question: can a curator end up with a FASTA from one run and a chromosome list
from a different, incompatible run, such that the chr list references scaffolds
absent from the FASTA?**

**Answer: yes — confirmed by execution, and it is the ordinary outcome of the
documented `blast-contaminants` path, not an edge case. There is no cross-check
of any kind, anywhere.**

The three resolvers are independent by construction, and CLAUDE.md is right that
this is *intentional* and *necessary*: the pools genuinely differ
(`rename_and_orient` produces fa+chr but never haplotigs; `blast_contaminants`
produces fa only), so forcing all three to come from one run would be strictly
wrong. The status column's per-type marks exist precisely to make the split
legible. That part of the design is correct.

What is missing is any notion of **compatibility** between the independently
chosen files. Concretely:

1. **fa from `blast_contaminants` + chr list from `pretext_to_asm`** (T6,
   confirmed). Removing a contaminant scaffold that happens to be a named
   chromosome leaves the chromosome list naming a scaffold the FASTA no longer
   contains. `blast_contaminants` is excluded from the chr-list pool *by design*
   (spec L42-44) on the premise that contaminant filtering doesn't touch the
   chromosome list — a premise that is false exactly when it matters.
2. **fa from `pretext_to_asm` + chr list from `rename_and_orient`** — reachable
   whenever a rename-and-orient run records its chr list but not its fa (DOM-01's
   partial-capture shape, one key instead of none). The FASTA then has
   `SCAFFOLD_n` headers while the chromosome list carries renamed chromosome
   names: no name in the list matches any header in the FASTA.
3. **fa from `rename_and_orient` + chr list from a newer `pretext_to_asm_recurate`**
   — the spec *explicitly blesses* this combination (L181-185: "rename-and-orient
   ran, but an even newer recurate round still owns the chromosome list"). Those
   two files describe different scaffold sets (the recurate round changed the
   assembly *after* the rename), so the blessed example is itself an incoherent
   pair.

Consumers: `finalize_qc.py:239/251/281` calls the three finders in three
independent loops and `cp`s each result into the curated release directory — no
comparison, no header/name check, no warning. `microchromosome_second_shot.py:106-111`
resolves fa+chr independently and feeds both to the splitting script.
`_resolve_canonical_files` (status) also resolves them independently, so
`grit status` *displays* the mismatch (different rows marked `fa` and `chr`) but
never flags it as a problem — and a curator has no reason to read two marks on
two different rows as an error, since the spec teaches them that exactly that is
correct and expected.

So: no cross-check exists, the display cannot distinguish a legitimate split from
an incoherent one, and the release step ships whatever it is handed.

---

## Step-sequencing hazards

**Is there a legal step order?** No — and that is deliberate. There is no state
machine, no precondition graph, no "you must run X before Y". Each step
independently resolves the inputs it needs and raises `FileNotFoundError` if they
are absent. `STEP_TO_STATUS` (`manifests.py:92-111`) maps a step to a Jira-facing
status label but never *gates* anything. `require_workdir(ctx)` is the only
ordering guard, and it only asserts that `setup` has run. Given that a curator
legitimately loops (curate → remap → recurate → remap …) and legitimately skips
optional steps, "any step, any time" is the right call; the cost is that every
hazard below is reachable.

- **Re-running a step that already succeeded.** `pretext-to-asm`,
  `pretext-to-asm-recurate` and `microchromosome-combine` share
  `_run_pretext_to_asm_core`'s skip: if the previous run dir holds a
  `{tol_id}*.curated.fa` and no input is newer, the step **no-ops**, prints
  "Already done", writes no tracker record, and canonical is unchanged. Safe when
  the mtime comparison is right, silently wrong when it isn't (T10/DOM-09).
  `hic-remapping` has the same shape keyed on the remapped pretext's mtime.
  `rename-and-orient` and `blast-contaminants` have **no** skip and always
  re-run — so re-running them always moves canonical, matching the spec.
- **Downstream step while an upstream bsub job is in flight.** No guard, no
  blocking, no "job pending for this step" check. The in-flight run dir is
  returned by `latest_run_dir` and its partial files are eligible as canonical
  (T3/DOM-02). This is the single sharpest edge in the system: fire-and-forget
  plus "freshest file wins" plus "in-flight counts as latest".
- **Interleaving a recurate with an in-progress step.** `pretext-to-asm-recurate`
  calls `find_canonical_fa` for its *input*, so a recurate launched while
  `rename-and-orient` is still writing will consume the partial FASTA (same
  mechanism as T3) — and it *is* guarded on the output side
  (`pretext_to_asm_recurate.py:165-172` raises if no `{hap}_fa` was recorded),
  which is more than any other step does.
- **`untrack` / `retrack` mid-chain.**
  - Untracking a *completed* run works and is the intended escape hatch, but it
    hands canonical to an **earlier run of the same step** before considering
    other pool members (DOM-10) — the spec says "the next-freshest pool member".
  - Untracking an *in-flight* run appears to work and is reverted by the next
    `grit status` (T5/DOM-04).
  - CLAUDE.md's reasoning ("an untracked run never has `status='started'`") holds
    only for `--untracked`-from-start; it does not hold for `untrack`-after-start.
  - `retrack` restores `outputs` from the untracked record, or from an earlier
    `success` record for the same run dir — fine, unless `cleanup` deleted the
    files meanwhile (DOM-11), in which case retrack reports success and changes
    nothing resolvable.
- **`grit cleanup` deleting a run dir canonical points at.** `_STEPS_KEEP_LATEST`
  keeps only `tracker.latest_run_dir(step)` per step for `pretext_to_asm`,
  `hic_remapping[_hap2]`, `rename_and_orient`, `fastga`, `find_reference`, `qv`,
  and deletes every other run dir. `latest_run_dir` **excludes untracked runs**,
  so an untracked *newest* run dir is deleted while the older tracked one is kept
  (DOM-11) — data loss for the run the curator explicitly asked grit not to
  touch, and `retrack` can no longer recover it. Deleting a dir that canonical
  currently points at is otherwise self-healing (`_step_output` checks
  `exists()` and re-globs), but `rename_and_orient_hap2`, `blast_contaminants`,
  `microchromosome_combine` and both recurate steps are absent from the list, so
  cleanup is asymmetric between haplotypes.
- **`grit remove`** deletes the workdir and the registry entry wholesale behind a
  typed confirmation; the curated release directory is untouched. Not a canonical
  hazard.
- **`--dry-run`** isolates registry + workdir under `~/.grit/dry_run/` and does
  exercise the tracker/canonical paths, which is genuinely valuable. It cannot
  reproduce DOM-01 (dry-run branches always pass a populated `outputs`), DOM-02
  (nothing is in flight), or DOM-08/09 (no clock skew, no `scp`).

---

## Test coverage of this logic

`tests/test_helpers_canonical.py` (506 lines, 26 tests) and
`tests/test_status.py` (956 lines) are genuinely good where they reach. They
cover the *policy*; they do not cover the *inputs to the policy*.

**Covered:**
- Full pool ordering for `find_canonical_fa`: every pairwise "X beats Y" among
  `pretext_to_asm` / `microchromosome_combine` / `blast_contaminants` /
  `rename_and_orient`, both directions, with explicit `os.utime` control.
- Re-run-wins semantics after a recurate (`*_after_recurate_with_newer_mtime_wins`
  × 3) — the L50-57 claim, the design's core.
- Tie-break favouring the first-listed step.
- `untrack` fallback for `blast_contaminants`, `microchromosome_combine`,
  `rename_and_orient`, `pretext_to_asm_recurate`.
- Per-hap recurate independence and the `_hap2` step-name choice.
- `find_curated_fa`'s unprefixed fallback: *must not* fire for a dual-hap prefix,
  *must* fire for `primary`.
- The `143f425` fix, in exactly its fixed shape: latest run recorded an outputs
  dict **containing other keys but not this one** → re-glob wins
  (`test_chr_list_from_newer_run_dir_wins_when_output_key_was_not_recorded`,
  `test_chr_list_of_latest_run_beats_earlier_run_of_the_same_step`).
- `RunTracker` untracked semantics: `get_output` skips untracked,
  `start(untracked=True)` never canonical, `finish(untracked=True)` keeps the
  marker, promotion, undo.
- `_canonical_mark`: per-type marks, hap indices, the recurate-vs-rename
  simultaneous-canonical case, the unrecorded-file-in-run-dir credit, and that a
  canonical file in *another* run dir must not mark the row.

**Not covered (each maps to a finding):**
- **DOM-01** — latest successful run recorded **no outputs at all**
  (`finish(outputs=None)`). Every existing test passes a non-empty dict. This is
  the one-line gap between the tested fix and the untested residue.
- **DOM-02** — `_step_output` re-globbing a run whose only record is `started`
  (in-flight). No test creates a `started`-only pool run.
- **DOM-03** — the *filesystem fallbacks* with an untracked run on disk. Tests
  exercise the fallbacks only when nothing is tracked at all, never when the only
  run is untracked.
- **DOM-04** — `pending_jobs()` / `_refresh_pending_jobs` on a run that was
  untracked *after* starting. `test_pending_jobs_returns_started_with_job_id`
  covers the plain case only.
- **DOM-05** — no test asserts anything about fa and chr_list being mutually
  consistent; no test resolves both in one scenario and compares provenance.
- **DOM-06** — no test calls any canonical resolver with `hap2_prefix` on a
  `primary`/`alternate` context. `mock_ctx_primary` is used once, for hap1 only.
- **`find_canonical_haplotigs` has zero direct unit tests.** It appears in the
  test suite only as a `@patch` target (`test_pretext_to_asm_recurate.py`,
  `test_post_curation.py`). Its pool, its mtime comparison, its three-tier glob
  fallback, the `hap_prefix == ctx.hap1_prefix`-only no-prefix branch, and the
  interaction with `haplotig_files`' empty placeholders (DOM-07) are all
  untested — for the resolver that decides which haplotig file gets *shipped*.
- **DOM-08 / DOM-09** — no clock-skew or mtime-preserving-copy scenario; no test
  of the `inputs_newer_than_curated_fa` skip with an input *older* than the
  previous output.
- **DOM-10** — no test distinguishes "untrack hands over to an earlier run of the
  same step" from "untrack hands over to another pool member".
- **DOM-11** — `test_cleanup.py` does not cover an untracked newest run dir.
- **DOM-12** — `_canonical_mark` is never tested with a canonical path in a
  *subdirectory* of the run dir (the `blast_contaminants` layout).
- Equal-mtime ties are tested; ties on a 1-second-granularity filesystem across a
  chained command are not (and probably can't be, in-process).

---

## Findings

**DOM-01** | severity: critical | confidence: confirmed
| `grit/core/run_tracker.py:188-202` (`get_output`), consumed by `grit/utils/helpers.py:378-384`
| claim: When a step's newest successful run recorded no outputs at all, `get_output` silently returns an **older run of the same step**, and because that path exists `_step_output` never re-globs — so the `143f425` "canonical can't move backwards" fix does not cover the `finish(outputs=None)` case that the bsub epilogue produces.
| failure scenario: `pretext-to-asm` (fa A) → `rename-and-orient` run 1 (fa B, recorded) → `rename-and-orient` run 2 writes fa C but its `-Ep` epilogue's `collect_outputs` returns `{}` (spec glob miss / NFS attribute lag) so `_state-update` records `success` with `outputs=None` → `find_canonical_fa` returns **B (run 1's superseded FASTA)** instead of C; `hic-remapping` and `finalize-qc` then use B. `grit status` shows run 2 `success` and marks run 1's row canonical.
| effort: S | blast radius: cross-module
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**DOM-02** | severity: critical | confidence: confirmed
| `grit/core/run_tracker.py:176-186` (`latest_run_dir` `started` fallback) + `grit/utils/helpers.py:386-395`
| claim: A file being written *right now* by an in-flight bsub job is eligible as canonical, because `_step_output` re-globs `latest_run_dir()` and that falls back to `status="started"` runs, with no completeness, size or job-state check.
| failure scenario: `pretext-to-asm` (fa A) → `grit rename-and-orient` submits a bsub job → grit returns immediately (fire-and-forget) → curator runs `grit hic-remapping` in the same minute → `find_canonical_fa` returns the **half-written `tolX.hap1.primary.renamed.fa`** (mtime = now, freshest in the pool) → `curationpretext` remaps against a truncated assembly and the curator curates a Hi-C map of an assembly that never existed.
| effort: S | blast radius: module
| debt quadrant: inadvertent-reckless
| open-source impact: friction

**DOM-03** | severity: critical | confidence: confirmed
| `grit/utils/helpers.py:692-707` (`find_latest_dir`), reached from `helpers.py:468-482`, `:518-556`, `:606-637`
| claim: The filesystem fallbacks of all three resolvers go through `find_latest_dir`, which prefers the alphabetically-last directory on disk and never consults untracked status — so an `--untracked` run is canonical for fa, haplotigs *and* chr_list whenever it is the only run of its step.
| failure scenario: curator runs `grit pretext-to-asm --untracked -t RC-x` to test an experimental AGP → tracker pool is (correctly) empty → `find_curated_fa` / the haplotigs glob / the chr-list glob all resolve into the **untracked run dir** → `grit finalize-qc` copies the experimental FASTA, haplotigs and chromosome list into the curated release directory. Same mechanism makes `grit untrack -s pretext_to_asm` a no-op when there is one `pretext_to_asm` run.
| effort: S | blast radius: module
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**DOM-04** | severity: critical | confidence: confirmed
| `grit/core/run_tracker.py:213-233` (`pending_jobs`) + `grit/core/registry.py:271-297` (`_refresh_pending_jobs` / `_resolve_gone_job`)
| claim: `pending_jobs()` treats only `success`/`failed` as terminal, so a run untracked *after* it started is still reported as pending, and the recovery path re-`finish`es it without `untracked=` — clobbering the untracked marker with `success` and making it canonical again. CLAUDE.md asserts this is impossible.
| failure scenario: curator submits `rename-and-orient` with the wrong reference, runs `grit untrack -s rename_and_orient` (accepted — `untrack` falls back to the `started` run), then runs `grit status` → `_refresh_pending_jobs` → `_resolve_gone_job` → `finish(step, run_dir, "success", outputs=…)` → the **wrongly-referenced renamed FASTA is canonical again**, and the next `hic-remapping`/`finalize-qc` uses it.
| effort: S | blast radius: cross-module
| debt quadrant: inadvertent-reckless
| open-source impact: friction

**DOM-05** | severity: critical | confidence: confirmed
| `grit/utils/helpers.py:594-601` (chr-list pool excludes `blast_contaminants`) + `grit/steps/post_curation/finalize_qc.py:236-286`
| claim: The three resolvers select independently with **no compatibility check anywhere**, so `finalize-qc` routinely ships a FASTA and a chromosome list from different, mutually inconsistent runs.
| failure scenario: `pretext-to-asm` (fa A + chr list A′ naming SCAFFOLD_1…N) → `blast-contaminants` removes SCAFFOLD_7 (a named chromosome) producing fa B → `grit finalize-qc` copies **B** as the curated assembly and **A′** as the chromosome list, so the shipped chromosome list names a scaffold absent from the shipped FASTA. Reachable identically for the FASTA/chr-list pair the spec itself blesses at L181-185 (rename-and-orient fa + newer recurate chr list).
| effort: M | blast radius: cross-module
| debt quadrant: deliberate-prudent (independent pools are correct) shading into inadvertent-reckless (no coherence check at the release step)
| open-source impact: blocker

**DOM-06** | severity: critical | confidence: confirmed
| `grit/utils/helpers.py:337-347` (`find_curated_fa` fallback #3) + `grit/utils/helpers.py:625-635` + `grit/steps/optional/rename_and_orient.py:200-225`, `grit/steps/post_curation/hic_remapping.py:94`, `grit/steps/post_curation/finalize_qc.py:295-302`
| claim: `--hap2` is not gated by `is_single_hap`, and the no-hap-prefix fallbacks guard only against the literal tokens `"hap1"/"hap2"` — so on a `primary`/`alternate` ticket the resolvers hand back **hap1's** FASTA and chromosome list as `"alternate"`'s canonical files, fabricating a second haplotype.
| failure scenario: `primary`-key ticket (`is_single_hap` is True) whose pretext-to-asm produced the unprefixed `tolX.1.primary.curated.fa` → curator runs `grit hic-remapping --hap2` → `find_canonical_fa(ctx,"alternate")` falls through to `find_curated_fa`'s fallback #3 (`"alternate" not in ("hap1","hap2")` passes the guard) and returns **`tolX.1.primary.curated.fa`** → a `hic_remapping_hap2` map is built from hap1's assembly → `finalize-qc`'s hap2-map copy is gated only on "that dir has content", not on `is_single_hap`, so **hap1's Hi-C map is published to NFS as the alternate haplotype's map**. `grit rename-and-orient --hap2` does the same for the FASTA. (Also: `_detect_assembly_type` can never return `paternal`, so the `paternal`/`maternal` branches in `is_single_hap`, `find_curated_fa`'s alias map and `find_canonical_*` are dead code, and a paternal/maternal YAML raises `ValueError`.)
| effort: M | blast radius: cross-module
| debt quadrant: inadvertent-reckless
| open-source impact: friction

**DOM-07** | severity: major | confidence: plausible
| `grit/steps/post_curation/haplotig_files.py:88-96` + `grit/utils/helpers.py:518-556`
| claim: `haplotig-files` `touch`es empty hap-prefixed `all_haplotigs.curated.fa` placeholders **into the `pretext_to_asm` run dir**, where both `_step_output`'s re-glob and `find_canonical_haplotigs`' hap-specific-first fallback prefer them over the real combined haplotigs file sitting beside them.
| failure scenario: dual-hap `grit post-curation` → pretext-to-asm writes the combined `tolX.1.haplotigs.fa` (which no `_OUTPUT_SPECS` haplotigs pattern matches, so `hap1_haplotigs` is never recorded) → `haplotig-files` creates empty `tolX.hap1.1.all_haplotigs.curated.fa` / `tolX.hap2.1.…` in that same dir → `find_canonical_haplotigs` returns the **0-byte placeholder** → `grit finalize-qc` ships empty haplotigs while the real haplotigs remain in the workdir. Confidence is *plausible* only because pretext-to-asm's actual dual-hap haplotig filename could not be verified from this repo; the resolver's own docstring asserts it.
| effort: M | blast radius: module
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**DOM-08** | severity: major | confidence: plausible
| `grit/utils/helpers.py:397-419` (`_latest_tracked_output`)
| claim: mtime is compared across files written by *different clocks* — synchronous steps stamp with the login host's clock, bsub'd steps with the compute node's — so a negative skew of a few seconds silently reverses the pool order, and nothing detects it (the run-dir ISO timestamps, which all come from the submit host, are never consulted).
| failure scenario: `grit pretext-to-asm` runs in-process on the login host at 12:00:00 (fa A) → `grit rename-and-orient`'s bsub job writes fa B on a node whose clock is 20 s behind → B's mtime is older than A's → `find_canonical_fa` keeps **A**, so `finalize-qc` ships the un-renamed, un-oriented assembly. Curator's only clue is `fa(1)` sitting on the `pretext_to_asm` row in `grit status`.
| effort: L | blast radius: module
| debt quadrant: deliberate-prudent (mtime is the right ordering key for this workflow; the skew exposure is an accepted cost)
| open-source impact: friction

**DOM-09** | severity: major | confidence: plausible
| `grit/utils/helpers.py:248-278` (`inputs_newer_than_curated_fa`) + `grit/steps/post_curation/pretext_to_asm.py:75-92`
| claim: The "already done" skip in `_run_pretext_to_asm_core` (and the analogous one in `hic_remapping`) decides whether a curator's *new* curation round runs, based purely on input-vs-output mtime — so any mtime-preserving copy of the AGP makes grit silently discard the round, writing no tracker record and printing "Already done".
| failure scenario: recurate round 1 finished at t3 → curator curates the remapped map, copies the new AGP with `scp -p` into `{workdir}/recurate/` (preserved mtime t2 < t3) → `grit pretext-to-asm-recurate` prints "Already done → <round-1 dir>", returns, and **canonical stays the round-1 assembly**; `grit status` looks entirely healthy. Not documented in `recuration-canonical-priority.md`, which tells the curator step 8 is simply "run the command".
| effort: M | blast radius: module
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**DOM-15** | severity: major | confidence: confirmed
| `recuration-canonical-priority.md` (whole document)
| claim: The spec is accurate about everything it describes but documents none of the ways the answer can be wrong, so a curator has no reason to distrust it — and a stale/incomplete spec on load-bearing logic is itself a defect.
| failure scenario: a curator following the document runs `grit pretext-to-asm-recurate` after `scp -p`-ing an AGP, sees "Already done", believes (per L128-140) that "canonical_fa = the recurate output", and runs `finalize-qc` — shipping round 1. The document never mentions: the "already done" skip; that `--untracked` runs can still win via the filesystem fallbacks (DOM-03); that an in-flight job's partial output can be canonical (DOM-02); that fa and chr_list can be mutually incompatible (DOM-05, while L181-185 actively presents such a pair as correct); that `grit cleanup` deletes non-canonical run dirs (DOM-11); or that `--hap2` on a primary/alternate ticket resolves hap1's files (DOM-06). Its L188-191 claim that the two status tables "can't disagree" is false (DOM-12), and its L142-151 description of `untrack` is imprecise (DOM-10).
| effort: M | blast radius: cross-module
| debt quadrant: inadvertent-prudent
| open-source impact: blocker

**DOM-10** | severity: minor | confidence: confirmed
| `grit/core/run_tracker.py:31-41` (`_untracked_dirs`) + `grit/core/click_cli.py:311-325`
| claim: `untrack` excludes only the named *run dir*, so canonical passes to an **earlier run of the same step** before any other pool member is considered — not "the next-freshest pool member" as the spec says (L147-149).
| failure scenario: `rename-and-orient` run 1 (bad reference) → run 2 (also wrong) → curator runs `grit untrack -s rename_and_orient` expecting the `pretext_to_asm` output to take over → canonical becomes **run 1's equally-wrong renamed FASTA**, and the curator must untrack twice with no indication that a second untrack is needed (the printed "canonical is now: <run 1 timestamp>" hint is the only clue).
| effort: S | blast radius: file
| debt quadrant: deliberate-prudent (per-run granularity is defensible) with a stale spec
| open-source impact: none

**DOM-11** | severity: minor | confidence: confirmed
| `grit/core/cleanup.py:67-73` (`_latest_run_dir`) + `:86-110`
| claim: `cleanup`'s keep-set is `tracker.latest_run_dir(step)`, which excludes untracked runs — so the **newest** run dir is deleted while an older tracked one is kept, destroying exactly the run the curator asked grit not to track and making `retrack` unrecoverable.
| failure scenario: curator runs `grit pretext-to-asm` (run 1), then `grit pretext-to-asm --untracked` (run 2, an experiment worth keeping on disk), then `grit cleanup --yes` → run 2's directory is `rmtree`d → `grit retrack -s pretext_to_asm` reports success but its recorded output paths no longer exist, so the resolvers silently fall back to run 1.
| effort: S | blast radius: module
| debt quadrant: inadvertent-prudent
| open-source impact: none

**DOM-12** | severity: minor | confidence: confirmed
| `grit/core/status.py:248-252` (`_canonical_mark`'s run-dir branch)
| claim: The unrecorded-file credit matches on `Path(path).parent == run_dir`, which misses any step whose outputs live in a *subdirectory* of the run dir — so the spec's "the two tables can't disagree" (L188-191) fails precisely for `blast_contaminants`.
| failure scenario: `blast-contaminants` succeeds but records no outputs (its `outputs or None` path) → canonical fa is re-globbed to `{run_dir}/hap1/tolX.hap1.1.decontaminated.fa` → the "Canonical files" table shows that file, while the step-history row for that run shows a **blank** `Canonical` cell (its parent is `run_dir/hap1`, not `run_dir`) → the curator reads the history table as "the decontaminated FASTA is not canonical" and re-runs or untracks the wrong step.
| effort: S | blast radius: file
| debt quadrant: inadvertent-prudent
| open-source impact: none

**DOM-13** | severity: minor | confidence: confirmed
| `grit/core/status.py:161-167` (`_canonical_haps`) and `:227-274` (`_canonical_mark`)
| claim: The display layer re-implements two pieces of domain logic — the single-hap test (inline `ctx.hap1_prefix in ("primary","paternal")` instead of `is_single_hap(ctx)`) and run-dir attribution of canonical files (a partial copy of `_step_output`'s re-glob rule) — so it can drift from the resolvers it is meant to report on. `_canonical_mark`'s run-dir branch is a genuine fix for a real display inconsistency, but it fixes it *in the display*, and it is already wrong for nested outputs (DOM-12).
| failure scenario: `is_single_hap` is extended (e.g. a new single-hap YAML key) → `finalize-qc` and the six gated steps process one haplotype while `grit status` resolves and displays canonical files for two, so the curator sees a `hap2` canonical FASTA (resolved via DOM-06's fallback) for a ticket that has no hap2.
| effort: S | blast radius: module
| debt quadrant: deliberate-reckless (a display-layer patch chosen over reconciling the resolvers; contrary to this project's stated "keep the display layer thin" preference)
| open-source impact: none

**DOM-14** | severity: minor | confidence: confirmed
| `grit/utils/helpers.py:459-466` and `:594-601`
| claim: Both `rename_and_orient` **and** `rename_and_orient_hap2` sit in the pool for *every* haplotype; cross-hap contamination is prevented only by the two steps' output *keys* happening to differ (`hap1_fa` vs `hap2_fa`), not by any hap check in the pool construction.
| failure scenario: a future normalisation of `_OUTPUT_SPECS_HAP2`'s keys to plain `fa`/`chr_list` (or a `pretext_to_asm_recurate`-style `f"{hap_prefix}_fa"` scheme) makes `_step_output("rename_and_orient_hap2", ["hap1_fa"], "hap1")` match → **hap2's renamed FASTA becomes hap1's canonical FASTA** and `finalize-qc` ships hap2's assembly as hap1's. Latent today, not currently triggerable.
| effort: S | blast radius: file
| debt quadrant: inadvertent-prudent
| open-source impact: none

**DOM-16** | severity: minor | confidence: plausible
| `grit/utils/helpers.py:415` (`p.stat().st_mtime`) + `grit/core/status.py:189-195`
| claim: `_latest_tracked_output` stats candidate paths unguarded, and `_resolve_canonical_files` catches only `FileNotFoundError` — so a stale NFS handle (`OSError`/ESTALE, not a subclass of `FileNotFoundError`) crashes the resolver.
| failure scenario: `grit cleanup` in one shell deletes a run dir while `grit status` in another has already passed the `exists()` check → `stat()` raises `OSError: [Errno 116] Stale file handle` → `grit status -t RC-x` exits with a traceback instead of a table, and the same exception propagates out of `find_canonical_fa` inside `hic-remapping`/`finalize-qc` rather than being handled as "not found".
| effort: S | blast radius: file
| debt quadrant: inadvertent-prudent
| open-source impact: none
