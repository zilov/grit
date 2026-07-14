"""
RegistryManager — global ticket registry stored in ~/.grit/registry.json.

All tickets live in a single file. The ``status`` field controls visibility:
active tickets (status != "done") appear in ``grit status``; done tickets are
filtered out but remain in the file so they can be returned to work and queried
later (e.g. ``grit summary`` for per-period counts).

Registry record format:
    {
        "ticket_id": "RC-1234",
        "tol_id": "xbLimHian1",
        "species": "Limanda limanda",
        "workdir": "/lustre/.../working/dz11_curation/xbLimHian1",
        "added_at": "2025-06-02T10:00:00Z",
        "status": "in_curation"
    }
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".grit"


class RegistryManager:
    """Manages the global ticket registry in ~/.grit/registry.json."""

    def __init__(self, registry_dir: Path | None = None) -> None:
        self.dir = registry_dir or _DEFAULT_DIR
        self.registry_path = self.dir / "registry.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_ticket(
        self,
        ticket_id: str,
        tol_id: str,
        species: str,
        workdir: Path,
        *,
        status: str = "in_curation",
    ) -> None:
        """
        Add or update a ticket entry in the registry.

        Called from setup_curation. Idempotent — calling again updates
        the status but preserves added_at.
        """
        self.dir.mkdir(exist_ok=True)
        tickets = self._load()

        existing = next((t for t in tickets if t["ticket_id"] == ticket_id), None)
        if existing:
            existing["status"] = status
            existing["tol_id"] = tol_id
            existing["species"] = species
            existing["workdir"] = str(workdir)
        else:
            tickets.append(
                {
                    "ticket_id": ticket_id,
                    "tol_id": tol_id,
                    "species": species,
                    "workdir": str(workdir),
                    "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": status,
                }
            )
            log.info("Registry: added ticket %s (%s)", ticket_id, tol_id)

        self._save(tickets)

    def update_status(self, ticket_id: str, status: str) -> None:
        """Update the status of any ticket."""
        tickets = self._load()
        for t in tickets:
            if t["ticket_id"] == ticket_id:
                t["status"] = status
                self._save(tickets)
                log.debug("Registry: %s → %s", ticket_id, status)
                return
        log.warning("Registry: ticket %s not found (cannot update status)", ticket_id)

    def mark_done(self, ticket_id: str) -> None:
        """Set ticket status to 'done'. Ticket stays in registry.json."""
        self.update_status(ticket_id, "done")
        log.info("Registry: ticket %s marked as done", ticket_id)

    def find_ticket(self, ticket_id: str) -> dict | None:
        """Find any ticket by ID regardless of status."""
        return next((t for t in self._load() if t["ticket_id"] == ticket_id), None)

    def all_tickets(self) -> list[dict]:
        """Return active tickets (status != 'done')."""
        return [t for t in self._load() if t.get("status") != "done"]

    def done_tickets(self, limit: int | None = 5) -> list[dict]:
        """Return the most recently completed tickets. Pass limit=None for all."""
        done = [t for t in self._load() if t.get("status") == "done"]
        return done[-limit:] if limit is not None else done

    def append_step(self, workdir: Path, record: dict) -> None:
        """Append a step record to the ticket matching workdir."""
        tickets = self._load()
        for t in tickets:
            if Path(t["workdir"]) == workdir:
                t.setdefault("steps", []).append(record)
                self._save(tickets)
                return
        log.warning("Registry: no ticket found for workdir %s", workdir)

    def get_steps(self, workdir: Path, step: str | None = None) -> list[dict]:
        """Return step records for ticket at workdir, optionally filtered by step name."""
        tickets = self._load()
        for t in tickets:
            if Path(t["workdir"]) == workdir:
                steps = t.get("steps", [])
                return [r for r in steps if step is None or r.get("step") == step]
        return []

    def patch_step_job_id(self, workdir: Path, step: str, run_dir: Path, job_id: str) -> None:
        """Set job_id on the latest started entry for (step, run_dir)."""
        tickets = self._load()
        for t in tickets:
            if Path(t["workdir"]) == workdir:
                steps = t.get("steps", [])
                for r in reversed(steps):
                    if (
                        r.get("step") == step
                        and r.get("run_dir") == str(run_dir)
                        and r.get("status") == "started"
                    ):
                        r["job_id"] = job_id
                        self._save(tickets)
                        return
        log.debug("Registry: job_id patch target not found for %s/%s", step, run_dir)

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
            if not success_steps:
                continue
            last_step = success_steps[-1]
            new_status = STEP_TO_STATUS.get(last_step, ticket["status"])
            tol_id = ticket.get("tol_id", "")
            if new_status == "in_curation" and tol_id and list(workdir.glob(f"{tol_id}*.pretext.agp_1")):
                new_status = STEP_TO_STATUS.get("agp_copied", new_status)
            if new_status == "done":
                ticket["status"] = "done"
                changed = True
            elif new_status != ticket["status"]:
                ticket["status"] = new_status
                changed = True

        if changed:
            self._save(tickets)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_pending_jobs(self) -> None:
        """Bulk-check all pending bsub jobs and write success/failed to each tracker."""
        from grit.core.run_tracker import RunTracker
        from grit.utils.helpers import _check_bjobs

        # Collect pending job_id → (tracker, entry, tol_id) across all active tickets
        pending: dict[str, tuple] = {}
        for ticket in self._load():
            if ticket.get("status") == "done":
                continue
            workdir = Path(ticket["workdir"])
            if not workdir.exists():
                continue
            tracker = RunTracker(workdir)
            tol_id = ticket.get("tol_id", "")
            for entry in tracker.pending_jobs():
                job_id = entry.get("job_id")
                if job_id and job_id not in pending:
                    pending[job_id] = (tracker, entry, tol_id)

        if not pending:
            return

        live = _check_bjobs(list(pending.keys()))

        for job_id, bjobs_status in live.items():
            if job_id not in pending:
                continue
            tracker, entry, tol_id = pending[job_id]
            step = entry.get("step", "")
            run_dir = Path(entry.get("run_dir", ""))

            if bjobs_status == "EXIT":
                tracker.finish(step, run_dir, "failed")
            elif bjobs_status == "gone":
                self._resolve_gone_job(tracker, step, run_dir, tol_id)

    @staticmethod
    def _resolve_gone_job(tracker, step: str, run_dir: Path, tol_id: str) -> None:
        """Resolve a gone bsub job via output file presence."""
        if step in ("hic_remapping", "hic_remapping_hap2"):
            matches = list(run_dir.glob(f"pretext_maps_processed/{tol_id}*hr.pretext")) if run_dir.exists() else []
            if matches:
                key = "hap1_pretext" if step == "hic_remapping" else "hap2_pretext"
                outputs = {key: str(sorted(matches)[-1])}
                tracker.finish(step, run_dir, "success", outputs=outputs)
            else:
                tracker.finish(step, run_dir, "failed")
        elif step == "sex_matcher":
            found = run_dir.exists() and any(run_dir.glob("Best_match*"))
            tracker.finish(step, run_dir, "success" if found else "failed")
        # other bsub steps: leave as-is until epilogue fix propagates

    def _load(self) -> list[dict]:
        if not self.registry_path.exists():
            return []
        try:
            return json.loads(self.registry_path.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Registry: could not read %s", self.registry_path)
            return []

    def _save(self, data: list[dict]) -> None:
        self.dir.mkdir(exist_ok=True)
        tmp = self.registry_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, self.registry_path)
