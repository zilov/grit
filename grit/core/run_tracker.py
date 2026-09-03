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
~/.grit/grit_registry.json) — RunTracker is a workdir-scoped view over it, not
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


def _untracked_dirs(records: list[dict]) -> set[str]:
    """Return the set of run_dirs whose most recent record status is 'untracked'.

    Iterating forward means the last status seen for each run_dir wins, which
    correctly handles undo (a later 'success' re-enables a previously untracked dir).
    """
    latest_status: dict[str, str] = {}
    for r in records:
        rd = r.get("run_dir")
        if rd:
            latest_status[rd] = r.get("status", "")
    return {rd for rd, st in latest_status.items() if st == "untracked"}


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
        untracked: bool = False,
    ) -> Path:
        """
        Record step start; create and return the timestamped run_dir.

        Pass ``create_dir=False`` for steps that place output directly in workdir
        and don't need a dedicated run subdirectory.
        Pass ``suffix`` to append a string to the timestamp (e.g. hap prefix) so
        that two steps started within the same second get unique run_dirs.
        Pass ``untracked=True`` to mark the run as non-canonical from the start
        so that ``latest_run_dir`` never returns it.

        In print_only mode: returns a virtual path without touching the filesystem.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%S")
        dir_name = f"{ts}_{suffix}" if suffix else ts
        run_dir = self.workdir / step / dir_name

        if not self.print_only:
            if create_dir:
                run_dir.mkdir(parents=True, exist_ok=True)
            status = "untracked" if untracked else "started"
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
            log.debug("Run started: step=%s run_dir=%s untracked=%s", step, run_dir, untracked)

        return run_dir

    def finish(
        self,
        step: str,
        run_dir: Path,
        status: str,
        job_id: str | None = None,
        *,
        outputs: dict[str, str] | None = None,
        untracked: bool = False,
    ) -> None:
        """
        Record step completion (status: 'success' | 'failed').

        Call this after the step's subprocess exits (or after bsub returns a job_id).
        For bsub-submitted jobs, call with status='started' and job_id set; the
        _state-update CLI command will write the final 'success'/'failed' entry
        when the job's -Ep epilogue fires.

        *outputs* maps semantic keys (e.g. 'hap1_fa', 'hap1_pretext') to absolute
        file path strings for the outputs produced by this step.

        Pass ``untracked=True`` when the run this call finishes was started with
        ``start(untracked=True)``, so the recorded status stays 'untracked' instead
        of clobbering it with 'success'/'failed' (which would make the run
        canonical). *outputs* are still recorded, so a later call to
        ``finish(..., "success", outputs=...)`` without ``untracked`` (e.g. via
        `grit retrack`) can promote the run to canonical.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%S")
        record: dict = {
            "step": step,
            "timestamp": ts,
            "status": "untracked" if untracked else status,
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
        Run dirs whose most recent record has status 'untracked' are excluded.
        """
        runs = self.history(step)
        untracked_dirs = _untracked_dirs(runs)
        success_runs = [
            r
            for r in runs
            if r.get("status") == "success"
            and r.get("run_dir")
            and r["run_dir"] not in untracked_dirs
        ]
        if success_runs:
            return Path(success_runs[-1]["run_dir"])
        started_runs = [
            r
            for r in runs
            if r.get("status") == "started"
            and r.get("run_dir")
            and r["run_dir"] not in untracked_dirs
        ]
        if started_runs:
            return Path(started_runs[-1]["run_dir"])
        return None

    def get_output(self, step: str, key: str) -> str | None:
        """
        Return the path string for *key* from the latest successful run of *step*.

        Returns None if no successful run exists or the key is absent.
        Runs whose most recent record has status 'untracked' are excluded.
        """
        runs = self.history(step)
        untracked_dirs = _untracked_dirs(runs)
        success_runs = [
            r
            for r in runs
            if r.get("status") == "success"
            and r.get("outputs")
            and r.get("run_dir") not in untracked_dirs
        ]
        if not success_runs:
            return None
        return success_runs[-1]["outputs"].get(key)

    def untrack(self, step: str, run_dir: Path | None = None) -> bool:
        """Mark the latest success run of *step* as untracked. Returns True if found."""
        if run_dir is None:
            run_dir = self.latest_run_dir(step)
        if run_dir is None:
            return False
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H_%M_%S")
        self._registry.append_step(
            self.workdir,
            {"step": step, "timestamp": ts, "status": "untracked", "run_dir": str(run_dir)},
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
            r
            for r in all_records
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
