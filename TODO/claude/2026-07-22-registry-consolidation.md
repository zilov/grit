# Registry Consolidation (TODO 34, Variant A) Implementation Plan

**Status: DONE** — executed inline 2026-07-27 on `feat/registry-and-invalidation`, commits `6f5492a`..`5e39143`. All 4 tasks complete, `pytest tests/` green (same 4 pre-existing `test_pre_curation.py` failures as before, unrelated), print-only smoke check clean. `TODO/34_registry_consolidation.md` moved to `TODO/done/`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate `runs.jsonl` as a data store. `RegistryManager` (`~/.grit/registry_v2.json`) becomes the single source of truth for step history; `RunTracker` becomes a pure, workdir-scoped delegate over it — no dual-write, no fallback-to-file-on-disk branching.

**Architecture:** `RunTracker` keeps its existing public API (`start`, `finish`, `history`, `latest_run_dir`, `get_output`, `invalidate`, `pending_jobs`, `record_job`, `verify_outputs`, `log_path`) so none of its 8 call sites (`click_cli.py`, `cleanup.py`, `context.py`, `status.py`) change. Internally, every method that used to read/write `.grit/runs.jsonl` now reads/writes through an injected (or lazily-default) `RegistryManager` instance. `RunTracker.__init__` gains an optional `registry: RegistryManager | None` parameter for dependency injection in tests — production code never passes it and gets the real `~/.grit/registry_v2.json`-backed manager.

The `.grit/<step>/<timestamp>.log` per-run text log (subprocess stdout/stderr capture, written via `RunTracker.log_path()`) is unrelated to `runs.jsonl` and is **not** touched by this plan.

The `migrate-tracker` CLI command (`grit/core/click_cli.py`) reads `.grit/runs.jsonl` directly off disk (not through `RunTracker`) as a one-time bridge for tickets curated before this change. It stays exactly as-is — it is the intended permanent path for absorbing pre-existing `runs.jsonl` files into the registry, not a workaround to remove.

**Tech Stack:** Python 3.13, pytest, no new dependencies.

## Global Constraints

- Do not change the public method signatures of `RunTracker` used by existing call sites (`start`, `finish`, `history`, `latest_run_dir`, `get_output`, `invalidate`, `pending_jobs`, `record_job`, `verify_outputs`, `log_path`) — only add the new optional `registry` constructor kwarg.
- Do not touch `grit/core/click_cli.py`'s `migrate-tracker` command — it reads `runs.jsonl` directly and must keep working for tickets with pre-existing files.
- Every step ends with `pytest tests/ -q` passing (excluding the 4 pre-existing failures in `tests/test_pre_curation.py`, which are unrelated to this work and already failing on `main`).
- Follow existing code style: no comments unless explaining non-obvious WHY; `from __future__ import annotations`; dataclass/type-hint conventions already in the two files.

---

### Task 1: Strip `runs.jsonl` from `RunTracker`, add registry injection

**Files:**
- Modify: `grit/core/run_tracker.py` (entire file)
- Test: `tests/test_run_tracker.py` (entire file, rewritten)

**Interfaces:**
- Produces: `RunTracker(workdir: Path, *, print_only: bool = False, registry: RegistryManager | None = None)` — same public methods as before, no signature changes on any of them.
- Consumes: `RegistryManager` from `grit/core/registry.py` — `append_step(workdir, record)`, `get_steps(workdir, step=None)`, `patch_step_job_id(workdir, step, run_dir, job_id)` (all already exist, unchanged).

- [x] **Step 1: Rewrite `grit/core/run_tracker.py`**

Replace the entire file with:

```python
"""
RunTracker — per-ticket execution log and timestamped run-directory manager.

Storage layout:
    {workdir}/
        <step>/
            <ISO-timestamp>/    ← run_dir for repeatable steps
        .grit/
            <step>/
                <timestamp>.log ← per-run stdout/stderr capture

Step history itself lives in the global registry (RegistryManager,
~/.grit/registry_v2.json) — RunTracker is a workdir-scoped view over it, not
a separate store. Non-repeatable steps (setup, haplotig_files, …) still log
history the same way; their output files stay in workdir/ or the parent
step's run_dir.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from grit.core.registry import RegistryManager

log = logging.getLogger(__name__)


def _invalidated_dirs(records: list[dict]) -> set[str]:
    """Return the set of run_dirs whose most recent record status is 'invalidated'.

    Iterating forward means the last status seen for each run_dir wins, which
    correctly handles undo (a later 'success' re-enables a previously invalidated dir).
    """
    latest_status: dict[str, str] = {}
    for r in records:
        rd = r.get("run_dir")
        if rd:
            latest_status[rd] = r.get("status", "")
    return {rd for rd, st in latest_status.items() if st == "invalidated"}


class RunTracker:
    """Workdir-scoped view over the global registry's step history."""

    def __init__(
        self,
        workdir: Path,
        *,
        print_only: bool = False,
        registry: "RegistryManager | None" = None,
    ) -> None:
        self.workdir = workdir
        self.grit_dir = workdir / ".grit"
        self.print_only = print_only
        self._registry_obj = registry

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def start(
        self,
        step: str,
        ticket_id: str,
        tol_id: str,
        *,
        create_dir: bool = True,
        suffix: str = "",
        invalidated: bool = False,
    ) -> Path:
        """
        Record step start; create and return the timestamped run_dir.

        Pass ``create_dir=False`` for steps that place output directly in workdir
        and don't need a dedicated run subdirectory.
        Pass ``suffix`` to append a string to the timestamp (e.g. hap prefix) so
        that two steps started within the same second get unique run_dirs.
        Pass ``invalidated=True`` to mark the run as non-canonical from the start
        so that ``latest_run_dir`` never returns it.

        In print_only mode: returns a virtual path without touching the filesystem.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%S")
        dir_name = f"{ts}_{suffix}" if suffix else ts
        run_dir = self.workdir / step / dir_name

        if not self.print_only:
            if create_dir:
                run_dir.mkdir(parents=True, exist_ok=True)
            status = "invalidated" if invalidated else "started"
            self._registry.append_step(
                self.workdir,
                {
                    "step": step,
                    "timestamp": ts,
                    "status": status,
                    "ticket_id": ticket_id,
                    "tol_id": tol_id,
                    "run_dir": str(run_dir),
                    "job_id": None,
                },
            )
            log.debug("Run started: step=%s run_dir=%s invalidated=%s", step, run_dir, invalidated)

        return run_dir

    def finish(
        self,
        step: str,
        run_dir: Path,
        status: str,
        job_id: str | None = None,
        *,
        outputs: dict[str, str] | None = None,
    ) -> None:
        """
        Record step completion (status: 'success' | 'failed').

        Call this after the step's subprocess exits (or after bsub returns a job_id).
        For bsub-submitted jobs, call with status='started' and job_id set; the
        _state-update CLI command will write the final 'success'/'failed' entry
        when the job's -Ep epilogue fires.

        *outputs* maps semantic keys (e.g. 'hap1_fa', 'hap1_pretext') to absolute
        file path strings for the outputs produced by this step.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%S")
        record: dict = {
            "step": step,
            "timestamp": ts,
            "status": status,
            "run_dir": str(run_dir),
        }
        if job_id is not None:
            record["job_id"] = job_id
        if outputs is not None:
            record["outputs"] = outputs
        if not self.print_only:
            self._registry.append_step(self.workdir, record)
            log.debug("Run finished: step=%s status=%s", step, status)

    def record_job(self, step: str, run_dir: Path, job_id: str) -> None:
        """
        Update the latest 'started' entry for a bsub step to include the job_id.

        Called immediately after bsub returns the job ID, before the job finishes.
        """
        if self.print_only:
            return
        self._registry.patch_step_job_id(self.workdir, step, run_dir, job_id)

    def history(self, step: str | None = None) -> list[dict]:
        """Return all step records, optionally filtered by step name."""
        return self._registry.get_steps(self.workdir, step)

    def latest_run_dir(self, step: str) -> Path | None:
        """
        Return the run_dir of the last *successful* run for a step, or None.

        If the step only has a 'started' entry (bsub job still running or finished
        but _state-update hasn't fired yet), returns that run_dir as a fallback.
        Run dirs whose most recent record has status 'invalidated' are excluded.
        """
        runs = self.history(step)
        invalidated_dirs = _invalidated_dirs(runs)
        success_runs = [
            r for r in runs
            if r.get("status") == "success" and r.get("run_dir")
            and r["run_dir"] not in invalidated_dirs
        ]
        if success_runs:
            return Path(success_runs[-1]["run_dir"])
        started_runs = [
            r for r in runs
            if r.get("status") == "started" and r.get("run_dir")
            and r["run_dir"] not in invalidated_dirs
        ]
        if started_runs:
            return Path(started_runs[-1]["run_dir"])
        return None

    def get_output(self, step: str, key: str) -> str | None:
        """
        Return the path string for *key* from the latest successful run of *step*.

        Returns None if no successful run exists or the key is absent.
        Runs whose most recent record has status 'invalidated' are excluded.
        """
        runs = self.history(step)
        inv_dirs = _invalidated_dirs(runs)
        success_runs = [
            r for r in runs
            if r.get("status") == "success" and r.get("outputs")
            and r.get("run_dir") not in inv_dirs
        ]
        if not success_runs:
            return None
        return success_runs[-1]["outputs"].get(key)

    def invalidate(self, step: str, run_dir: Path | None = None) -> bool:
        """Mark the latest success run of *step* as invalidated. Returns True if found."""
        if run_dir is None:
            run_dir = self.latest_run_dir(step)
        if run_dir is None:
            return False
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%S")
        self._registry.append_step(
            self.workdir,
            {"step": step, "timestamp": ts, "status": "invalidated", "run_dir": str(run_dir)},
        )
        return True

    def pending_jobs(self) -> list[dict]:
        """Return records with status='started' that have a job_id (bsub jobs in flight).

        Excludes entries where a later terminal entry (success/failed) already
        exists for the same (step, run_dir) — prevents re-resolving finished jobs
        on every `grit status` call.
        """
        all_records = self.history()
        terminal = {"success", "failed"}
        latest: dict[tuple, str] = {}
        for r in all_records:
            key = (r.get("step"), r.get("run_dir"))
            latest[key] = r.get("status", "")
        return [
            r for r in all_records
            if r.get("status") == "started"
            and r.get("job_id")
            and latest.get((r.get("step"), r.get("run_dir"))) not in terminal
        ]

    # ------------------------------------------------------------------
    # Output verification
    # ------------------------------------------------------------------

    def verify_outputs(self, step: str, tol_id: str, run_dir: Path | None = None) -> str:
        """
        Check whether a step's expected output files are present.

        Returns one of: 'ok' | 'partial' | 'missing' | 'not_tracked' | 'no_files'
        """
        from grit.core.manifests import STEP_MANIFESTS

        manifest = STEP_MANIFESTS.get(step)
        if manifest is None:
            return "not_tracked"

        patterns = manifest.get("files", [])
        if not patterns:
            return "no_files"  # step verified via exit code only

        check_dir = run_dir if (run_dir and manifest.get("dir") == "run_dir") else self.workdir
        if not check_dir.exists():
            return "missing"

        found = 0
        for pattern in patterns:
            resolved = pattern.replace("{tol_id}", tol_id)
            matches = list(check_dir.glob(resolved))
            if matches:
                found += 1

        if found == len(patterns):
            return "ok"
        elif found > 0:
            return "partial"
        return "missing"

    # ------------------------------------------------------------------
    # Log path helper
    # ------------------------------------------------------------------

    def log_path(self, step: str, run_dir: Path) -> Path:
        """Return path for the per-run log file inside .grit/<step>/<ts>.log."""
        ts = run_dir.name
        step_log_dir = self.grit_dir / step
        step_log_dir.mkdir(parents=True, exist_ok=True)
        return step_log_dir / f"{ts}.log"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @property
    def _registry(self) -> "RegistryManager":
        if self._registry_obj is None:
            from grit.core.registry import RegistryManager
            self._registry_obj = RegistryManager()
        return self._registry_obj
```

Key changes from the current file: no `import json`, no `self.runs_log`, no `_append`, `history()`/`record_job()` no longer touch any file directly — everything routes through `self._registry`. The `_registry` property is no longer `Optional` / lazily-checked against "is this workdir registered" — it always resolves to a real `RegistryManager` (injected in tests, default-constructed in production, where `add_ticket()` has always already run by the time any tracker method is called).

- [x] **Step 2: Rewrite `tests/test_run_tracker.py`**

Replace the entire file with:

```python
"""Tests for RunTracker."""

from pathlib import Path

import pytest

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker


@pytest.fixture
def reg(tmp_path):
    return RegistryManager(registry_dir=tmp_path / ".grit_reg")


@pytest.fixture
def tracker(tmp_path, reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", tmp_path)
    return RunTracker(tmp_path, registry=reg)


def test_start_creates_run_dir(tracker, tmp_path):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    assert run_dir.exists()
    assert run_dir.parent.name == "pretext_to_asm"


def test_start_writes_to_registry(tracker):
    tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    records = tracker.history()
    assert len(records) == 1
    r = records[0]
    assert r["step"] == "pretext_to_asm"
    assert r["status"] == "started"
    assert r["ticket_id"] == "RC-1234"
    assert r["tol_id"] == "sDipInt39"


def test_finish_appends_success_record(tracker):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", run_dir, "success")
    records = tracker.history()
    assert len(records) == 2
    assert records[-1]["status"] == "success"
    assert records[-1]["run_dir"] == str(run_dir)


def test_finish_appends_failed_record(tracker):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", run_dir, "failed")
    records = tracker.history()
    assert records[-1]["status"] == "failed"


def test_history_filters_by_step(tracker):
    r1 = tracker.start("setup_curation", "RC-1234", "sDipInt39")
    tracker.finish("setup_curation", r1, "success")
    r2 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", r2, "success")

    setup_records = tracker.history("setup_curation")
    assert all(r["step"] == "setup_curation" for r in setup_records)
    assert len(setup_records) == 2  # started + finished


def test_latest_run_dir_returns_last_success(tracker):
    r1 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", r1, "failed")
    r2 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", r2, "success")

    result = tracker.latest_run_dir("pretext_to_asm")
    assert result == r2


def test_latest_run_dir_falls_back_to_started(tracker):
    r1 = tracker.start("qv", "RC-1234", "sDipInt39")
    # No finish call — bsub job still running

    result = tracker.latest_run_dir("qv")
    assert result == r1


def test_latest_run_dir_returns_none_when_no_history(tracker):
    result = tracker.latest_run_dir("nonexistent_step")
    assert result is None


def test_record_job_patches_started_entry(tracker):
    run_dir = tracker.start("sex_matcher", "RC-1234", "sDipInt39")
    tracker.record_job("sex_matcher", run_dir, "99999")

    records = tracker.history("sex_matcher")
    started = next(r for r in records if r["status"] == "started")
    assert started["job_id"] == "99999"


def test_pending_jobs_returns_started_with_job_id(tracker):
    r1 = tracker.start("qv", "RC-1234", "sDipInt39")
    tracker.record_job("qv", r1, "12345")
    tracker.start("sex_matcher", "RC-1234", "sDipInt39")
    # no job_id for sex_matcher yet

    pending = tracker.pending_jobs()
    assert len(pending) == 1
    assert pending[0]["job_id"] == "12345"


def test_print_only_does_not_write_history(tmp_path, reg):
    reg.add_ticket("RC-1234", "sDipInt39", "species", tmp_path)
    tracker = RunTracker(tmp_path, print_only=True, registry=reg)
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    assert not run_dir.exists()
    assert reg.get_steps(tmp_path) == []


def test_verify_outputs_ok(tracker):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    (run_dir / "sDipInt39.1.hap1.curated.fa").write_text(">seq\n")
    (run_dir / "sDipInt39.1.curated.agp").write_text("")

    result = tracker.verify_outputs("pretext_to_asm", "sDipInt39", run_dir)
    assert result == "ok"


def test_verify_outputs_missing(tracker):
    run_dir = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    # No files created

    result = tracker.verify_outputs("pretext_to_asm", "sDipInt39", run_dir)
    assert result == "missing"


def test_verify_outputs_not_tracked(tracker):
    result = tracker.verify_outputs("unknown_step", "sDipInt39", None)
    assert result == "not_tracked"


def test_verify_outputs_setup_curation_checks_workdir(tracker, tmp_path):
    (tmp_path / "original.fa").write_text(">seq\n")
    tracker.start("setup_curation", "RC-1234", "sDipInt39")

    result = tracker.verify_outputs("setup_curation", "sDipInt39")
    assert result == "ok"


def test_invalidate_marks_latest_success(tracker):
    r1 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39", suffix="a")
    tracker.finish("pretext_to_asm", r1, "success")
    r2 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39", suffix="b")
    tracker.finish("pretext_to_asm", r2, "success")

    result = tracker.invalidate("pretext_to_asm")
    assert result is True
    # Latest success (r2) is now invalidated; previous success (r1) becomes canonical
    assert tracker.latest_run_dir("pretext_to_asm") == r1


def test_invalidate_returns_false_when_no_success(tracker):
    result = tracker.invalidate("nonexistent_step")
    assert result is False


def test_get_output_skips_invalidated(tracker):
    r1 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39", suffix="a")
    tracker.finish("pretext_to_asm", r1, "success", outputs={"fa": "/path/to/r1.fa"})
    r2 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39", suffix="b")
    tracker.finish("pretext_to_asm", r2, "success", outputs={"fa": "/path/to/r2.fa"})

    tracker.invalidate("pretext_to_asm")  # invalidates r2
    assert tracker.get_output("pretext_to_asm", "fa") == "/path/to/r1.fa"


def test_start_invalidated_never_canonical(tracker):
    tracker.start("qv", "RC-1234", "sDipInt39", invalidated=True)
    # Even though we have a run_dir, latest_run_dir should not return it
    assert tracker.latest_run_dir("qv") is None


def test_invalidate_undo(tracker):
    r1 = tracker.start("pretext_to_asm", "RC-1234", "sDipInt39")
    tracker.finish("pretext_to_asm", r1, "success", outputs={"fa": "/path/to/r1.fa"})
    tracker.invalidate("pretext_to_asm")
    assert tracker.latest_run_dir("pretext_to_asm") is None

    # Undo: append a success record for r1
    tracker.finish("pretext_to_asm", r1, "success", outputs={"fa": "/path/to/r1.fa"})
    assert tracker.latest_run_dir("pretext_to_asm") == r1
    assert tracker.get_output("pretext_to_asm", "fa") == "/path/to/r1.fa"


def test_history_reads_from_registry(tmp_path, reg):
    """RunTracker.history() is a pure view over RegistryManager.get_steps()."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    reg.add_ticket("RC-9999", "xbTest1", "species", workdir)
    reg.append_step(workdir, {
        "step": "pretext_to_asm",
        "timestamp": "2026-07-01T10_00_00",
        "status": "success",
        "run_dir": str(workdir / "pretext_to_asm" / "2026-07-01T10_00_00"),
        "job_id": None,
    })

    tracker = RunTracker(workdir, registry=reg)

    steps = tracker.history("pretext_to_asm")
    assert len(steps) == 1
    assert steps[0]["status"] == "success"

    all_steps = tracker.history()
    assert len(all_steps) == 1
```

Removed relative to the old file: `test_start_writes_to_runs_jsonl` (renamed to `test_start_writes_to_registry`, no jsonl assertion), `test_tracker_dual_writes_to_registry` (dual-write no longer exists — deleted outright), the `.grit/runs.jsonl` existence assertion in the print-only test (renamed to `test_print_only_does_not_write_history`, now asserts on `reg.get_steps()` instead).

- [x] **Step 3: Run the rewritten test file**

Run: `python -m pytest tests/test_run_tracker.py -v`
Expected: all tests PASS (20 tests → 19 after removing the dual-write test and merging two into one rename).

- [x] **Step 4: Commit**

```bash
git add grit/core/run_tracker.py tests/test_run_tracker.py
git commit -m "refactor(run_tracker): remove runs.jsonl, delegate entirely to RegistryManager"
```

---

### Task 2: Remove the `runs.jsonl` fallback from `RegistryManager`

**Files:**
- Modify: `grit/core/registry.py:159-199` (`refresh_statuses`), `:205-227` (`_refresh_pending_jobs`)
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `RunTracker(workdir, registry=self)` — the `registry` kwarg added in Task 1.
- Produces: no change to `RegistryManager`'s own public method signatures.

- [x] **Step 1: Edit `refresh_statuses`**

In `grit/core/registry.py`, replace:

```python
    def refresh_statuses(self) -> None:
        """
        Re-derive each active ticket's status from its step history.

        Reads from the registry steps array first; falls back to runs.jsonl
        via RunTracker for tickets not yet migrated. Skips done tickets.
        """
        from grit.core.manifests import STEP_TO_STATUS
        from grit.core.run_tracker import RunTracker

        self._refresh_pending_jobs()

        tickets = self._load()
        changed = False
        for ticket in tickets:
            if ticket.get("status") == "done":
                continue
            workdir = Path(ticket["workdir"])
            if not workdir.exists():
                continue
            history = ticket.get("steps", [])
            if not history:
                tracker = RunTracker(workdir)
                history = tracker.history()
            success_steps = [r["step"] for r in history if r.get("status") == "success"]
```

with:

```python
    def refresh_statuses(self) -> None:
        """
        Re-derive each active ticket's status from its step history.

        Skips done tickets.
        """
        from grit.core.manifests import STEP_TO_STATUS

        self._refresh_pending_jobs()

        tickets = self._load()
        changed = False
        for ticket in tickets:
            if ticket.get("status") == "done":
                continue
            workdir = Path(ticket["workdir"])
            if not workdir.exists():
                continue
            history = ticket.get("steps", [])
            success_steps = [r["step"] for r in history if r.get("status") == "success"]
```

- [x] **Step 2: Pass `registry=self` in `_refresh_pending_jobs`**

In the same file, replace:

```python
    def _refresh_pending_jobs(self) -> None:
        """Bulk-check all pending bsub jobs and write success/failed to each tracker."""
        from grit.core.run_tracker import RunTracker
        from grit.utils.helpers import _check_bjobs

        # Collect pending job_id → (tracker, entry, tol_id, hap1, hap2) across all active tickets
        pending: dict[str, tuple] = {}
        for ticket in self._load():
            if ticket.get("status") == "done":
                continue
            workdir = Path(ticket["workdir"])
            if not workdir.exists():
                continue
            tracker = RunTracker(workdir)
```

with:

```python
    def _refresh_pending_jobs(self) -> None:
        """Bulk-check all pending bsub jobs and write success/failed to each tracker."""
        from grit.core.run_tracker import RunTracker
        from grit.utils.helpers import _check_bjobs

        # Collect pending job_id → (tracker, entry, tol_id, hap1, hap2) across all active tickets
        pending: dict[str, tuple] = {}
        for ticket in self._load():
            if ticket.get("status") == "done":
                continue
            workdir = Path(ticket["workdir"])
            if not workdir.exists():
                continue
            tracker = RunTracker(workdir, registry=self)
```

This fixes a latent bug: previously, `RunTracker(workdir)` inside `_refresh_pending_jobs` always default-constructed its own `RegistryManager()` pointing at the real `~/.grit/registry_v2.json`, ignoring `self`'s `registry_dir` override (relevant for tests, and for any future multi-registry use). Passing `registry=self` makes it consistent.

- [x] **Step 3: Replace the obsolete jsonl-fallback test**

In `tests/test_registry.py`, delete `test_refresh_statuses` (the one that writes `.grit/runs.jsonl` by hand, lines ~81-105) — the code path it tests no longer exists. `test_refresh_statuses_reads_from_steps_array` (further down the file) already covers `refresh_statuses` via `append_step`, so no replacement test is needed — just remove the obsolete one.

- [x] **Step 4: Run affected tests**

Run: `python -m pytest tests/test_registry.py -v`
Expected: all PASS (one fewer test than before — the deleted one).

- [x] **Step 5: Commit**

```bash
git add grit/core/registry.py tests/test_registry.py
git commit -m "refactor(registry): drop runs.jsonl fallback in refresh_statuses"
```

---

### Task 3: Update the `fake_workdir` test fixture

**Files:**
- Modify: `tests/conftest.py:89-166` (`fake_workdir` fixture)

**Interfaces:**
- Consumes: `RegistryManager(registry_dir=...)`, `RunTracker(workdir, registry=...)` from Tasks 1-2.

This fixture is currently unused by any test (`grep -rn fake_workdir tests/*.py` shows only its own definition), but it hand-writes `.grit/runs.jsonl` and would silently produce a `RunTracker` that can never see that history after Task 1 (since `RunTracker` no longer reads jsonl at all). Fix it now so it doesn't rot further and is ready if a future test needs it.

- [x] **Step 1: Replace the `.grit/runs.jsonl` write with registry seeding**

In `tests/conftest.py`, replace:

```python
    # .grit/runs.jsonl
    grit_dir = tmp_path / ".grit"
    grit_dir.mkdir()
    runs = [
        {"step": "setup_curation", "timestamp": "2025-06-02T10_00_00", "status": "success",
         "ticket_id": mock_ctx.ticket_id, "tol_id": tol_id, "run_dir": str(tmp_path)},
        {"step": "pretext_to_asm", "timestamp": pta_ts, "status": "success",
         "ticket_id": mock_ctx.ticket_id, "tol_id": tol_id, "run_dir": str(pta_dir)},
        {"step": "hic_remapping", "timestamp": hic_ts, "status": "success",
         "ticket_id": mock_ctx.ticket_id, "tol_id": tol_id, "run_dir": str(hic_dir)},
    ]
    (grit_dir / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in runs) + "\n")

    # Attach a tracker pointing to the real tmp_path
    from grit.core.run_tracker import RunTracker
    mock_ctx.tracker = RunTracker(tmp_path)

    return tmp_path
```

with:

```python
    # Seed step history directly in an isolated registry
    from grit.core.registry import RegistryManager
    from grit.core.run_tracker import RunTracker

    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(mock_ctx.ticket_id, tol_id, "species", tmp_path)
    for step, ts, run_dir in [
        ("setup_curation", "2025-06-02T10_00_00", tmp_path),
        ("pretext_to_asm", pta_ts, pta_dir),
        ("hic_remapping", hic_ts, hic_dir),
    ]:
        reg.append_step(tmp_path, {
            "step": step, "timestamp": ts, "status": "success",
            "ticket_id": mock_ctx.ticket_id, "tol_id": tol_id, "run_dir": str(run_dir),
        })

    # Attach a tracker pointing to the real tmp_path
    mock_ctx.tracker = RunTracker(tmp_path, registry=reg)

    return tmp_path
```

Also update the docstring's layout diagram — replace the line:

```
            .grit/
                runs.jsonl                              (RunTracker log)
```

with:

```
            .grit_reg/
                registry_v2.json                        (isolated registry, seeded with step history)
```

Remove the now-unused `import json` at the top of the fixture if nothing else in it uses `json` (check the rest of the function body first — it doesn't, `json.dumps` was only used for the jsonl write).

- [x] **Step 2: Verify nothing broke**

Run: `python -m pytest tests/ -q`
Expected: same pass/fail counts as before this task (the fixture is unused, so this is a no-op verification — confirms the file still imports and collects cleanly).

- [x] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(conftest): update fake_workdir fixture to seed registry instead of runs.jsonl"
```

---

### Task 4: Full verification sweep and TODO bookkeeping

**Files:**
- None modified — verification only, plus moving `TODO/34_registry_consolidation.md`.

- [x] **Step 1: Grep for any remaining `runs.jsonl` reference outside the intended survivors**

Run:
```bash
grep -rln "runs\.jsonl" --include="*.py" .
```
Expected output: only `grit/core/click_cli.py` (the `migrate-tracker` command, intentionally unchanged) and `TODO/tiny.md`'s existing unrelated bug note (`runs count inflated 2x`) if it's a `.md` file matched by a broader grep — the `--include="*.py"` filter above should show **only** `grit/core/click_cli.py`. If anything else appears, that call site was missed — go back and fix it before proceeding.

- [x] **Step 2: Full test suite**

Run: `python -m pytest tests/ -q`
Expected: same 4 pre-existing failures in `tests/test_pre_curation.py` (unrelated `StopIteration`/mock issue, already broken on `main` before this work), all else PASS.

- [x] **Step 3: Manual smoke check of `grit status` in print-only mode**

Run: `grit --print-only status` (or `grit --yaml tests/fixtures/<some fixture>.yaml --print-only status -t RC-1234`, whichever matches this repo's existing manual-check convention)
Expected: no traceback; ticket table renders (even if empty/minimal in a throwaway environment).

- [x] **Step 4: Move TODO 34 to done**

```bash
git mv TODO/34_registry_consolidation.md TODO/done/34_registry_consolidation.md
git commit -m "docs(todo): move TODO 34 to done — runs.jsonl removed, RunTracker is a pure Registry delegate"
```

---

## Self-Review Notes (for the plan author, not a task)

- **Spec coverage:** TODO 34's implementation-order items 1-3 (Registry steps array, atomic save, RunTracker delegation) were already done before this plan; this plan closes items 3 (properly, not just "keep as thin wrapper" but "no dual-write") and effectively supersedes item 8 ("delete RunTracker") with the Variant-A decision: RunTracker stays as a class, but `runs.jsonl` — the thing item 8 actually cared about — is gone. Items 4 (step functions return `dict[str, Path] | None`) and 9 (`manifests.py` allowed-output-keys table) were explicitly scoped OUT of this plan per the Variant-A conversation — they are separate, larger changes not required to close the dual-write risk. If the user wants those too, they need a separate plan.
- **Placeholder scan:** no TBD/"add error handling"/"similar to Task N" — every step has full code.
- **Type consistency:** `RunTracker.__init__`'s new `registry` param type (`RegistryManager | None`) matches the `TYPE_CHECKING`-only import used for the annotation, avoiding a circular import (`registry.py` already imports `RunTracker` inside `refresh_statuses`/`_refresh_pending_jobs`, so `run_tracker.py` must not import `RegistryManager` at module level).
