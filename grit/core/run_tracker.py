"""
RunTracker — per-ticket execution log and timestamped run-directory manager.

Storage layout:
    {workdir}/
        <step>/
            <ISO-timestamp>/    ← run_dir for repeatable steps
        .grit/
            runs.jsonl          ← append-only execution log (one JSON per line)
            <step>/
                <timestamp>.log ← per-run stdout/stderr capture

Non-repeatable steps (setup, haplotig_files, …) still log to runs.jsonl but
their output files stay in workdir/ or the parent step's run_dir.
"""

from __future__ import annotations

import glob
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class RunTracker:
    """Tracks step executions for a single ticket workdir."""

    def __init__(self, workdir: Path, *, print_only: bool = False) -> None:
        self.workdir = workdir
        self.grit_dir = workdir / ".grit"
        self.runs_log = self.grit_dir / "runs.jsonl"
        self.print_only = print_only

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def start(self, step: str, ticket_id: str, tol_id: str, *, create_dir: bool = True) -> Path:
        """
        Record step start; create and return the timestamped run_dir.

        Pass ``create_dir=False`` for steps that place output directly in workdir
        and don't need a dedicated run subdirectory.

        In print_only mode: returns a virtual path without touching the filesystem.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        run_dir = self.workdir / step / ts

        if not self.print_only:
            if create_dir:
                run_dir.mkdir(parents=True, exist_ok=True)
            self.grit_dir.mkdir(parents=True, exist_ok=True)
            self._append(
                {
                    "step": step,
                    "timestamp": ts,
                    "status": "started",
                    "ticket_id": ticket_id,
                    "tol_id": tol_id,
                    "run_dir": str(run_dir),
                    "job_id": None,
                }
            )
            log.debug("Run started: step=%s run_dir=%s", step, run_dir)

        return run_dir

    def finish(self, step: str, run_dir: Path, status: str, job_id: str | None = None) -> None:
        """
        Record step completion (status: 'success' | 'failed').

        Call this after the step's subprocess exits (or after bsub returns a job_id).
        For bsub-submitted jobs, call with status='started' and job_id set; the
        _state-update CLI command will write the final 'success'/'failed' entry
        when the job's -Ep epilogue fires.
        """
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        record: dict = {
            "step": step,
            "timestamp": ts,
            "status": status,
            "run_dir": str(run_dir),
        }
        if job_id is not None:
            record["job_id"] = job_id
        if not self.print_only:
            self._append(record)
            log.debug("Run finished: step=%s status=%s", step, status)

    def record_job(self, step: str, run_dir: Path, job_id: str) -> None:
        """
        Update the latest 'started' entry for a bsub step to include the job_id.

        Called immediately after bsub returns the job ID, before the job finishes.
        """
        if self.print_only or not self.runs_log.exists():
            return
        lines = self.runs_log.read_text().splitlines()
        # Find the last 'started' entry for this step + run_dir and add job_id
        updated = []
        patched = False
        for line in reversed(lines):
            if not patched:
                try:
                    r = json.loads(line)
                    if r.get("step") == step and r.get("run_dir") == str(run_dir) and r.get("status") == "started":
                        r["job_id"] = job_id
                        line = json.dumps(r)
                        patched = True
                except json.JSONDecodeError:
                    pass
            updated.append(line)
        self.runs_log.write_text("\n".join(reversed(updated)) + "\n")

    def history(self, step: str | None = None) -> list[dict]:
        """Return all log entries, optionally filtered by step name."""
        if not self.runs_log.exists():
            return []
        records = [json.loads(line) for line in self.runs_log.read_text().splitlines() if line.strip()]
        return [r for r in records if step is None or r.get("step") == step]

    def latest_run_dir(self, step: str) -> Path | None:
        """
        Return the run_dir of the last *successful* run for a step, or None.

        If the step only has a 'started' entry (bsub job still running or finished
        but _state-update hasn't fired yet), returns that run_dir as a fallback.
        """
        runs = self.history(step)
        # Prefer 'success' entries
        success_runs = [r for r in runs if r.get("status") == "success" and r.get("run_dir")]
        if success_runs:
            return Path(success_runs[-1]["run_dir"])
        # Fall back to last 'started' entry (job may still be running)
        started_runs = [r for r in runs if r.get("status") == "started" and r.get("run_dir")]
        if started_runs:
            return Path(started_runs[-1]["run_dir"])
        return None

    def pending_jobs(self) -> list[dict]:
        """Return records with status='started' that have a job_id (bsub jobs in flight)."""
        return [
            r for r in self.history()
            if r.get("status") == "started" and r.get("job_id")
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
            # Support subdirectory patterns like "pretext_maps_processed/*.pretext"
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

    def _append(self, record: dict) -> None:
        with self.runs_log.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
