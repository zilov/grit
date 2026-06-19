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

    def done_tickets(self, limit: int = 5) -> list[dict]:
        """Return the most recently completed tickets."""
        done = [t for t in self._load() if t.get("status") == "done"]
        return done[-limit:]

    def refresh_statuses(self) -> None:
        """
        Re-derive each active ticket's status from its runs.jsonl.

        Called by `grit status` to show up-to-date info without requiring
        every step to call update_status() perfectly. Skips done tickets.
        """
        from grit.core.manifests import STEP_TO_STATUS
        from grit.core.run_tracker import RunTracker

        tickets = self._load()
        changed = False
        for ticket in tickets:
            if ticket.get("status") == "done":
                continue
            workdir = Path(ticket["workdir"])
            if not workdir.exists():
                continue
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
        self.registry_path.write_text(json.dumps(data, indent=2))
