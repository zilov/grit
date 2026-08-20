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

Five changes, in dependency order: flatten the resolution helpers first
(everything else reads through them), then fix the two steps that currently
bypass unified resolution, then add curator-facing visibility
(`status.py` marker), then the small `_RECURATE_TIP` wording fix, then
rewrite the design doc to describe what was actually built.

## Global Constraints

(binding on every task below — from `CLAUDE.md`)

- `log.*` for internal logging, `console.print()` (via `grit/utils/output.py`)
  only for curator-facing structured output (headers/tips/done messages) —
  never bare `print()`.
- Minimal docstrings: one line stating what the function does/returns. No
  historical context about the bug/task that motivated a change — that
  belongs in the commit message.
- No comments explaining *what* code does or referencing this task/ticket;
  only comments justifying a genuinely non-obvious *why*.
- Every step function must keep respecting `ctx.print_only` exactly as it
  does today — do not add new filesystem/subprocess calls that skip the
  `print_only` guard.
- Tests use the `mock_ctx` fixture (`tests/conftest.py`) and fixture YAML
  under `tests/fixtures/`; no real filesystem/Jira access; `subprocess`/`bsub`
  calls are mocked and verified via call inspection.
- After each task: `uv run pytest tests/ -v` (full suite, not just the
  touched file) and `uv run ruff check . && uv run ruff format .` must both
  be clean before committing.
- Do not touch files outside this task's listed scope.

---

## Task 1: Flatten `find_canonical_fa`/`_chr_list`/`_haplotigs` into one mtime pool

**Scope:** `grit/utils/helpers.py` only, plus `tests/test_helpers_canonical.py`.

Replace the "unconditional top tier + two-tier mtime comparison" shape with
a single `_latest_tracked_output` call over one ordered pool (order only
matters as an mtime tie-break, per its existing contract — first-listed step
wins a tie).

- **`find_canonical_fa`** pool: `["pretext_to_asm", "microchromosome_combine",
  "blast_contaminants", "rename_and_orient", "rename_and_orient_hap2",
  "pretext_to_asm_recurate", "pretext_to_asm_recurate_hap2"]` (use
  `_recurate_step_name(ctx, hap_prefix)` for the correct hap1/hap2 recurate
  step name, as today). Delete the unconditional recurate exists-check block
  (lines 407-410) and the two separate `baseline`/`result` calls (lines
  412-420); replace with one `_latest_tracked_output(ctx, pool, keys)` call,
  freshest tracked non-untracked output wins outright, filesystem fallback
  unchanged.
- **`find_canonical_chr_list`** pool: same list minus `blast_contaminants`
  (contamination filtering doesn't touch the chromosome list — same
  exclusion as today).
- **`find_canonical_haplotigs`** pool: `["pretext_to_asm",
  "pretext_to_asm_recurate"]` (hap2 variant folded in via
  `_recurate_step_name`, as today) — contamination/rename never touch
  haplotigs, so this pool stays small; no behavior change from today's
  actual resolution, just expressed as one pool instead of a hardcoded
  single-step check plus a separate recurate exists-check.

`_latest_tracked_output` itself (lines 354-378) needs no changes — it
already accepts an arbitrary step list; it's the two-call/tiered *callers*
that collapse to one call each. Update each of the three functions'
docstrings to describe the flat pool instead of tiers.

**Before/after** for `find_canonical_fa`, concretely: today, once
`pretext_to_asm_recurate` exists at all, it wins forever regardless of
mtime — a `blast-contaminants` run afterwards has zero effect on canonical
resolution even though it produced a newer file. After this change,
`blast-contaminants` run after `pretext_to_asm_recurate` produces a file
with a newer mtime and correctly becomes canonical; running `pretext_to_asm`
again later (fresher mtime) correctly wins back over a stale
`rename_and_orient`/recurate output, matching the recency-wins model already
established for the lower tiers — this task just removes the one remaining
exception to it.

**Test updates** (`tests/test_helpers_canonical.py`):
- Remove/rewrite the unconditional-recurate-wins test and the
  mtime-tie-break-between-tiers test (both assume the old two-tier shape).
- Add pool tie-break coverage for the flattened list (equal mtimes resolve
  to the first-listed step in the new single pool order).
- Add a test that `blast_contaminants`/`rename_and_orient` run *after*
  `pretext_to_asm_recurate` with a newer mtime correctly becomes canonical —
  this is the core regression test for this task.
- Add `grit untrack --step microchromosome_combine` and `--step
  rename_and_orient` falling back to the next-freshest tracked output in the
  flat pool (generalizing the existing recurate/blast_contaminants
  untrack-fallback tests already in this file — untrack itself needs no code
  change, `RunTracker` is already step-name-agnostic; this is pool-flattening
  regression coverage only).

**Report file:** `.superpowers/sdd/44_canonical_fa_flat_mtime_priority/task-1-report.md`

---

## Task 2: Fix `blast_contaminants` and `rename_and_orient` input resolution

**Scope:** `grit/steps/optional/blast_contaminants.py`,
`grit/steps/optional/rename_and_orient.py`, plus
`tests/test_blast_contaminants.py` and `tests/test_rename_and_orient.py`.
Depends on Task 1 (`find_canonical_fa` must already be flattened).

**2a. Read input via `find_canonical_fa`:**
- `blast_contaminants.py::_blast_contaminants_for_hap`: replace
  `find_curated_fa(ctx, hap_prefix)` (line 97) with
  `find_canonical_fa(ctx, hap_prefix)`. Update the docstring/comment at
  lines 39-42 and 95-96 claiming it "always reads the raw `pretext_to_asm`
  output" / "never a previous blast_contaminants run's own output" — both
  become false; the new behavior is "reads whatever is currently canonical
  for this haplotype."
- `rename_and_orient.py::_submit_rename_and_orient_for_hap`: replace the
  hand-rolled `blast_contaminants`-or-`find_curated_fa` lookup (lines 71-77)
  with a single `find_canonical_fa(ctx, hap_prefix)` call. Update the
  comment at lines 69-70 similarly.

This is what actually enables the motivating workflow: post-curation →
recurate → finalize-qc → curator finds a problem → blast-contaminants on the
recurate FASTA → rename-and-orient on that decontaminated output — each step
now picks up whatever is freshest instead of a hardcoded single predecessor.

**2b. Design decision — SCAFFOLD-header risk on the "blast after rename"
order:** `blast_contaminants`'s scaffold-ID extraction regex (`perl -nE 'say
"true,$1" if /([HAP_\d]*SCAFFOLD_\d+)/i'`, `blast_contaminants.py` line 109)
only recognizes `pretext_to_asm`'s `SCAFFOLD_N`/`HAP_SCAFFOLD_N` header
convention. If a curator chains `blast-contaminants` onto a
`rename_and_orient` output (headers renamed to `chr1`, `chr2`, ... —
`find_canonical_fa` now correctly picks that file up per 2a), the regex
matches nothing, `blast.me` ends up with only its header line, and
`decon_blastBTK`/`remove_contamination_bed` silently produce a no-op
"decontaminated" FASTA byte-identical (or near enough) to the input — the
step reports success but removes nothing.

Chosen mitigation: **warn and continue**, not refuse. After the extract_cmd
runs (line 111), check `blast_me` for at least one non-header line (skip the
check under `ctx.print_only`, matching how every other step here treats
`--print-only` as no-filesystem-access mode); if empty, `log.warning` that
the input FASTA's headers don't look like `pretext_to_asm` scaffold names
(so no contaminant scaffolds could be identified) and that the step will
produce a copy of the input with no scaffolds removed, then let it run to
completion rather than raising. Do not add a new CLI flag or
`--allow-renamed` escape hatch for this.

**Test updates:**
- `tests/test_blast_contaminants.py` — repoint the 4 existing
  `find_curated_fa` mocks to `find_canonical_fa`; add a case verifying the
  warn-and-continue path when the input FASTA's headers don't match the
  SCAFFOLD pattern (empty `blast_me` after extraction → warning logged, no
  exception raised).
- `tests/test_rename_and_orient.py` — repoint mocks from `find_curated_fa`/
  the hand-rolled blast_contaminants lookup to `find_canonical_fa`.

**Report file:** `.superpowers/sdd/44_canonical_fa_flat_mtime_priority/task-2-report.md`

---

## Task 3: Drop `rename_and_orient`'s pre-tracker idempotency guard

**Scope:** `grit/steps/optional/rename_and_orient.py` and
`tests/test_rename_and_orient.py`. Depends on Task 2 landing in the same
file (do this task second within `rename_and_orient.py`, after 2a/2b, so
there's one coherent diff to that function — implementer may combine into
the same commit as Task 2 if working the same file, but this is tracked as
its own review unit).

`rename_and_orient.py::_submit_rename_and_orient_for_hap` lines 61-67 return
early (print "Already done", no tracker interaction at all — before
`ctx.tracker.start` is ever called) if `{outdir}/{prefix}.fa` already
exists. Under the flat mtime-pool model this is actively harmful: a
deliberate rerun on fresher canonical input (say, after a recurate round)
produces *no new tracked output* and *no new file*, since the fixed output
prefix (`{tol_id}.{hap_prefix}.primary.renamed`) never changes between runs
— the step just no-ops forever after the first run, even though the whole
point of the flat pool is that a rerun should be able to win on mtime.

Fix: delete the guard block (lines 61-67) entirely. This matches
`blast_contaminants`'s existing behavior, which has no such guard and always
executes. No output-path change needed: the tool overwriting `{prefix}.fa`
in place is fine because `ctx.tracker.start()` creates a fresh,
distinctly-named run_dir per invocation (same pattern every other tracked
step already relies on for "which run's output is this") — the *tracker*
record is what changes per run, not the `rename_and_orient/` directory's
fixed-prefix filename.

**Test updates:**
- `tests/test_rename_and_orient.py` — confirmed none of the current test
  cases exercise this guard path, so removing it should not break existing
  tests. Add a rerun-produces-new-tracked-output test: submit twice with
  different canonical inputs (mock `find_canonical_fa` to return two
  different paths across the two calls), assert `ctx.tracker.start` is
  called both times and the guard no longer short-circuits the second call.

**Report file:** `.superpowers/sdd/44_canonical_fa_flat_mtime_priority/task-3-report.md`

---

## Task 4: Add a "current canonical" marker to `grit status -t`

**Scope:** `grit/core/status.py` only. No dedicated test file exists for
this module today — check for one before assuming there isn't (`tests/` may
have `test_status.py`); if none exists, manual verification via
`--print-only`/fixture run is acceptable, but add one if a suitable test
fixture pattern already exists for this file.

`grit/core/status.py::_print_canonical_files` (lines 142-183) already
computes `find_canonical_fa`/`find_canonical_chr_list`/
`find_canonical_haplotigs` per haplotype for its own summary table. Factor
that resolution out into a small helper (e.g. `_resolve_canonical_files(ctx,
haps) -> dict[str, dict[str, Path]]`, keyed by hap then by
`"fa"`/`"haplotigs"`/`"chr_list"`) so it's computed once per
`show_ticket_history` call and reused by both the existing canonical-files
table and the new marker.

In `show_ticket_history`'s step-history table (iterating
`step_latest.items()`, lines 337-401): for each row, check whether that
entry's recorded `outputs` dict contains a path matching any of the resolved
canonical paths for this ticket (plain string/Path equality against the
values from the new helper — a pure snapshot comparison against
currently-tracked runs, no historical reconstruction, no new tracker state).
Add a "Canonical" column (or append a marker like `★` to the existing
"Status" cell — pick whichever reads better once implemented; a separate
column keeps "Status" clean) that shows a checkmark/star when the match is
found. Steps with no `outputs` recorded (e.g. `agp_copied`'s synthetic row
at line 408, or steps whose epilogue/bjobs-poll never populated `outputs`)
simply show no marker — no error, no special-casing needed beyond a plain
"does outputs contain this path" check.

**Report file:** `.superpowers/sdd/44_canonical_fa_flat_mtime_priority/task-4-report.md`

---

## Task 5: Reword `pretext_to_asm_recurate`'s `_RECURATE_TIP`

**Scope:** `grit/steps/post_curation/pretext_to_asm_recurate.py` and
`tests/test_pretext_to_asm_recurate.py` only.

Reword `_RECURATE_TIP` (lines 18-24) — drop the claim that recuration output
"always takes canonical priority... once it exists" (no longer true after
Task 1). Describe it instead as one more entry in the flat mtime pool:
freshest tracked output wins, so if the curator wants the recurate output to
remain canonical they should not rerun `blast-contaminants`/
`rename-and-orient` afterwards on unrelated stale input — and if they need
to, that's now a normal, supported forward-chain (see Task 2), not something
requiring `grit untrack` first.

**Test updates:** update `test_prints_ordering_tip`'s string assertion to
match the reworded `_RECURATE_TIP`.

**Report file:** `.superpowers/sdd/44_canonical_fa_flat_mtime_priority/task-5-report.md`

---

## Task 6: Rewrite `recuration-canonical-priority.md` and the `CLAUDE.md` pointer

**Scope:** `recuration-canonical-priority.md` and the "Canonical FASTA
priority" bullet in `CLAUDE.md`'s "Key conventions" section only. Depends on
Tasks 1-5 all being complete — this doc should describe what was actually
built, not what was planned, so do it last.

Rewrite `recuration-canonical-priority.md` (currently describes the tiered
model end-to-end, including a mermaid flowchart) to describe the flat
mtime-pool model instead:

- The per-haplotype pool for `find_canonical_fa` is one ordered list (see
  Task 1) — freshest tracked, non-untracked output wins, no tiers. Same for
  `find_canonical_chr_list`/`find_canonical_haplotigs`'s smaller pools.
- The "chain forward from recurate" workflow this unblocks: curator can run
  `blast-contaminants`/`rename-and-orient` again after a recurate round
  without `grit untrack` first, and the freshest output becomes canonical.
- The SCAFFOLD-header warn-and-continue limitation from Task 2b — document
  this explicitly as an accepted limitation of running `blast-contaminants`
  after `rename-and-orient` (headers no longer match `SCAFFOLD_N`), not a
  bug to file later.
- The new `grit status -t` canonical marker from Task 4 as the curator-facing
  way to see which step currently owns canonical_fa, and `grit untrack
  --step <step>` (already uniform, any of the pool's step names) as the
  uniform way to undo an unwanted canonical change — mention this replaces
  the old recurate-only escape hatch.
- Update or remove the mermaid flowchart to match the flat-pool model (a
  simpler diagram: one box per pool step feeding into "freshest wins", plus
  the user-facing step-by-step path from the current doc revision, updated
  only where tiering language ("unconditional top", "priority order") no
  longer applies).

Update `CLAUDE.md`'s "Canonical FASTA priority" bullet to describe the flat
pool in one or two sentences instead of the tiered chain, keeping the
pointer to `recuration-canonical-priority.md`.

**Report file:** `.superpowers/sdd/44_canonical_fa_flat_mtime_priority/task-6-report.md`
