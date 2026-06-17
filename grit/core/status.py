"""Status display logic for `grit status` — global ticket list and per-ticket step history."""

from __future__ import annotations

import datetime
from pathlib import Path

from rich.table import Table

from grit.utils.output import console, print_curation_results, print_tip


def show_global_status(registry) -> None:
    """Print a table of all active tickets."""
    from grit.core.run_tracker import RunTracker

    tickets = registry.all_tickets()
    if not tickets:
        console.print("[dim]No active tickets. Run [bold]grit setup[/bold] to start curation.[/dim]")
        return

    table = Table(title="Active Curation Tickets", show_header=True, header_style="bold cyan")
    table.add_column("Ticket", style="bold")
    table.add_column("ToL ID")
    table.add_column("Species")
    table.add_column("Last Step")
    table.add_column("Last Run")
    table.add_column("Status", style="green")

    for t in tickets:
        workdir = Path(t["workdir"])
        last_step = ""
        last_run = ""
        if workdir.exists():
            tracker = RunTracker(workdir)
            history = tracker.history()
            if history:
                last_entry = history[-1]
                last_step = last_entry.get("step", "")
                last_run = last_entry.get("timestamp", "")
            status_display = t.get("status", "")
        else:
            status_display = "[red]workdir missing[/red]"
        table.add_row(
            t["ticket_id"],
            t.get("tol_id", ""),
            t.get("species", ""),
            last_step,
            last_run,
            status_display,
        )

    console.print(table)

    done = registry.done_tickets(limit=3)
    if done:
        console.print("\n[dim]Recently completed:[/dim]")
        for t in done:
            console.print(f"  [dim]{t['ticket_id']} ({t.get('tol_id', '')}) — {t.get('status', '')}[/dim]")


def show_ticket_history(registry, ticket_id: str, user_config: dict) -> None:
    """Print per-step run history and curation results for a single ticket."""
    from grit.core.run_tracker import RunTracker
    from grit.utils.helpers import _check_bjobs

    tickets = registry.all_tickets() + registry.done_tickets(limit=20)
    ticket = next((t for t in tickets if t["ticket_id"] == ticket_id), None)
    if ticket is None:
        console.print(f"[red]Ticket {ticket_id} not found in registry.[/red]")
        return

    workdir = Path(ticket["workdir"])
    if not workdir.exists():
        console.print(f"[yellow]Workdir not found: {workdir}[/yellow]")
        return

    tracker = RunTracker(workdir)
    history = tracker.history()
    tol_id = ticket.get("tol_id", "")

    # Poll bjobs for any pending jobs
    pending = tracker.pending_jobs()
    live_job_statuses: dict[str, str] = {}
    if pending:
        job_ids = [r["job_id"] for r in pending if r.get("job_id")]
        if job_ids:
            live_job_statuses = _check_bjobs(job_ids)

    # Aggregate by step: last run per step
    step_latest: dict[str, dict] = {}
    step_counts: dict[str, int] = {}
    for r in history:
        step = r.get("step", "")
        step_counts[step] = step_counts.get(step, 0) + 1
        step_latest[step] = r

    table = Table(
        title=f"Step history — {ticket_id} ({tol_id})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Step")
    table.add_column("Runs", justify="right")
    table.add_column("Last Run")
    table.add_column("Status")
    table.add_column("Job ID")

    hic_success_run_dir: Path | None = None

    for step, entry in step_latest.items():
        status = entry.get("status", "")
        job_id = entry.get("job_id") or ""
        ts = entry.get("timestamp", "")

        # Enrich bsub job status from live bjobs query
        if status == "started" and job_id and job_id in live_job_statuses:
            bjobs_status = live_job_statuses[job_id]
            if bjobs_status == "DONE":
                status = "done (check)"
            elif bjobs_status == "EXIT":
                status = "failed (job exited)"
            elif bjobs_status in ("RUN", "PEND"):
                status = f"running ({bjobs_status})"
            elif bjobs_status == "gone":
                status = "unknown (gone)"

        # hic_remapping: file-based check when job is gone or no job_id
        if step == "hic_remapping" and status in ("started", "unknown (gone)"):
            run_dir_path = Path(entry.get("run_dir", ""))
            if run_dir_path.exists() and any(
                run_dir_path.glob(f"pretext_maps_processed/{tol_id}*hr.pretext")
            ):
                status = "success"
                tracker.finish("hic_remapping", run_dir_path, "success")
            elif status == "started":
                status = "running"

        if step == "hic_remapping" and status == "success":
            hic_success_run_dir = Path(entry.get("run_dir", ""))

        style = ""
        if "success" in status:
            style = "green"
        elif "fail" in status or "EXIT" in status:
            style = "red"
        elif "running" in status or status == "started":
            style = "yellow"

        table.add_row(
            step,
            str(step_counts.get(step, 1)),
            ts,
            f"[{style}]{status}[/{style}]" if style else status,
            job_id,
        )

    agp_files = sorted(workdir.glob(f"{tol_id}*.pretext.agp_1"), key=lambda p: p.stat().st_mtime)
    if agp_files:
        agp_mtime = datetime.datetime.fromtimestamp(
            agp_files[-1].stat().st_mtime
        ).strftime("%Y-%m-%dT%H:%M:%S")
        table.add_row("agp_copied", "-", agp_mtime, "[green]found[/green]", "")
    else:
        table.add_row("agp_copied", "-", "", "[yellow]missing[/yellow]", "")

    console.print(table)

    print_curation_results(tracker, workdir, tol_id)

    farm_host = user_config.get("farm_host", "<farm_host>")

    if hic_success_run_dir:
        remapped_pattern = (
            f"{hic_success_run_dir}/pretext_maps_processed/{tol_id}*normal.pretext"
        )
        print_tip(
            f"To copy remapped pretext map to your local machine:\n"
            f"  [bold cyan]scp {farm_host}:{remapped_pattern} "
            f"~/curations/work/{tol_id}/[/bold cyan]"
        )

    print_tip(
        f"To copy AGP from your local machine:\n"
        f"  [bold cyan]scp ~/curations/work/{tol_id}/{tol_id}*.pretext.agp_1 "
        f"{farm_host}:{workdir}/[/bold cyan]"
    )

    last_success = next(
        (r["step"] for r in reversed(history) if r.get("status") == "success"),
        None,
    )
    if last_success == "setup_curation":
        print_tip(
            f"Curation done and AGP copied? Run post-curation steps:\n"
            f"  [bold cyan]grit post-curation -t {ticket_id}[/bold cyan]"
        )
    if hic_success_run_dir:
        print_tip(
            f"HiC remapping done — next step:\n"
            f"  [bold cyan]grit finalize-qc -t {ticket_id}[/bold cyan]"
        )
