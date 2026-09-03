"""
RegistryManager — global ticket registry stored in ~/.grit/grit_registry.json.

All tickets live in a single file. The ``status`` field controls visibility:
active tickets (status != "done") appear in ``grit status``; done tickets are
filtered out but remain in the file so they can be returned to work and queried
later (e.g. ``grit status``'s done-ticket counts by time period).

Registry record format:
    {
        "ticket_id": "RC-1234",
        "tol_id": "xbLimHian1",
        "species": "Limanda limanda",
        "workdir": "/lustre/.../working/dz11_curation/xbLimHian1",
        "added_at": "2025-06-02T10:00:00Z",
        "status": "in_curation",
        "cleaned_up": false
    }

``cleaned_up`` is only set (to True) once ``grit cleanup`` has processed a
done ticket with no errors; absent/false means it hasn't been cleaned yet.

Durability. The registry is the only record of step history, and it is written
from every login and compute node over NFS, so reads and writes are deliberately
defensive:

* reading fails closed — an existing but unparseable registry raises
  ``RegistryError`` rather than reading as ``[]``, because an empty read
  followed by a write would erase every ticket;
* every write first copies the version it replaces to ``grit_registry.json.bak``
  and, once a day, to ``grit_registry.<date>.json`` (the last
  ``SNAPSHOT_RETENTION`` days are kept);
* writes install through a temp file named for the writing host and pid, so two
  concurrent writers cannot splice each other's partial output, and files are
  created mode 0600.

Writes are still not serialised across hosts: a concurrent read-modify-write can
lose a record. That fix is a storage-format decision, tracked separately.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import click

log = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".grit"
_REGISTRY_FILENAME = "grit_registry.json"

SNAPSHOT_RETENTION = 7


class RegistryError(click.ClickException):
    """The registry exists but cannot be trusted; refuse to read or overwrite it.

    A ClickException so the curator gets the message and exit code 1 rather than a
    traceback; it is still an ordinary exception when raised outside the CLI.
    """


def dry_run_root() -> Path:
    """Isolated sandbox root for --dry-run mode: never the real ~/.grit state."""
    return Path.home() / ".grit" / "dry_run"


class RegistryManager:
    """Manages the global ticket registry in ~/.grit/grit_registry.json."""

    def __init__(self, registry_dir: Path | None = None) -> None:
        self.dir = registry_dir or _DEFAULT_DIR
        self.registry_path = self.dir / _REGISTRY_FILENAME
        self.backup_path = self.dir / f"{_REGISTRY_FILENAME}.bak"

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
        hap1_prefix: str = "hap1",
        hap2_prefix: str = "hap2",
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
            existing["hap1_prefix"] = hap1_prefix
            existing["hap2_prefix"] = hap2_prefix
        else:
            tickets.append(
                {
                    "ticket_id": ticket_id,
                    "tol_id": tol_id,
                    "species": species,
                    "workdir": str(workdir),
                    "added_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": status,
                    "hap1_prefix": hap1_prefix,
                    "hap2_prefix": hap2_prefix,
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
        """Set ticket status to 'done'. Ticket stays in grit_registry.json."""
        self.update_status(ticket_id, "done")
        log.info("Registry: ticket %s marked as done", ticket_id)

    def mark_cleaned_up(self, ticket_id: str) -> None:
        """Set cleaned_up=True so future `grit cleanup` runs skip this ticket."""
        tickets = self._load()
        for t in tickets:
            if t["ticket_id"] == ticket_id:
                t["cleaned_up"] = True
                self._save(tickets)
                log.debug("Registry: %s marked cleaned_up", ticket_id)
                return
        log.warning("Registry: ticket %s not found (cannot mark cleaned_up)", ticket_id)

    def delete_ticket(self, ticket_id: str) -> dict | None:
        """Remove a ticket's entry from the registry entirely. Returns the removed
        entry, or None if no ticket with that ID was found."""
        tickets = self._load()
        removed = next((t for t in tickets if t["ticket_id"] == ticket_id), None)
        if removed is None:
            log.warning("Registry: ticket %s not found (cannot delete)", ticket_id)
            return None
        tickets = [t for t in tickets if t["ticket_id"] != ticket_id]
        self._save(tickets)
        log.info("Registry: deleted ticket %s (%s)", ticket_id, removed.get("tol_id", ""))
        return removed

    def find_ticket(self, ticket_id: str) -> dict | None:
        """Find any ticket by ID regardless of status."""
        return next((t for t in self._load() if t["ticket_id"] == ticket_id), None)

    def find_ticket_by_workdir(self, workdir: Path) -> dict | None:
        """Find any ticket by workdir path regardless of status."""
        return next((t for t in self._load() if Path(t["workdir"]) == workdir), None)

    def all_tickets(self) -> list[dict]:
        """Return active tickets (status != 'done')."""
        return [t for t in self._load() if t.get("status") != "done"]

    def done_tickets(self, limit: int | None = 5, include_cleaned: bool = False) -> list[dict]:
        """Return the most recently completed tickets. Pass limit=None for all.

        Excludes tickets already marked cleaned_up unless include_cleaned=True.
        """
        done = [t for t in self._load() if t.get("status") == "done"]
        if not include_cleaned:
            done = [t for t in done if not t.get("cleaned_up")]
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
            if not success_steps:
                continue
            last_step = success_steps[-1]
            new_status = STEP_TO_STATUS.get(last_step, ticket["status"])
            tol_id = ticket.get("tol_id", "")
            if (
                new_status == "in_curation"
                and tol_id
                and list(workdir.glob(f"{tol_id}*.pretext.agp_1"))
            ):
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

        # Collect pending job_id → (tracker, entry, tol_id, hap1, hap2) across all active tickets
        pending: dict[str, tuple] = {}
        for ticket in self._load():
            if ticket.get("status") == "done":
                continue
            workdir = Path(ticket["workdir"])
            if not workdir.exists():
                continue
            tracker = RunTracker(workdir, registry=self)
            tol_id = ticket.get("tol_id", "")
            hap1 = ticket.get("hap1_prefix", "hap1")
            hap2 = ticket.get("hap2_prefix", "hap2")
            for entry in tracker.pending_jobs():
                job_id = entry.get("job_id")
                if job_id and job_id not in pending:
                    pending[job_id] = (tracker, entry, tol_id, hap1, hap2)

        if not pending:
            return

        live = _check_bjobs(list(pending.keys()))

        for job_id, bjobs_status in live.items():
            if job_id not in pending:
                continue
            tracker, entry, tol_id, hap1, hap2 = pending[job_id]
            step = entry.get("step", "")
            run_dir = Path(entry.get("run_dir", ""))

            if bjobs_status == "EXIT":
                tracker.finish(step, run_dir, "failed")
            elif bjobs_status == "gone":
                self._resolve_gone_job(tracker, step, run_dir, tol_id, hap1, hap2)

    @staticmethod
    def _resolve_gone_job(
        tracker, step: str, run_dir: Path, tol_id: str, hap1: str = "hap1", hap2: str = "hap2"
    ) -> None:
        """Resolve a gone bsub job via output file presence."""
        from grit.utils.helpers import _get_step_specs, collect_outputs

        specs = _get_step_specs(step)
        if specs:
            outputs = collect_outputs(specs, run_dir, tol_id, hap1=hap1, hap2=hap2)
            tracker.finish(
                step, run_dir, "success" if outputs else "failed", outputs=outputs or None
            )
        elif step == "sex_matcher":
            found = run_dir.exists() and any(run_dir.glob("Best_match*"))
            tracker.finish(step, run_dir, "success" if found else "failed")
        # other bsub steps: leave as-is until epilogue fix propagates

    def _load(self) -> list[dict]:
        """Return the registry document; raise RegistryError if it exists but is unreadable."""
        if not self.registry_path.exists():
            return []
        try:
            return json.loads(self.registry_path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            raise RegistryError(self._unreadable_message(exc)) from exc

    def _unreadable_message(self, exc: Exception) -> str:
        """Curator-facing explanation of an unreadable registry, naming what to restore from."""
        lines = [
            f"Registry {self.registry_path} exists but could not be read ({exc}).",
            "Refusing to continue: writing now would replace it with an empty registry.",
        ]
        restore_from = [p for p in (self.backup_path, *reversed(self._snapshots())) if p.exists()]
        if restore_from:
            lines.append("Restore the newest one that looks right:")
            lines += [f"  cp {p} {self.registry_path}" for p in restore_from]
        else:
            lines.append(f"No backup found in {self.dir}.")
        return "\n".join(lines)

    def _snapshots(self) -> list[Path]:
        """Dated snapshot files, oldest first."""
        return sorted(self.dir.glob(f"{self.registry_path.stem}.2*.json"))

    def _save(self, data: list[dict]) -> None:
        self.dir.mkdir(exist_ok=True)
        if self.registry_path.exists():
            self._backup_current()
        self._atomic_write(self.registry_path, json.dumps(data, indent=2))

    def _backup_current(self) -> None:
        """Keep the version about to be replaced: always as .bak, once a day as a snapshot."""
        current = self.registry_path.read_text()
        self._atomic_write(self.backup_path, current)
        today = datetime.now().strftime("%Y-%m-%d")
        snapshot = self.dir / f"{self.registry_path.stem}.{today}.json"
        if not snapshot.exists():
            self._atomic_write(snapshot, current)
        for stale in self._snapshots()[:-SNAPSHOT_RETENTION]:
            stale.unlink(missing_ok=True)

    def _atomic_write(self, path: Path, text: str) -> None:
        """Install text at path via a temp file private to this writer, mode 0600."""
        tmp = path.with_name(f"{path.name}.tmp.{socket.gethostname()}.{os.getpid()}")
        try:
            tmp.write_text(text)
            tmp.chmod(0o600)
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
