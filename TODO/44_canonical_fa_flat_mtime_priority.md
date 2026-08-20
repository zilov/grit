# TODO 44: flatten canonical FASTA resolution into one mtime pool

## Problem

`find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs`
(`grit/utils/helpers.py`) resolve "the current canonical output" per
haplotype through a **tiered** model: `pretext_to_asm_recurate[_hap2]` is an
unconditional top tier (exists-check only, no mtime comparison — see
`find_canonical_fa` lines 407-410) that always wins once it exists; below
that, `rename_and_orient[_hap2]`/`blast_contaminants` are compared by mtime
against `microchromosome_combine`/`pretext_to_asm` via two separate
`_latest_tracked_output` calls (lines 412-420).

This has a real usability gap: because recurate's top tier is unconditional
rather than mtime-compared, there is no way for a curator to legitimately
run `blast-contaminants` or `rename-and-orient` again *after* a recurate
round (e.g. to fix contamination or orientation found while reviewing the
recurated assembly) without first running `grit untrack --step
pretext_to_asm_recurate[_hap2]` to blow away the recurate record. There's no
"chain forward from recurate" path — recuration is architecturally a dead
end for the pipeline's later refinement steps.

It also turns out `blast_contaminants` and `rename_and_orient` don't
actually participate in unified canonical resolution as *inputs* today —
confirmed by reading both files:

- `blast_contaminants.py::_blast_contaminants_for_hap` calls
  `find_curated_fa(ctx, hap_prefix)` unconditionally (line 97) — always the
  raw `pretext_to_asm` output, never `microchromosome_combine`'s output, a
  prior recurate's output, or anything else that might currently be
  canonical.
- `rename_and_orient.py::_submit_rename_and_orient_for_hap` hand-rolls its
  own two-step lookup (lines 71-77): `blast_contaminants` tracker output if
  present, else `find_curated_fa`. Also misses `microchromosome_combine` and
  recurate output entirely.

So even in the currently-documented in-order workflow
(`recuration-canonical-priority.md` steps 4-6), running
`microchromosome-combine` and then `blast-contaminants` silently feeds
`blast-contaminants` the *wrong* input (raw `pretext_to_asm` output, not the
birds-specific combined FASTA) — a pre-existing correctness bug this plan
also fixes as a side effect of unifying input resolution onto
`find_canonical_fa`.

## Design

### 1. Flatten `find_canonical_fa`/`_chr_list`/`_haplotigs` into one mtime pool

Replace the "unconditional top tier + two-tier mtime comparison" shape with
a single `_latest_tracked_output` call over one ordered pool (order only
matters as an mtime tie-break, per its existing contract):

- **`find_canonical_fa`** pool: `["pretext_to_asm", "microchromosome_combine",
  "blast_contaminants", "rename_and_orient", "rename_and_orient_hap2",
  "pretext_to_asm_recurate", "pretext_to_asm_recurate_hap2"]`. Delete the
  unconditional recurate exists-check block (lines 407-410) and the two
  separate `baseline`/`result` calls (lines 412-420); replace with one
  `_latest_tracked_output(ctx, pool, keys)` call, freshest tracked
  non-untracked output wins outright.
- **`find_canonical_chr_list`** pool: same list minus `blast_contaminants`
  (contamination filtering doesn't touch the chromosome list — same
  exclusion as today).
- **`find_canonical_haplotigs`** pool: `["pretext_to_asm",
  "pretext_to_asm_recurate"]` (hap2 variant folded in via the existing
  `_recurate_step_name(ctx, hap_prefix)` helper, as today) —
  contamination/rename never touch haplotigs, so this pool stays small; no
  behavior change from today's actual resolution, just expressed as one
  pool instead of a hardcoded single-step check plus a separate recurate
  exists-check.

`_latest_tracked_output` itself (lines 354-378) needs no changes — it
already accepts an arbitrary step list; it's the two-call/tiered *callers*
that collapse to one call each.

Before/after for `find_canonical_fa`, concretely: today, once
`pretext_to_asm_recurate` exists at all, it wins forever regardless of
mtime — a `blast-contaminants` run afterwards has zero effect on canonical
resolution even though it produced a newer file. After this change, `blast-
contaminants` run after `pretext_to_asm_recurate` produces a file with a
newer mtime and correctly becomes canonical; running `pretext_to_asm`
again later (fresher mtime) correctly wins back over a stale
`rename_and_orient`/recurate output, matching the recency-wins model TODO 40
already established for the lower tiers — this task just removes the one
remaining exception to it.

### 2. Fix `blast_contaminants` and `rename_and_orient` to read input via `find_canonical_fa`

- `blast_contaminants.py::_blast_contaminants_for_hap`: replace `find_curated_fa(ctx, hap_prefix)`
  (line 97) with `find_canonical_fa(ctx, hap_prefix)`. Update the docstring/comment
  at lines 39-42 and 95-96 claiming it "always reads the raw `pretext_to_asm`
  output" / "never a previous blast_contaminants run's own output" — both
  become false; the new behavior is "reads whatever is currently canonical
  for this haplotype."
- `rename_and_orient.py::_submit_rename_and_orient_for_hap`: replace the
  hand-rolled `blast_contaminants`-or-`find_curated_fa` lookup (lines 71-77)
  with a single `find_canonical_fa(ctx, hap_prefix)` call. Update the
  comment at lines 69-70 similarly.

This is what actually enables the motivating workflow: post-curation →
recurate → finalize-qc → curator finds a problem → blast-contaminants on
the recurate FASTA → rename-and-orient on that decontaminated output — each
step now picks up whatever is freshest instead of a hardcoded single
predecessor.

**Design decision — SCAFFOLD-header risk on the "blast after rename" order:**
`blast_contaminants`'s scaffold-ID extraction regex (`perl -nE 'say
"true,$1" if /([HAP_\d]*SCAFFOLD_\d+)/i'`, `blast_contaminants.py` line 109)
only recognizes `pretext_to_asm`'s `SCAFFOLD_N`/`HAP_SCAFFOLD_N` header
convention. If a curator chains `blast-contaminants` onto a
`rename_and_orient` output (headers renamed to `chr1`, `chr2`, ...
via `find_canonical_fa` now correctly picking that file up), the regex
matches nothing, `blast.me` ends up with only its header line, and
`decon_blastBTK`/`remove_contamination_bed` silently produce a no-op
"decontaminated" FASTA that is byte-identical (or near enough) to the
input — the step reports success but removes nothing.

Chosen mitigation: **warn and continue**, not refuse. After the extract_cmd
runs (line 111), check `blast_me` for at least one non-header line (skip
the check under `ctx.print_only`, matching how every other step here treats
`--print-only` as no-filesystem-access mode); if empty, log a `log.warning`
that the input FASTA's headers don't look like `pretext_to_asm` scaffold
names (so no contaminant scaffolds could be identified) and that the step
will produce a copy of the input with no scaffolds removed, then let it run
to completion rather than raising. Rationale: refusing outright would block
a curator who *knows* contamination was already handled pre-rename and is
just re-running the step for pipeline-order reasons; a clear warning in the
log plus an honest (no-op) result is safer than a silent no-op with no
signal at all, and keeps `blast_contaminants` from needing new required
flags or an `--allow-renamed` escape hatch. Document this explicitly in the
rewritten `recuration-canonical-priority.md` (see point 5 below) as an
accepted limitation of running blast-contaminants after rename-and-orient,
not a bug to file later.

### 3. Drop `rename_and_orient`'s pre-tracker idempotency guard

`rename_and_orient.py::_submit_rename_and_orient_for_hap` lines 61-67
return early (print "Already done", no tracker interaction at all — before
`ctx.tracker.start` is ever called) if `{outdir}/{prefix}.fa` already
exists. Under the flat mtime-pool model this is actively harmful: a
deliberate rerun on fresher canonical input (say, after a recurate round)
produces *no new tracked output* and *no new file*, since the fixed
output prefix (`{tol_id}.{hap_prefix}.primary.renamed`) never changes
between runs — the step just no-ops forever after the first run, even
though the whole point of the flat pool is that a rerun should be able to
win on mtime.

Fix: delete the guard block (lines 61-67) entirely. This matches
`blast_contaminants`'s existing behavior, which has no such guard and
always executes. Confirmed compatible with existing tests — none of
`tests/test_rename_and_orient.py`'s current cases test this guard path (see
test-update list below for the new test that exercises the intended rerun
behavior instead). No output-path change needed: `bash`/`rename-and-orient`
overwriting `{prefix}.fa` in place is fine because `ctx.tracker.start()`
creates a fresh, distinctly-named run_dir per invocation (same pattern
every other tracked step already relies on for the "which run's output is
this" question) — the *tracker* record is what changes per run, not the
`rename_and_orient/` directory's fixed-prefix filename.

### 4. Add a "current canonical" marker to `grit status -t`

`grit/core/status.py::_print_canonical_files` (lines 142-183) already
computes `find_canonical_fa`/`find_canonical_chr_list`/
`find_canonical_haplotigs` per haplotype for its own summary table. Factor
that resolution out into a small helper (e.g. `_resolve_canonical_files(ctx,
haps) -> dict[str, dict[str, Path]]`, keyed by hap then by
`"fa"`/`"haplotigs"`/`"chr_list"`) so it's computed once per
`show_ticket_history` call and reused by both the existing canonical-files
table and the new marker.

In `show_ticket_history`'s step-history table (iterating `step_latest.items()`,
lines 337-401): for each row, check whether that entry's recorded
`outputs` dict contains a path matching any of the resolved canonical paths
for this ticket (plain string/Path equality against the values from the new
helper — a pure snapshot comparison against currently-tracked runs, no
historical reconstruction, no new tracker state). Add a "Canonical" column
(or append a marker like `★` to the existing "Status" cell — pick whichever
reads better once implemented; a separate column keeps "Status" clean) that
shows a checkmark/star when the match is found. Steps with no `outputs`
recorded (e.g. `agp_copied`'s synthetic row at line 408, or steps whose
epilogue/bjobs-poll never populated `outputs`) simply show no marker — no
error, no special-casing needed beyond a plain "does outputs contain this
path" check.

### 5. Rely on `grit untrack --step <step>` as the uniform undo — verify, don't build

`grit untrack` is already step-name-agnostic and already excludes untracked
runs from `RunTracker.get_output`/`latest_run_dir`, which `_latest_tracked_output`
depends on. Once the unconditional recurate tier is gone, untracking any of
the five pool steps for a haplotype should naturally fall through to the
next-freshest still-tracked output in the flat pool — no new production
code, just tests confirming the flattened pool falls through correctly for
steps that previously had no test coverage here (see test list below).

### File-level scope

| File | Change |
|---|---|
| `grit/utils/helpers.py` | Flatten `find_canonical_fa` (delete unconditional recurate block + two-call tier comparison, one `_latest_tracked_output` call over the full pool), `find_canonical_chr_list`, `find_canonical_haplotigs` similarly. Update each function's docstring to describe the flat pool instead of tiers. |
| `grit/steps/optional/blast_contaminants.py` | `find_curated_fa` → `find_canonical_fa` in `_blast_contaminants_for_hap`; update docstring/comments; add the empty-`blast_me` warn-and-continue check after the extract step. |
| `grit/steps/optional/rename_and_orient.py` | Hand-rolled lookup → single `find_canonical_fa` call; delete the pre-tracker idempotency guard (lines 61-67); update the "Prefer blast_contaminants'..." comment. |
| `grit/steps/post_curation/pretext_to_asm_recurate.py` | Reword `_RECURATE_TIP` (lines 18-24) — drop "recuration output always takes canonical priority... once it exists"; describe it as one more entry in the mtime pool, freshest wins. |
| `grit/core/status.py` | Factor `_print_canonical_files`'s resolution into a reusable helper; add the canonical marker to the step-history table in `show_ticket_history`. |
| `recuration-canonical-priority.md` | Full rewrite from tiered model to flat mtime-pool model, including the new SCAFFOLD-header limitation note and the "chain forward from recurate" workflow this unblocks. Executed as part of implementation, not part of this planning doc. |

### Test updates

- `tests/test_helpers_canonical.py` — remove/rewrite the
  unconditional-recurate-wins test and the mtime-tie-break-between-tiers
  test (both assume the old two-tier shape); add:
  - pool tie-break coverage for the flattened list (equal mtimes resolve to
    first-listed step in the new single pool order);
  - a test that `blast_contaminants`/`rename_and_orient` run *after*
    `pretext_to_asm_recurate` with a newer mtime correctly becomes
    canonical (the core regression test for this task);
  - `grit untrack --step microchromosome_combine` and `--step
    rename_and_orient` falls back to the next-freshest tracked output in
    the flat pool (generalizing the existing recurate/blast_contaminants
    untrack-fallback tests already in this file).
- `tests/test_blast_contaminants.py` — repoint the 4 existing
  `find_curated_fa` mocks to `find_canonical_fa`; add a case verifying the
  warn-and-continue path when the input FASTA's headers don't match the
  SCAFFOLD pattern (empty `blast_me` after extraction → warning logged, no
  exception raised).
- `tests/test_rename_and_orient.py` — repoint mocks from `find_curated_fa`/
  the hand-rolled blast_contaminants lookup to `find_canonical_fa`; add a
  rerun-produces-new-tracked-output test (submits twice with different
  canonical inputs, asserts the guard no longer short-circuits the second
  call before `ctx.tracker.start`).
- `tests/test_pretext_to_asm_recurate.py` — update
  `test_prints_ordering_tip`'s string assertion to match the reworded
  `_RECURATE_TIP`.

## Implementation order

1. Flatten `helpers.py` (`find_canonical_fa`/`_chr_list`/`_haplotigs`) and
   update/add its unit tests first — everything else in this plan depends
   on the flat pool existing and being correct before other steps are
   pointed at it.
2. Fix `blast_contaminants`'s and `rename_and_orient`'s input resolution
   (`find_canonical_fa`) and drop `rename_and_orient`'s idempotency guard,
   including the SCAFFOLD-header warn-and-continue check; update their
   test files.
3. Add the `status.py` canonical marker (factor out `_print_canonical_files`'s
   resolution, wire it into `show_ticket_history`'s step-history table).
4. Reword `pretext_to_asm_recurate.py`'s `_RECURATE_TIP` and update its test.
5. Rewrite `recuration-canonical-priority.md` last, once the actual
   behavior (pool order, warn-and-continue decision, the new status.py
   marker) is final — the doc should describe what was built, not what was
   planned.
