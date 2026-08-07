"""Cleanup disk space for done curation tickets."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import rich_click as click
from rich.table import Table

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.utils.helpers import _submit_bsub, build_bsub_opts
from grit.utils.output import console

log = logging.getLogger(__name__)

# (kind, path); kind: "delete" | "truncate" | "gzip"
CleanupAction = tuple[str, Path]

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


def _size_bytes(path: Path) -> int | None:
    """Return apparent size in bytes via du --apparent-size (accurate on Lustre), or None."""
    import subprocess

    try:
        result = subprocess.run(
            ["du", "-sb", "--apparent-size", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0])
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _fmt_size(num_bytes: int | None) -> str:
    """Return a human-readable size (e.g. ``3.9G``) for a byte count, or ``?`` if unknown."""
    if num_bytes is None:
        return "?"
    size = float(num_bytes)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}{unit}"
        size /= 1024
    return f"{size:.1f}P"


def _latest_run_dir(tracker: RunTracker, step: str, step_dir: Path) -> Path | None:
    """Return the run_dir to keep: tracker's latest, or filesystem alphabetical last."""
    tracked = tracker.latest_run_dir(step)
    if tracked and tracked.exists():
        return tracked
    subdirs = sorted(d for d in step_dir.iterdir() if d.is_dir()) if step_dir.is_dir() else []
    return subdirs[-1] if subdirs else None


def _is_fastk_index_file(name: str) -> bool:
    """True for FastK per-thread index files (``*.ktab.N`` / ``*.post.N``)."""
    return ".ktab." in name or ".post." in name


def plan_cleanup(workdir: Path, tol_id: str, tracker: RunTracker) -> list[CleanupAction]:
    """Return a list of (kind, path) actions that would be applied for this workdir."""
    actions: list[CleanupAction] = []

    # 1. Older run dirs (keep only latest per step)
    kept_dirs: dict[str, Path] = {}
    for step in _STEPS_KEEP_LATEST:
        step_dir = workdir / step
        if not step_dir.is_dir():
            continue
        keep = _latest_run_dir(tracker, step, step_dir)
        if keep:
            kept_dirs[step] = keep
        for subdir in sorted(step_dir.iterdir()):
            if not subdir.is_dir():
                continue
            if keep and subdir.resolve() == keep.resolve():
                # Still delete work/ inside the kept run dir (Nextflow scratch)
                work_dir = subdir / "work"
                if work_dir.is_dir():
                    actions.append(("delete", work_dir))
            else:
                actions.append(("delete", subdir))

    # 1b. FastK index files inside any kept run dir (any step, not just two)
    for kept_dir in kept_dirs.values():
        if not kept_dir.is_dir():
            continue
        for f in kept_dir.iterdir():
            if f.is_file() and _is_fastk_index_file(f.name):
                actions.append(("delete", f))

    # 1c. find_reference kept dir: truncate the used reference, delete the rest
    ref_kept_dir = kept_dirs.get("find_reference")
    if ref_kept_dir and ref_kept_dir.is_dir():
        for f in ref_kept_dir.iterdir():
            if not f.is_file():
                continue
            if _is_fastk_index_file(f.name):
                continue  # already handled in 1b
            if f.name.endswith("_reheader.fna"):
                if f.stat().st_size > 0:
                    actions.append(("truncate", f))
            else:
                actions.append(("delete", f))

    # 1d. pretext_to_asm kept dir: gzip the curated fasta outputs
    ptoa_kept_dir = kept_dirs.get("pretext_to_asm")
    if ptoa_kept_dir and ptoa_kept_dir.is_dir():
        for f in sorted(ptoa_kept_dir.glob("*.fa")):
            if f.is_file() and f.stat().st_size > 0:
                actions.append(("gzip", f))

    # 2. Any remaining work/ dirs at any depth not already covered above
    already_deleted = {p for kind, p in actions if kind == "delete"}
    for work_dir in workdir.rglob("work"):
        if work_dir.is_dir() and work_dir not in already_deleted:
            # Only include if it looks like a Nextflow work dir (has hash subdirs)
            children = list(work_dir.iterdir())
            if children and all(len(c.name) == 2 for c in children if c.is_dir()):
                actions.append(("delete", work_dir))

    # 3. workdir root files
    for fname in _WORKDIR_FILES_TO_DELETE:
        fpath = workdir / fname
        if fpath.exists():
            actions.append(("delete", fpath))

    return actions


def run_cleanup(dry_run: bool = True) -> None:
    reg = RegistryManager()
    done = reg.done_tickets(limit=None)

    if not done:
        console.print("[yellow]No done tickets found in registry.[/yellow]")
        return

    table = Table(title="Cleanup plan", show_header=True, header_style="bold cyan")
    table.add_column("Action")
    table.add_column("Ticket")
    table.add_column("ToL ID")
    table.add_column("Path")
    table.add_column("Size", justify="right")

    all_targets: list[tuple[str, str, Path]] = []  # (ticket_id, kind, path)
    total_bytes = 0

    for ticket in done:
        ticket_id = ticket["ticket_id"]
        tol_id = ticket.get("tol_id", "")
        workdir = Path(ticket.get("workdir", ""))
        if not workdir.exists():
            log.debug("Workdir missing, skipping: %s", workdir)
            continue
        tracker = RunTracker(workdir)
        targets = plan_cleanup(workdir, tol_id, tracker)
        for kind, t in targets:
            num_bytes = _size_bytes(t)
            table.add_row(kind, ticket_id, tol_id, str(t), _fmt_size(num_bytes))
            all_targets.append((ticket_id, kind, t))
            total_bytes += num_bytes or 0

    if not all_targets:
        console.print("[green]Nothing to clean up.[/green]")
        return

    table.add_row("", "", "", "[bold]Total[/bold]", f"[bold]{total_bytes / 1024**3:.2f} GB[/bold]")
    console.print(table)

    if dry_run:
        console.print(
            f"\n[yellow]Dry run — {len(all_targets)} item(s) listed above would be applied. "
            "Pass [bold]--yes[/bold] to execute.[/yellow]"
        )
        return

    removed = 0
    gzip_submitted = 0
    errors = 0
    gzip_dirs_seen: set[Path] = set()

    for ticket_id, kind, path in all_targets:
        if kind == "delete":
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                log.info("Deleted: %s", path)
                removed += 1
            except OSError as exc:
                log.warning("Could not delete %s: %s", path, exc)
                errors += 1
        elif kind == "truncate":
            try:
                path.write_bytes(b"")
                log.info("Truncated: %s", path)
                removed += 1
            except OSError as exc:
                log.warning("Could not truncate %s: %s", path, exc)
                errors += 1
        elif kind == "gzip":
            parent = path.parent
            if parent in gzip_dirs_seen:
                continue
            gzip_dirs_seen.add(parent)
            inner_cmd = f"cd {parent} && pigz -p 8 *.fa"
            bsub_opts = build_bsub_opts(
                memory_mb=4000,
                cores=8,
                queue="normal",
                output="gzip_fa.out",
                error="gzip_fa.err",
                run_dir=parent,
            )
            job_id = _submit_bsub(inner_cmd, bsub_opts, dry_run)
            log.info("Submitted gzip job %s for %s", job_id, parent)
            gzip_submitted += 1
        else:  # pragma: no cover - defensive
            log.warning("Unknown cleanup action kind %r for %s", kind, path)

    console.print(
        f"\n[green]Removed/truncated {removed} item(s).[/green]"
        + (f" [cyan]{gzip_submitted} gzip job(s) submitted.[/cyan]" if gzip_submitted else "")
        + (f" [red]{errors} error(s).[/red]" if errors else "")
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@click.command("cleanup")
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Actually delete files (default: dry run, just show what would be removed).",
)
def cleanup_cmd(yes):
    """Free disk space for done tickets.

    For each workdir of tickets already marked as done:

    - Deletes older run dirs for every step in _STEPS_KEEP_LATEST (pretext_to_asm,
      hic_remapping, hic_remapping_hap2, rename_and_orient, fastga, find_reference,
      qv), keeping only the latest canonical run per step — this already covers
      removing non-canonical pretext_to_asm run dirs, no separate mechanism needed.
    - Deletes Nextflow work/ scratch dirs, both inside kept run dirs and anywhere
      else under the workdir.
    - Deletes original.fa from the workdir root.
    - Deletes FastK .ktab/.post per-thread index files found inside any kept
      run dir.
    - In find_reference's kept run dir: truncates the used *_reheader.fna to
      0 bytes (filename kept, so which reference was used stays visible)
      instead of deleting it, and deletes the raw downloaded reference plus
      its .1gdb/.bps/.gix index files.
    - In pretext_to_asm's kept run dir: gzips non-empty curated .fa files
      in place via a fire-and-forget bsub pigz job (one job per run dir).

    Runs as dry run by default — pass --yes to execute.
    """
    run_cleanup(dry_run=not yes)
