"""
RegistryManager — global ticket registry stored in ~/.grit/registry.json.

Tracks all tickets that have passed through `grit setup`. Completed tickets
are moved to ~/.grit/done.json when finalize_for_qc succeeds.

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
    """Manages the global ticket registry in ~/.grit/."""

    def __init__(self, registry_dir: Path | None = None) -> None:
        self.dir = registry_dir or _DEFAULT_DIR
        self.registry_path = self.dir / "registry.json"
        self.done_path = self.dir / "done.json"

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
        tickets = self._load(self.registry_path)

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

        self._save(self.registry_path, tickets)

    def update_status(self, ticket_id: str, status: str) -> None:
        """Update the status of an active ticket."""
        tickets = self._load(self.registry_path)
        for t in tickets:
            if t["ticket_id"] == ticket_id:
                t["status"] = status
                self._save(self.registry_path, tickets)
                log.debug("Registry: %s → %s", ticket_id, status)
                return
        log.warning("Registry: ticket %s not found (cannot update status)", ticket_id)

    def mark_done(self, ticket_id: str) -> None:
        """
        Move a ticket from the active registry to done.json.

        Called from finalize_for_qc on success.
        """
        tickets = self._load(self.registry_path)
        ticket = next((t for t in tickets if t["ticket_id"] == ticket_id), None)
        if ticket is None:
            log.warning("Registry: ticket %s not found (cannot mark done)", ticket_id)
            return

        ticket["status"] = "qc"
        done = self._load(self.done_path)
        # Replace any existing done entry for this ticket
        done = [t for t in done if t["ticket_id"] != ticket_id]
        done.append(ticket)
        self._save(self.done_path, done)

        remaining = [t for t in tickets if t["ticket_id"] != ticket_id]
        self._save(self.registry_path, remaining)
        log.info("Registry: ticket %s moved to done", ticket_id)

    def all_tickets(self) -> list[dict]:
        """Return all active tickets from the registry."""
        return self._load(self.registry_path)

    def done_tickets(self, limit: int = 5) -> list[dict]:
        """Return the most recently completed tickets."""
        done = self._load(self.done_path)
        return done[-limit:]

    def refresh_statuses(self) -> None:
        """
        Re-derive each active ticket's status from its runs.jsonl.

        Called by `grit status` to show up-to-date info without requiring
        every step to call update_status() perfectly.
        """
        from grit.core.manifests import STEP_TO_STATUS
        from grit.core.run_tracker import RunTracker

        tickets = self._load(self.registry_path)
        changed = False
        for ticket in tickets:
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
            if new_status != ticket["status"]:
                ticket["status"] = new_status
                changed = True

        if changed:
            self._save(self.registry_path, tickets)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("Registry: could not read %s", path)
            return []

    def _save(self, path: Path, data: list[dict]) -> None:
        self.dir.mkdir(exist_ok=True)
        path.write_text(json.dumps(data, indent=2))
