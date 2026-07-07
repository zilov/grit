"""Cleanup disk space for done curation tickets."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import rich_click as click
from rich.table import Table

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.utils.output import console

log = logging.getLogger(__name__)

# Step dirs where we keep only the latest canonical run and delete older ones.
_STEPS_KEEP_LATEST = [
    "pretext_to_asm",
    "hic_remapping",
    "hic_remapping_hap2",
    "rename_and_orient",
    "fastga",
    "find_reference",
    "qv",
]

# Files in workdir root to delete.
_WORKDIR_FILES_TO_DELETE = ["original.fa"]


def _fmt_size(path: Path) -> str:
    """Return human-readable size via du -sh (fast, no rglob)."""
    import subprocess
    try:
        result = subprocess.run(
            ["du", "-sh", str(path)], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.split()[0]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "?"


def _latest_run_dir(tracker: RunTracker, step: str, step_dir: Path) -> Path | None:
    """Return the run_dir to keep: tracker's latest, or filesystem alphabetical last."""
    tracked = tracker.latest_run_dir(step)
    if tracked and tracked.exists():
        return tracked
    subdirs = sorted(d for d in step_dir.iterdir() if d.is_dir()) if step_dir.is_dir() else []
    return subdirs[-1] if subdirs else None


def plan_cleanup(workdir: Path, tol_id: str, tracker: RunTracker) -> list[Path]:
    """Return a list of paths that would be deleted for this workdir."""
    to_delete: list[Path] = []

    # 1. Older run dirs (keep only latest per step)
    for step in _STEPS_KEEP_LATEST:
        step_dir = workdir / step
        if not step_dir.is_dir():
            continue
        keep = _latest_run_dir(tracker, step, step_dir)
        for subdir in sorted(step_dir.iterdir()):
            if not subdir.is_dir():
                continue
            if keep and subdir.resolve() == keep.resolve():
                # Still delete work/ inside the kept run dir (Nextflow scratch)
                work_dir = subdir / "work"
                if work_dir.is_dir():
                    to_delete.append(work_dir)
            else:
                to_delete.append(subdir)

    # 2. Any remaining work/ dirs at any depth not already covered above
    for work_dir in workdir.rglob("work"):
        if work_dir.is_dir() and work_dir not in to_delete:
            # Only include if it looks like a Nextflow work dir (has hash subdirs)
            children = list(work_dir.iterdir())
            if children and all(len(c.name) == 2 for c in children if c.is_dir()):
                to_delete.append(work_dir)

    # 3. workdir root files
    for fname in _WORKDIR_FILES_TO_DELETE:
        fpath = workdir / fname
        if fpath.exists():
            to_delete.append(fpath)

    return to_delete


def run_cleanup(dry_run: bool = True) -> None:
    reg = RegistryManager()
    done = reg.done_tickets(limit=None)

    if not done:
        console.print("[yellow]No done tickets found in registry.[/yellow]")
        return

    table = Table(title="Cleanup plan", show_header=True, header_style="bold cyan")
    table.add_column("Ticket")
    table.add_column("ToL ID")
    table.add_column("Path")
    table.add_column("Size", justify="right")

    all_targets: list[tuple[str, Path]] = []  # (ticket_id, path)

    for ticket in done:
        ticket_id = ticket["ticket_id"]
        tol_id = ticket.get("tol_id", "")
        workdir = Path(ticket.get("workdir", ""))
        if not workdir.exists():
            log.debug("Workdir missing, skipping: %s", workdir)
            continue
        tracker = RunTracker(workdir)
        targets = plan_cleanup(workdir, tol_id, tracker)
        for t in targets:
            size = _fmt_size(t)
            table.add_row(ticket_id, tol_id, str(t), size)
            all_targets.append((ticket_id, t))

    if not all_targets:
        console.print("[green]Nothing to clean up.[/green]")
        return

    console.print(table)

    if dry_run:
        console.print(
            f"\n[yellow]Dry run — {len(all_targets)} item(s) listed above would be deleted. "
            "Pass [bold]--yes[/bold] to execute.[/yellow]"
        )
        return

    deleted = 0
    errors = 0
    for ticket_id, path in all_targets:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            log.info("Deleted: %s", path)
            deleted += 1
        except OSError as exc:
            log.warning("Could not delete %s: %s", path, exc)
            errors += 1

    console.print(
        f"\n[green]Deleted {deleted} item(s).[/green]"
        + (f" [red]{errors} error(s).[/red]" if errors else "")
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("cleanup")
@click.option("--yes", is_flag=True, default=False,
              help="Actually delete files (default: dry run, just show what would be removed).")
def cleanup_cmd(yes):
    """Free disk space for done tickets.

    Deletes Nextflow work/ dirs, older pretext_to_asm / hic_remapping run dirs
    (keeping only the latest canonical run), and original.fa from each workdir
    of tickets already marked as done.

    Runs as dry run by default — pass --yes to execute.
    """
    run_cleanup(dry_run=not yes)
