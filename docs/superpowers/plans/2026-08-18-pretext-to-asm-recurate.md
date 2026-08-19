# pretext-to-asm-recurate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a curator re-curate an already-remapped Hi-C map ("curation of curated map") and re-run pretext-to-asm/hic-remapping on top of it, per haplotype, without breaking canonical-file resolution for the other haplotype or downstream steps.

**Architecture:** A new step file (`pretext_to_asm_recurate.py`) reuses the existing `_run_pretext_to_asm_core` helper (shared today by `pretext_to_asm.py` and `microchromosome_combine.py`) under two new, independent, per-hap tracker step names. It resolves its input via the existing `find_canonical_fa`, merges haplotigs via a new `output_transform` hook added to the shared core, and is layered into `find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs` as an unconditional top priority tier. A composite `post-curation-recurate` command chains it with `hic-remapping`. This depends on a prerequisite fix (already designed in `TODO/40_canonical_file_selection_by_mtime.md`) that makes the *existing* canonical-fa/chr-list chain resolve by file recency instead of fixed step order — implemented here as Task 1.

**Tech Stack:** Python 3, Click (`rich_click`), pytest, existing `RunTracker`/`RegistryManager` (JSON-backed, `~/.grit/grit_registry.json`).

**Spec:** `TODO/44_pretext_to_asm_recurate.md` (this plan implements it); `TODO/40_canonical_file_selection_by_mtime.md` (implemented here as Task 1, a hard prerequisite for Task 4's correctness).

## Global Constraints

- Exactly one recuration round is supported per haplotype — no numbered/unbounded step-name scheme (confirmed with curators: ~5-10% of cases need more and are explicitly out of scope).
- No hard validation/blocking of step order before recuration — only an informational tip via `print_tip`.
- Haplotig merging is plain FASTA-record concatenation — no dedup by name/sequence.
- `pretext-to-asm-recurate` and `post-curation-recurate` both use an *exclusive* `--hap2` flag (hap1 runs unless `--hap2` is passed, never both) — unlike `post-curation`'s existing *additive* `--hap2`.
- Recuration AGP files live in `{workdir}/recurate/`, one directory shared by both haps, filenames must contain the hap prefix (e.g. `{tol_id}.hap1.recurate.agp`) so the glob can disambiguate.
- Recuration's canonical-priority tier is fixed/unconditional (not mtime-compared against `rename_and_orient`/`blast_contaminants`) — it always wins once it exists for that hap; the escape hatch is `grit untrack --step pretext_to_asm_recurate` (already works, no code change needed — verify in Task 4).

---

## File Structure

- **Modify** `grit/utils/helpers.py`: add `_latest_tracked_output()` helper (Task 1); add unconditional top-tier lookups to `find_canonical_fa`, `find_canonical_chr_list`, `find_canonical_haplotigs` (Task 4).
- **Modify** `grit/steps/post_curation/pretext_to_asm.py`: add `agp_glob` and `output_transform` parameters to `_run_pretext_to_asm_core` (Task 2).
- **Create** `grit/steps/post_curation/pretext_to_asm_recurate.py`: new step + Click command (Task 3).
- **Create** `grit/steps/post_curation/post_curation_recurate.py`: composite step + Click command (Task 5).
- **Modify** `grit/core/click_cli.py`: register the two new commands (Tasks 3, 5).
- **Modify** `grit/core/manifests.py`: add manifest/status entries for the two new step names, for `grit status` display parity with every other tracked step (Task 6).
- **Modify** `tests/test_helpers_canonical.py`: TODO-40 recency tests (Task 1) + recurate-tier tests (Task 4).
- **Modify** `tests/test_post_curation.py`: new tests for `_run_pretext_to_asm_core`'s new params (Task 2).
- **Create** `tests/test_pretext_to_asm_recurate.py` (Task 3).
- **Create** `tests/test_post_curation_recurate.py` (Task 5).

---

### Task 1: Fix canonical-fa/chr-list resolution to use file mtime, not fixed step order

**Files:**
- Modify: `grit/utils/helpers.py:331-380` (`find_canonical_fa`), `grit/utils/helpers.py:464-532` (`find_canonical_chr_list`)
- Test: `tests/test_helpers_canonical.py`

**Interfaces:**
- Produces: `_latest_tracked_output(ctx, steps: list[str], key_variants: list[str]) -> Path | None` — a new module-level helper in `grit/utils/helpers.py`, used internally by `find_canonical_fa`/`find_canonical_chr_list`. Not used outside this file.

This is the prerequisite from `TODO/40_canonical_file_selection_by_mtime.md`. Today, `find_canonical_fa`'s tracker loop walks a fixed step-name list and returns the **first** step whose tracked output still exists on disk — it never compares *when* each step actually ran, so re-running an earlier-in-the-list step (e.g. `pretext_to_asm`) after a later one (e.g. `rename_and_orient`) is silently ignored. Task 4's recuration tier needs this fixed correctly first, since recuration's own input resolution (`find_canonical_fa`) must reflect the true latest state.

- [ ] **Step 1: Write the failing tests for the recency bug**

Add to `tests/test_helpers_canonical.py` (after the existing `test_blast_contaminants_beats_microchromosome_combine` test):

```python
def test_pretext_to_asm_rerun_after_rename_and_orient_wins(mock_ctx, tmp_path):
    """A fresh pretext_to_asm re-run must beat a now-stale rename_and_orient output."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    rao_dir = tmp_path / "rename_and_orient" / "2026-01-03T00_00_00"
    rao_fa = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    # curator fixes the AGP and re-runs pretext_to_asm — its new output is
    # chronologically the newest file, even though it's earlier in the fixed list
    pta_dir2 = tmp_path / "pretext_to_asm" / "2026-01-04T00_00_00"
    pta_fa2 = _write(pta_dir2 / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir2, "success", outputs={"hap1_fa": str(pta_fa2)})

    import os

    os.utime(pta_fa, (1000, 1000))
    os.utime(bc_fa, (2000, 2000))
    os.utime(rao_fa, (3000, 3000))
    os.utime(pta_fa2, (4000, 4000))

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa2


def test_blast_contaminants_rerun_after_rename_and_orient_wins(mock_ctx, tmp_path):
    """A fresh blast_contaminants re-run must beat a now-stale rename_and_orient output."""
    import os

    tracker = _make_tracker(tmp_path, mock_ctx)
    rao_dir = tmp_path / "rename_and_orient" / "2026-01-01T00_00_00"
    rao_fa = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    bc_dir = tmp_path / "blast_contaminants" / "2026-01-02T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    os.utime(rao_fa, (1000, 1000))
    os.utime(bc_fa, (2000, 2000))

    assert find_canonical_fa(mock_ctx, "hap1") == bc_fa


def test_microchromosome_combine_rerun_after_blast_contaminants_wins(mock_ctx, tmp_path):
    """A fresh microchromosome_combine re-run must beat a now-stale blast_contaminants
    output — recency wins within and across tiers, tier order is only a tie-break."""
    import os

    tracker = _make_tracker(tmp_path, mock_ctx)
    bc_dir = tmp_path / "blast_contaminants" / "2026-01-01T00_00_00"
    bc_fa = _write(bc_dir / f"{mock_ctx.tol_id}.hap1.1.decontaminated.fa")
    tracker.finish("blast_contaminants", bc_dir, "success", outputs={"hap1_fa": str(bc_fa)})

    combine_dir = tmp_path / "microchromosome_combine" / "2026-01-02T00_00_00"
    combine_fa = _write(combine_dir / f"{mock_ctx.tol_id}.hap1.fa")
    tracker.finish(
        "microchromosome_combine", combine_dir, "success", outputs={"hap1_fa": str(combine_fa)}
    )

    os.utime(bc_fa, (1000, 1000))
    os.utime(combine_fa, (2000, 2000))

    assert find_canonical_fa(mock_ctx, "hap1") == combine_fa
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `cd /Users/dz11/github/grit && pytest tests/test_helpers_canonical.py -k "rerun_after or rerun_" -v`
Expected: all three FAIL (current fixed-order logic returns the earlier-in-list step, not the chronologically newest).

- [ ] **Step 3: Add `_latest_tracked_output` and rewire `find_canonical_fa`**

In `grit/utils/helpers.py`, add the helper just above `find_canonical_fa` (around line 330):

```python
def _latest_tracked_output(
    ctx: "CurationContext",
    steps: list[str],
    key_variants: list[str],
) -> Path | None:
    """
    Among *steps* (tracker step names), return the Path with the newest
    mtime whose tracker output for any of *key_variants* still exists on
    disk. Steps with no matching output are skipped. Ties (equal mtime, or
    only one candidate) resolve to the first-listed step in *steps*.
    """
    if not ctx.tracker:
        return None
    best: tuple[float, int, Path] | None = None  # (mtime, -priority_index, path)
    for idx, step in enumerate(steps):
        for k in key_variants:
            val = ctx.tracker.get_output(step, k)
            if val and Path(val).exists():
                p = Path(val)
                mtime = p.stat().st_mtime
                candidate = (mtime, -idx, p)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
                break
    return best[2] if best else None
```

Replace the tracker loop inside `find_canonical_fa` (currently lines 352-363):

```python
    if ctx.tracker:
        keys = [f"{hap_prefix}_fa", f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_fa"]
        baseline = _latest_tracked_output(ctx, ["microchromosome_combine", "pretext_to_asm"], keys)
        result = _latest_tracked_output(
            ctx, ["rename_and_orient", "rename_and_orient_hap2", "blast_contaminants"], keys
        )
        if result and (baseline is None or result.stat().st_mtime > baseline.stat().st_mtime):
            return result
        if baseline:
            return baseline
```

- [ ] **Step 4: Rewire `find_canonical_chr_list` the same way**

Replace the tracker loop inside `find_canonical_chr_list` (currently lines 491-504):

```python
    if ctx.tracker:
        keys = [f"{hap_prefix}_chr_list", f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_chr_list"]
        baseline = _latest_tracked_output(ctx, ["microchromosome_combine", "pretext_to_asm"], keys)
        result = _latest_tracked_output(ctx, ["rename_and_orient", "rename_and_orient_hap2"], keys)
        if result and (baseline is None or result.stat().st_mtime > baseline.stat().st_mtime):
            return result
        if baseline:
            return baseline
```

- [ ] **Step 5: Run the new tests to verify they pass, then run the full existing suite for regressions**

Run: `cd /Users/dz11/github/grit && pytest tests/test_helpers_canonical.py -v`
Expected: all tests PASS, including the pre-existing ones (`test_blast_contaminants_beats_pretext_to_asm`, `test_rename_and_orient_beats_blast_contaminants`, `test_microchromosome_combine_beats_pretext_to_asm`, `test_blast_contaminants_beats_microchromosome_combine`, `test_rename_and_orient_beats_microchromosome_combine`, `test_untracking_blast_contaminants_falls_back_to_pretext_to_asm`) — they all use chronologically-increasing timestamps that match mtime order already, so they must keep passing unchanged.

Run: `cd /Users/dz11/github/grit && pytest tests/ -v`
Expected: full suite PASSES (no regressions elsewhere — `find_canonical_chr_list`/`find_canonical_fa` are called from `hic_remapping.py`, `finalize_qc.py`, `rename_and_orient.py`; their existing tests mock these functions directly or use non-conflicting single-step fixtures, so behavior is unaffected).

- [ ] **Step 6: Commit**

```bash
git add grit/utils/helpers.py tests/test_helpers_canonical.py
git commit -m "fix(helpers): resolve canonical fa/chr-list by mtime, not fixed step order"
```

---

### Task 2: Add `agp_glob` and `output_transform` params to `_run_pretext_to_asm_core`

**Files:**
- Modify: `grit/steps/post_curation/pretext_to_asm.py:39-124`
- Test: `tests/test_post_curation.py`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: `_run_pretext_to_asm_core(ctx, step_name, original_fa, original_fa_missing_msg, agp_search_dir, out_fa_name, output_specs, *, agp_glob: str | None = None, output_transform: Callable[[Path], None] | None = None) -> Path` — Task 3 depends on both new keyword params existing with these exact names and semantics: `agp_glob` overrides the AGP filename glob (relative to `agp_search_dir`), defaulting to today's `f"{ctx.tol_id}*.agp*"` when `None`; `output_transform`, when given, is called with the run_dir immediately after the `pretext-to-asm` binary succeeds and before `collect_outputs()` runs, letting a caller write extra files into run_dir so they're picked up by the same `collect_outputs`/`finish()` call (avoiding a second `tracker.finish()` that would silently overwrite the first call's outputs dict). `output_transform` is only invoked outside print-only mode.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_post_curation.py`, in the `run_pretext_to_asm` section (after `test_run_pretext_to_asm_print_only_skips_checks`):

```python
@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_core_custom_agp_glob(mock_glob, mock_run, mock_ctx, tmp_path):
    """A custom agp_glob overrides the default {tol_id}*.agp* pattern."""
    from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    original_fa = tmp_path / "original.fa"
    original_fa.write_text("")
    agp = str(tmp_path / "sDipInt39.hap1.recurate.agp")
    mock_glob.return_value = [agp]
    mock_run.return_value = ""

    _run_pretext_to_asm_core(
        mock_ctx,
        "pretext_to_asm_recurate",
        original_fa,
        "missing",
        tmp_path,
        "sDipInt39.fa",
        [],
        agp_glob="sDipInt39*hap1*.agp*",
    )

    glob_pattern = mock_glob.call_args[0][0]
    assert glob_pattern == str(tmp_path / "sDipInt39*hap1*.agp*")


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_core_default_agp_glob_unchanged(mock_glob, mock_run, mock_ctx, tmp_path):
    """Omitting agp_glob keeps today's {tol_id}*.agp* pattern (no regression)."""
    from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    original_fa = tmp_path / "original.fa"
    original_fa.write_text("")
    agp = str(tmp_path / "sDipInt39.agp")
    mock_glob.return_value = [agp]
    mock_run.return_value = ""

    _run_pretext_to_asm_core(
        mock_ctx, "pretext_to_asm", original_fa, "missing", tmp_path, "sDipInt39.fa", []
    )

    glob_pattern = mock_glob.call_args[0][0]
    assert glob_pattern == str(tmp_path / "sDipInt39*.agp*")


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
def test_run_pretext_to_asm_core_output_transform_runs_before_collect_outputs(
    mock_glob, mock_run, mock_ctx, tmp_path
):
    """output_transform can write a file that collect_outputs then picks up,
    all within the single finish() call collect_outputs feeds into."""
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker
    from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core

    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, mock_ctx.tol_id, mock_ctx.species, tmp_path)
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    original_fa = tmp_path / "original.fa"
    original_fa.write_text("")
    agp = str(tmp_path / "sDipInt39.agp")
    mock_glob.return_value = [agp]
    mock_run.return_value = ""

    def _write_extra_file(run_dir):
        (run_dir / "hap1.extra_output.fa").write_text(">seq\nACGT\n")

    output_specs = [("hap1_extra", "hap1.extra_output.fa", [])]
    run_dir = _run_pretext_to_asm_core(
        mock_ctx,
        "pretext_to_asm",
        original_fa,
        "missing",
        tmp_path,
        "sDipInt39.fa",
        output_specs,
        output_transform=_write_extra_file,
    )

    assert mock_ctx.tracker.get_output("pretext_to_asm", "hap1_extra") == str(
        run_dir / "hap1.extra_output.fa"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dz11/github/grit && pytest tests/test_post_curation.py -k "core_custom_agp_glob or core_default_agp_glob or core_output_transform" -v`
Expected: FAIL with `TypeError: _run_pretext_to_asm_core() got an unexpected keyword argument 'agp_glob'` (and similarly for `output_transform`).

- [ ] **Step 3: Implement the two new parameters**

In `grit/steps/post_curation/pretext_to_asm.py`, add the import and update the signature and body:

```python
from typing import Callable
```

```python
def _run_pretext_to_asm_core(
    ctx: CurationContext,
    step_name: str,
    original_fa: Path,
    original_fa_missing_msg: str,
    agp_search_dir: Path,
    out_fa_name: str,
    output_specs: list[tuple[str, str, list[str]]],
    *,
    agp_glob: str | None = None,
    output_transform: Callable[[Path], None] | None = None,
) -> Path:
```

Update the docstring's second paragraph to mention the new params:

```python
    """
    Runs pretext-to-asm for one (original_fa, agp) pair under a tracked step.

    Looks for *agp_glob* (default ``{tol_id}*.agp*``) in *agp_search_dir*, runs
    pretext-to-asm, optionally calls *output_transform(run_dir)* to let the
    caller write extra files into run_dir before outputs are collected, and
    records outputs via *output_specs* under *step_name*. Returns the run_dir
    (which may be a prior run's dir if the step was skipped as already done).

    Shared by ``run_pretext_to_asm`` (main assembly), ``run_microchromosome_combine``
    (micro-assembly small chromosomes), and ``run_pretext_to_asm_recurate``
    (re-curation of an already-remapped map).
    """
```

Change the AGP glob line (currently `agp_pattern = str(agp_search_dir / f"{ctx.tol_id}*.agp*")`):

```python
    agp_pattern = str(agp_search_dir / (agp_glob or f"{ctx.tol_id}*.agp*"))
```

Insert the hook call inside the existing `try` block, right after `_run(cmd, ...)` and before the `if ctx.tracker:` block:

```python
    try:
        _run(cmd, ctx.print_only, capture=False)
        if output_transform and not ctx.print_only:
            output_transform(run_dir)
        if ctx.tracker:
            outputs = collect_outputs(
                output_specs, run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
            )
            ctx.tracker.finish(step_name, run_dir, "success", outputs=outputs or None)
    except Exception:
        if ctx.tracker:
            ctx.tracker.finish(step_name, run_dir, "failed")
        raise
```

- [ ] **Step 4: Run tests to verify they pass, then run the full existing suite**

Run: `cd /Users/dz11/github/grit && pytest tests/test_post_curation.py -v`
Expected: all PASS, including the pre-existing `test_run_pretext_to_asm_*` tests (default params unchanged).

Run: `cd /Users/dz11/github/grit && pytest tests/ -v`
Expected: full suite PASSES.

- [ ] **Step 5: Commit**

```bash
git add grit/steps/post_curation/pretext_to_asm.py tests/test_post_curation.py
git commit -m "feat(pretext-to-asm): support custom AGP glob and post-run output hook"
```

---

### Task 3: `pretext-to-asm-recurate` step and CLI command

**Files:**
- Create: `grit/steps/post_curation/pretext_to_asm_recurate.py`
- Modify: `grit/core/click_cli.py` (register the new command)
- Test: `tests/test_pretext_to_asm_recurate.py`

**Interfaces:**
- Consumes: `_run_pretext_to_asm_core(..., agp_glob=..., output_transform=...)` from Task 2; `find_canonical_fa(ctx, hap_prefix)`, `find_canonical_haplotigs(ctx, hap_prefix)` from `grit/utils/helpers.py` (unchanged signatures); `print_step_header`, `print_tip` from `grit/utils/output.py`.
- Produces: `run_pretext_to_asm_recurate(ctx: CurationContext, hap_prefix: str, step_name: str) -> Path` and Click command `pretext_to_asm_recurate_cmd` — both consumed by Task 5's composite command. Tracker step names used: `"pretext_to_asm_recurate"` (hap1) / `"pretext_to_asm_recurate_hap2"` (hap2), with output keys `{hap_prefix}_fa`, `{hap_prefix}_chr_list`, `{hap_prefix}_haplotigs` — these exact key names are what Task 4's canonical-tier lookups query.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pretext_to_asm_recurate.py`:

```python
"""Tests for the pretext-to-asm-recurate step."""

from pathlib import Path
from unittest.mock import patch

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.post_curation.pretext_to_asm_recurate import run_pretext_to_asm_recurate


def _tracker(tmp_path, ctx):
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)
    return ctx.tracker


def _write(path, content=">seq\nACGT\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_agp_glob_picks_hap1_file_and_ignores_hap2(
    mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    """The AGP glob must be hap-qualified so it doesn't pick up the other hap's file."""
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    hap1_agp = str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")
    mock_glob.return_value = [hap1_agp]
    mock_run.return_value = ""

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    glob_pattern = mock_glob.call_args[0][0]
    assert "hap1" in glob_pattern
    assert str(tmp_path / "recurate") in glob_pattern


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_input_fasta_comes_from_find_canonical_fa(mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    canonical_fa = _write(tmp_path / "blast_contaminants" / "hap1.fa")
    mock_find_fa.return_value = canonical_fa
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.return_value = ""

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    mock_find_fa.assert_called_once_with(mock_ctx, "hap1")
    calls = [str(c) for c in mock_run.call_args_list]
    assert any(str(canonical_fa) in c for c in calls)


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_haplotig_merge_both_nonempty_concatenates(mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path):
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    prior_dir = tmp_path / "pretext_to_asm" / "run1"
    prior_haplotigs = _write(prior_dir / "sDipInt39.hap1.1.all_haplotigs.curated.fa", ">old\nAAAA\n")
    tracker.finish(
        "pretext_to_asm", prior_dir, "success", outputs={"hap1_haplotigs": str(prior_haplotigs)}
    )

    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]

    def _fake_run(cmd, print_only, **kwargs):
        # simulate pretext-to-asm writing its own new haplotigs file into run_dir
        out_fa = Path(cmd.split("-o ")[1].split()[0])
        _write(out_fa.parent / "sDipInt39.additional_haplotigs.curated.fa", ">new\nCCCC\n")
        return ""

    mock_run.side_effect = _fake_run

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    merged_path = Path(tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs"))
    content = merged_path.read_text()
    assert ">old" in content
    assert ">new" in content


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_haplotig_merge_prior_only_carries_forward(mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path):
    """Prior haplotigs non-empty, new run produces none — prior must be carried forward."""
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    prior_dir = tmp_path / "pretext_to_asm" / "run1"
    prior_haplotigs = _write(prior_dir / "sDipInt39.hap1.1.all_haplotigs.curated.fa", ">old\nAAAA\n")
    tracker.finish(
        "pretext_to_asm", prior_dir, "success", outputs={"hap1_haplotigs": str(prior_haplotigs)}
    )

    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.return_value = ""  # no new haplotigs file written

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    merged_path = Path(tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs"))
    assert ">old" in merged_path.read_text()


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_haplotigs")
def test_haplotig_merge_new_only_uses_new(
    mock_find_haplotigs, mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    """No prior haplotigs at all, new run produces some — use the new file as-is."""
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_haplotigs.side_effect = FileNotFoundError("none yet")
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]

    def _fake_run(cmd, print_only, **kwargs):
        out_fa = Path(cmd.split("-o ")[1].split()[0])
        _write(out_fa.parent / "sDipInt39.additional_haplotigs.curated.fa", ">new\nCCCC\n")
        return ""

    mock_run.side_effect = _fake_run

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    merged_path = Path(tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs"))
    assert ">new" in merged_path.read_text()


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_haplotigs")
def test_haplotig_merge_neither_tracks_nothing(
    mock_find_haplotigs, mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path
):
    """No prior and no new haplotigs — nothing tracked under the haplotigs key."""
    tracker = _tracker(tmp_path, mock_ctx)
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_haplotigs.side_effect = FileNotFoundError("none")
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.return_value = ""

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    assert tracker.get_output("pretext_to_asm_recurate", "hap1_haplotigs") is None


@patch("grit.steps.post_curation.pretext_to_asm._run")
@patch("grit.steps.post_curation.pretext_to_asm.glob.glob")
@patch("grit.steps.post_curation.pretext_to_asm_recurate.find_canonical_fa")
def test_prints_ordering_tip(mock_find_fa, mock_glob, mock_run, mock_ctx, tmp_path, capsys):
    mock_ctx.workdir = tmp_path
    mock_ctx.tol_id = "sDipInt39"
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"
    mock_find_fa.return_value = _write(tmp_path / "canonical.fa")
    mock_glob.return_value = [str(tmp_path / "recurate" / "sDipInt39.hap1.recurate.agp")]
    mock_run.return_value = ""

    run_pretext_to_asm_recurate(mock_ctx, "hap1", "pretext_to_asm_recurate")

    out = capsys.readouterr().out
    assert "canonical priority" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dz11/github/grit && pytest tests/test_pretext_to_asm_recurate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'grit.steps.post_curation.pretext_to_asm_recurate'`.

- [ ] **Step 3: Create `grit/steps/post_curation/pretext_to_asm_recurate.py`**

```python
"""Step: re-run pretext-to-asm on a curated remapped Hi-C map ("curation of curated map")."""

from __future__ import annotations

import glob
import logging
from pathlib import Path

import rich_click as click

from grit.core.base_command import GritCommand
from grit.core.context import CurationContext
from grit.steps.post_curation.pretext_to_asm import _run_pretext_to_asm_core
from grit.utils.helpers import find_canonical_fa, find_canonical_haplotigs
from grit.utils.output import console, print_step_header, print_tip

log = logging.getLogger(__name__)

_RECURATE_TIP = (
    "This uses the current canonical FASTA as input. If you still need to run "
    "blast-contaminants, rename-and-orient, or microchromosome-combine on this "
    "haplotype, do that BEFORE running pretext-to-asm-recurate — recuration "
    "output always takes canonical priority over those steps once it exists.\n"
    "To reverse this: grit untrack --step {step_name} -t <ticket>"
)

_NEW_HAPLOTIGS_GLOBS = (
    "*.additional_haplotigs.curated.fa",
    "*.all_haplotigs.curated.fa",
    "*.haplotigs.fa",
)


def _output_specs_for_hap(hap_prefix: str) -> list[tuple[str, str, list[str]]]:
    return [
        (
            f"{hap_prefix}_fa",
            "{tol_id}.*.primary.curated.fa",
            ["hap1", "hap2", "all_haplotigs", "additional_haplotigs"],
        ),
        (f"{hap_prefix}_chr_list", "{tol_id}.*.primary.chromosome.list.csv", []),
        (f"{hap_prefix}_haplotigs", f"{hap_prefix}.recurate_haplotigs.fa", []),
    ]


def _merge_haplotigs_transform(hap_prefix: str, prior_haplotigs: Path | None):
    """Build the output_transform hook that merges haplotigs before collect_outputs runs."""

    def _transform(run_dir: Path) -> None:
        new_matches: list[str] = []
        for pattern in _NEW_HAPLOTIGS_GLOBS:
            new_matches = glob.glob(str(run_dir / pattern))
            if new_matches:
                break
        new_haplotigs = Path(sorted(new_matches)[-1]) if new_matches else None

        prior_nonempty = bool(
            prior_haplotigs and prior_haplotigs.exists() and prior_haplotigs.stat().st_size > 0
        )
        new_nonempty = bool(
            new_haplotigs and new_haplotigs.exists() and new_haplotigs.stat().st_size > 0
        )

        if not prior_nonempty and not new_nonempty:
            return  # nothing to track

        merged_path = run_dir / f"{hap_prefix}.recurate_haplotigs.fa"
        if prior_nonempty and new_nonempty:
            merged_path.write_text(prior_haplotigs.read_text() + new_haplotigs.read_text())
        elif prior_nonempty:
            merged_path.write_text(prior_haplotigs.read_text())
        else:
            merged_path.write_text(new_haplotigs.read_text())

    return _transform


def run_pretext_to_asm_recurate(ctx: CurationContext, hap_prefix: str, step_name: str) -> Path:
    """
    Re-runs pretext-to-asm for one haplotype using the current canonical FASTA
    as input and a hap-qualified AGP from ``{workdir}/recurate/``.

    Merges haplotigs with whatever was canonical for this haplotype before
    this run (plain FASTA concatenation) — see ``_merge_haplotigs_transform``.

    Tracked under *step_name* (``pretext_to_asm_recurate`` for hap1,
    ``pretext_to_asm_recurate_hap2`` for hap2) so each haplotype's recuration
    status is fully independent.
    """
    log.info(
        "pretext-to-asm-recurate | ticket=%s tol_id=%s hap=%s",
        ctx.ticket_id,
        ctx.tol_id,
        hap_prefix,
    )
    print_step_header(ctx.ticket_id, ctx.tol_id, f"Pretext to ASM recurate ({hap_prefix})")
    print_tip(_RECURATE_TIP.format(step_name=step_name))

    prior_haplotigs: Path | None = None
    try:
        prior_haplotigs = find_canonical_haplotigs(ctx, hap_prefix)
    except FileNotFoundError:
        prior_haplotigs = None

    original_fa = find_canonical_fa(ctx, hap_prefix)
    agp_search_dir = ctx.workdir / "recurate"

    return _run_pretext_to_asm_core(
        ctx,
        step_name,
        original_fa,
        f"No canonical FASTA found for {hap_prefix!r}. Run pretext-to-asm first.",
        agp_search_dir,
        f"{ctx.tol_id}.fa",
        _output_specs_for_hap(hap_prefix),
        agp_glob=f"{ctx.tol_id}*{hap_prefix}*.agp*",
        output_transform=_merge_haplotigs_transform(hap_prefix, prior_haplotigs),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("pretext-to-asm-recurate", cls=GritCommand)
@click.option(
    "--hap2",
    "run_hap2",
    is_flag=True,
    default=False,
    help="Recurate hap2 instead of hap1.",
)
@click.pass_context
def pretext_to_asm_recurate_cmd(ctx, run_hap2):
    """Re-run pretext-to-asm on a curated remapped Hi-C map."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    hap_prefix = curation_ctx.hap2_prefix if run_hap2 else curation_ctx.hap1_prefix
    step_name = "pretext_to_asm_recurate_hap2" if run_hap2 else "pretext_to_asm_recurate"
    try:
        run_pretext_to_asm_recurate(curation_ctx, hap_prefix, step_name)
    except Exception:
        log.exception("pretext-to-asm-recurate failed")
        raise SystemExit(1)
```

The binary call happens inside `_run_pretext_to_asm_core` (in `pretext_to_asm.py`), not in this module — this is why the tests in Step 1 patch `grit.steps.post_curation.pretext_to_asm._run`/`grit.steps.post_curation.pretext_to_asm.glob.glob` (where the call actually happens) rather than this module's own namespace.

- [ ] **Step 4: Register the new command in `grit/core/click_cli.py`**

Add the import near the other `pretext_to_asm` import (around line 129):

```python
from grit.steps.post_curation.pretext_to_asm_recurate import (  # noqa: E402
    pretext_to_asm_recurate_cmd,
)
```

Add the registration near `cli.add_command(pretext_to_asm_cmd)` (around line 237):

```python
cli.add_command(pretext_to_asm_recurate_cmd)
```

- [ ] **Step 5: Run tests to verify they pass, then run the full existing suite**

Run: `cd /Users/dz11/github/grit && pytest tests/test_pretext_to_asm_recurate.py -v`
Expected: all PASS.

Run: `cd /Users/dz11/github/grit && pytest tests/ -v`
Expected: full suite PASSES.

Run: `cd /Users/dz11/github/grit && python -c "from grit.core.click_cli import cli; print('pretext-to-asm-recurate' in cli.commands)"`
Expected: prints `True`.

- [ ] **Step 6: Commit**

```bash
git add grit/steps/post_curation/pretext_to_asm_recurate.py grit/core/click_cli.py tests/test_pretext_to_asm_recurate.py
git commit -m "feat: add pretext-to-asm-recurate step and CLI command"
```

---

### Task 4: Layer recuration into canonical-file resolution as an unconditional top tier

**Files:**
- Modify: `grit/utils/helpers.py` (`find_canonical_fa`, `find_canonical_chr_list`, `find_canonical_haplotigs`)
- Test: `tests/test_helpers_canonical.py`

**Interfaces:**
- Consumes: tracker step names/output keys produced by Task 3 (`pretext_to_asm_recurate`/`_hap2`, keys `{hap_prefix}_fa`/`{hap_prefix}_chr_list`/`{hap_prefix}_haplotigs`).
- Produces: no new public functions — behavior change only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_helpers_canonical.py`:

```python
def test_recurate_wins_unconditionally_over_newer_rename_and_orient(mock_ctx, tmp_path):
    """Recuration is a fixed top tier — it wins even if rename_and_orient is
    re-run afterward with a newer mtime (unlike the mtime-tiered chain below it)."""
    import os

    tracker = _make_tracker(tmp_path, mock_ctx)
    recurate_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-01T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", recurate_dir, "success", outputs={"hap1_fa": str(recurate_fa)}
    )

    rao_dir = tmp_path / "rename_and_orient" / "2026-01-02T00_00_00"
    rao_fa = _write(rao_dir / f"{mock_ctx.tol_id}.hap1.primary.renamed.fa")
    tracker.finish("rename_and_orient", rao_dir, "success", outputs={"hap1_fa": str(rao_fa)})

    os.utime(recurate_fa, (1000, 1000))
    os.utime(rao_fa, (2000, 2000))  # newer, but must still lose to recurate

    assert find_canonical_fa(mock_ctx, "hap1") == recurate_fa


def test_recurate_absent_falls_through_to_existing_chain(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


def test_recurate_is_per_hap_independent(mock_ctx, tmp_path):
    """hap1 recurated, hap2 did not — hap2 must still resolve via the normal chain."""
    tracker = _make_tracker(tmp_path, mock_ctx)
    recurate_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-01T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", recurate_dir, "success", outputs={"hap1_fa": str(recurate_fa)}
    )

    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_hap2_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap2.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap2_fa": str(pta_hap2_fa)})

    assert find_canonical_fa(mock_ctx, "hap1") == recurate_fa
    assert find_canonical_fa(mock_ctx, "hap2") == pta_hap2_fa


def test_untracking_recurate_falls_back_to_pre_recuration_chain(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    pta_dir = tmp_path / "pretext_to_asm" / "2026-01-01T00_00_00"
    pta_fa = _write(pta_dir / f"{mock_ctx.tol_id}.hap1.1.curated.fa")
    tracker.finish("pretext_to_asm", pta_dir, "success", outputs={"hap1_fa": str(pta_fa)})

    recurate_dir = tmp_path / "pretext_to_asm_recurate" / "2026-01-02T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate", recurate_dir, "success", outputs={"hap1_fa": str(recurate_fa)}
    )
    assert find_canonical_fa(mock_ctx, "hap1") == recurate_fa

    tracker.untrack("pretext_to_asm_recurate")
    assert find_canonical_fa(mock_ctx, "hap1") == pta_fa


def test_recurate_hap2_step_name_used_for_hap2(mock_ctx, tmp_path):
    tracker = _make_tracker(tmp_path, mock_ctx)
    recurate_dir = tmp_path / "pretext_to_asm_recurate_hap2" / "2026-01-01T00_00_00"
    recurate_fa = _write(recurate_dir / f"{mock_ctx.tol_id}.1.primary.curated.fa")
    tracker.finish(
        "pretext_to_asm_recurate_hap2",
        recurate_dir,
        "success",
        outputs={"hap2_fa": str(recurate_fa)},
    )

    assert find_canonical_fa(mock_ctx, "hap2") == recurate_fa
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dz11/github/grit && pytest tests/test_helpers_canonical.py -k recurate -v`
Expected: FAIL (no recurate tier exists yet — resolution falls through to the normal chain, so `test_recurate_wins_unconditionally_over_newer_rename_and_orient` and the others asserting recurate wins fail).

- [ ] **Step 3: Add the unconditional top tier to `find_canonical_fa`**

In `grit/utils/helpers.py`, insert at the very top of `find_canonical_fa`'s body (before the `if ctx.tracker:` block added in Task 1):

```python
    if ctx.tracker:
        recurate_step = (
            "pretext_to_asm_recurate_hap2" if hap_prefix == ctx.hap2_prefix else "pretext_to_asm_recurate"
        )
        val = ctx.tracker.get_output(recurate_step, f"{hap_prefix}_fa")
        if val and Path(val).exists():
            return Path(val)
```

- [ ] **Step 4: Same for `find_canonical_chr_list`**

Insert at the top of `find_canonical_chr_list`'s body:

```python
    if ctx.tracker:
        recurate_step = (
            "pretext_to_asm_recurate_hap2" if hap_prefix == ctx.hap2_prefix else "pretext_to_asm_recurate"
        )
        val = ctx.tracker.get_output(recurate_step, f"{hap_prefix}_chr_list")
        if val and Path(val).exists():
            return Path(val)
```

- [ ] **Step 5: Same for `find_canonical_haplotigs`**

Insert at the top of `find_canonical_haplotigs`'s body:

```python
    if ctx.tracker:
        recurate_step = (
            "pretext_to_asm_recurate_hap2" if hap_prefix == ctx.hap2_prefix else "pretext_to_asm_recurate"
        )
        val = ctx.tracker.get_output(recurate_step, f"{hap_prefix}_haplotigs")
        if val and Path(val).exists():
            return Path(val)
```

- [ ] **Step 6: Run tests to verify they pass, then run the full existing suite**

Run: `cd /Users/dz11/github/grit && pytest tests/test_helpers_canonical.py -v`
Expected: all PASS, including Task 1's tests.

Run: `cd /Users/dz11/github/grit && pytest tests/ -v`
Expected: full suite PASSES.

- [ ] **Step 7: Manually verify `grit untrack` already works generically (no code change)**

Run: `cd /Users/dz11/github/grit && grep -n '"--step"' grit/core/click_cli.py`
Expected: shows `@click.option("--step", "-s", required=True, ...)` with no `type=click.Choice(...)` restriction — confirms the existing `untrack`/`--undo` CLI command already accepts `pretext_to_asm_recurate`/`pretext_to_asm_recurate_hap2` as free-text step names, matching what Step 4 of `TODO/44_pretext_to_asm_recurate.md`'s "escape hatch" relies on. No code change needed; this step is a verification checkpoint only.

- [ ] **Step 8: Commit**

```bash
git add grit/utils/helpers.py tests/test_helpers_canonical.py
git commit -m "feat(helpers): recurate output wins canonical-file resolution unconditionally"
```

---

### Task 5: `post-curation-recurate` composite command

**Files:**
- Create: `grit/steps/post_curation/post_curation_recurate.py`
- Modify: `grit/core/click_cli.py` (register the new command)
- Test: `tests/test_post_curation_recurate.py`

**Interfaces:**
- Consumes: `run_pretext_to_asm_recurate(ctx, hap_prefix, step_name)` from Task 3; `run_hic_remapping(ctx, *, run_hap1=True, run_hap2=False, ...)` from `grit/steps/post_curation/hic_remapping.py` (unchanged signature).
- Produces: `run_post_curation_recurate(ctx, *, run_hap2: bool = False) -> None` and Click command `post_curation_recurate_cmd`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_post_curation_recurate.py`:

```python
"""Tests for the post-curation-recurate composite step."""

from unittest.mock import patch

from grit.steps.post_curation.post_curation_recurate import run_post_curation_recurate


@patch("grit.steps.post_curation.post_curation_recurate.run_hic_remapping")
@patch("grit.steps.post_curation.post_curation_recurate.run_pretext_to_asm_recurate")
def test_default_runs_hap1_chain(mock_recurate, mock_hic, mock_ctx):
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    run_post_curation_recurate(mock_ctx)

    mock_recurate.assert_called_once_with(mock_ctx, "hap1", "pretext_to_asm_recurate")
    mock_hic.assert_called_once_with(mock_ctx, run_hap1=True, run_hap2=False)


@patch("grit.steps.post_curation.post_curation_recurate.run_hic_remapping")
@patch("grit.steps.post_curation.post_curation_recurate.run_pretext_to_asm_recurate")
def test_hap2_flag_runs_hap2_chain_exclusively(mock_recurate, mock_hic, mock_ctx):
    mock_ctx.hap1_prefix = "hap1"
    mock_ctx.hap2_prefix = "hap2"

    run_post_curation_recurate(mock_ctx, run_hap2=True)

    mock_recurate.assert_called_once_with(mock_ctx, "hap2", "pretext_to_asm_recurate_hap2")
    mock_hic.assert_called_once_with(mock_ctx, run_hap1=False, run_hap2=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/dz11/github/grit && pytest tests/test_post_curation_recurate.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `grit/steps/post_curation/post_curation_recurate.py`**

```python
"""Composite step: pretext-to-asm-recurate followed by hic-remapping, for one haplotype."""

from __future__ import annotations

import logging

import rich_click as click

from grit.core.base_command import GritCommand
from grit.steps.post_curation.hic_remapping import run_hic_remapping
from grit.steps.post_curation.pretext_to_asm_recurate import run_pretext_to_asm_recurate

log = logging.getLogger(__name__)


def run_post_curation_recurate(ctx, *, run_hap2: bool = False) -> None:
    """
    Run pretext-to-asm-recurate followed by hic-remapping for one haplotype.

    Recurates hap1 by default; pass ``run_hap2=True`` to recurate hap2
    instead — not in addition, unlike ``run_post_curation``'s ``--hap2``.
    """
    log.info("post-curation-recurate | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    hap_prefix = ctx.hap2_prefix if run_hap2 else ctx.hap1_prefix
    step_name = "pretext_to_asm_recurate_hap2" if run_hap2 else "pretext_to_asm_recurate"
    run_pretext_to_asm_recurate(ctx, hap_prefix, step_name)
    run_hic_remapping(ctx, run_hap1=not run_hap2, run_hap2=run_hap2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("post-curation-recurate", cls=GritCommand)
@click.option(
    "--hap2",
    "run_hap2",
    is_flag=True,
    default=False,
    help="Recurate hap2 instead of hap1.",
)
@click.pass_context
def post_curation_recurate_cmd(ctx, run_hap2):
    """Run pretext-to-asm-recurate + hic-remapping for one haplotype."""
    from grit.core.click_cli import build_context

    curation_ctx = build_context(ctx.obj)
    try:
        run_post_curation_recurate(curation_ctx, run_hap2=run_hap2)
    except Exception:
        log.exception("post-curation-recurate failed")
        raise SystemExit(1)
```

- [ ] **Step 4: Register the new command in `grit/core/click_cli.py`**

Add the import near `post_curation_cmd`'s import (around line 127):

```python
from grit.steps.post_curation.post_curation_recurate import (  # noqa: E402
    post_curation_recurate_cmd,
)
```

Add the registration near `cli.add_command(post_curation_cmd)` (around line 236):

```python
cli.add_command(post_curation_recurate_cmd)
```

- [ ] **Step 5: Run tests to verify they pass, then run the full existing suite**

Run: `cd /Users/dz11/github/grit && pytest tests/test_post_curation_recurate.py -v`
Expected: all PASS.

Run: `cd /Users/dz11/github/grit && pytest tests/ -v`
Expected: full suite PASSES.

Run: `cd /Users/dz11/github/grit && python -c "from grit.core.click_cli import cli; print('post-curation-recurate' in cli.commands)"`
Expected: prints `True`.

- [ ] **Step 6: Commit**

```bash
git add grit/steps/post_curation/post_curation_recurate.py grit/core/click_cli.py tests/test_post_curation_recurate.py
git commit -m "feat: add post-curation-recurate composite command"
```

---

### Task 6: `grit status` display parity — manifests and status labels

**Files:**
- Modify: `grit/core/manifests.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new — this is display-only polish, no other task depends on it.

- [ ] **Step 1: Add manifest entries**

In `grit/core/manifests.py`, add to `STEP_MANIFESTS` (near the existing `"pretext_to_asm"` entry):

```python
    "pretext_to_asm_recurate": {
        "dir": "run_dir",
        "files": ["{tol_id}*.curated.fa"],
    },
    "pretext_to_asm_recurate_hap2": {
        "dir": "run_dir",
        "files": ["{tol_id}*.curated.fa"],
    },
```

Add to `STEP_TO_STATUS` (near the existing `"pretext_to_asm"` entry):

```python
    "pretext_to_asm_recurate": "post_curation",
    "pretext_to_asm_recurate_hap2": "post_curation",
```

- [ ] **Step 2: Verify no test breakage**

Run: `cd /Users/dz11/github/grit && pytest tests/test_status.py tests/test_run_tracker.py -v`
Expected: all PASS (these dicts are read-only lookups keyed by step name; adding new keys cannot affect existing lookups).

- [ ] **Step 3: Commit**

```bash
git add grit/core/manifests.py
git commit -m "chore: add grit-status manifest entries for pretext-to-asm-recurate"
```

---

## Self-Review Notes

- **Spec coverage:** every numbered section of `TODO/44_pretext_to_asm_recurate.md` maps to a task above — new command/CLI shape (Task 3), step names (Task 3/4), input resolution (Task 3), AGP location (Task 3), output specs/haplotig merging (Task 3), canonical top tier (Task 4), composite command (Task 5), out-of-scope items are simply not built (no numbered-round scheme, no order validation beyond the tip, no dedup). The TODO 40 prerequisite is Task 1.
- **Type/name consistency checked:** `run_pretext_to_asm_recurate(ctx, hap_prefix, step_name)` signature is identical across Task 3 (definition), Task 4 (unaffected — Task 4 only touches `helpers.py`), and Task 5 (composite caller). Tracker step-name strings (`"pretext_to_asm_recurate"` / `"pretext_to_asm_recurate_hap2"`) and output keys (`{hap_prefix}_fa`/`_chr_list`/`_haplotigs`) are identical between Task 3's `_output_specs_for_hap`/`_merge_haplotigs_transform` and Task 4's lookups.
- **Patch targets double-checked:** the new step module never calls `_run`/`glob.glob` directly (both happen inside `_run_pretext_to_asm_core` in `pretext_to_asm.py`), so Task 3's tests patch `grit.steps.post_curation.pretext_to_asm._run`/`.glob.glob`, not the new module's own namespace — fixed inline in the plan, not left as a follow-up note.
