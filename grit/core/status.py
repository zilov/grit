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
        step_status = ""
        if workdir.exists():
            tracker = RunTracker(workdir)
            history = tracker.history()
            if history:
                last_entry = history[-1]
                last_step = last_entry.get("step", "")
                last_run = last_entry.get("timestamp", "")
                raw_status = last_entry.get("status", "")
                if raw_status == "success":
                    step_status = "[green]success[/green]"
                elif raw_status in ("failed",):
                    step_status = "[red]failed[/red]"
                elif raw_status == "started":
                    step_status = "[yellow]started[/yellow]"
                else:
                    step_status = raw_status
            status_display = step_status or t.get("status", "")
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

    ticket = registry.find_ticket(ticket_id)
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
    hic_hap2_success_run_dir: Path | None = None

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
                run_dir = Path(entry["run_dir"]) if entry.get("run_dir") else None
                if tracker.verify_outputs(step, tol_id, run_dir) in ("ok", "no_files"):
                    tracker.finish(step, run_dir, "success")
                    status = "success"
                else:
                    status = "unknown (gone)"

        if status == "started":
            status = "running"

        if step == "hic_remapping" and status == "success":
            hic_success_run_dir = Path(entry.get("run_dir", ""))
        if step == "hic_remapping_hap2" and status == "success":
            hic_hap2_success_run_dir = Path(entry.get("run_dir", ""))

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

    # Derive assembly_curated_dir: workdir = .../working/<user>_curation/<tol_id>/
    # assembly_curated_dir = .../assembly/curated/<tol_id>.<release>/
    curated_base = workdir.parent.parent.parent / "assembly" / "curated"
    curated_dirs = sorted(curated_base.glob(f"{tol_id}.*")) if curated_base.exists() else []
    curated_dir = curated_dirs[0] if curated_dirs else None

    print_curation_results(tracker, workdir, tol_id, curated_dir=curated_dir)

    farm_host = user_config.get("farm_host", "<farm_host>")

    fastga_entry = step_latest.get("fastga")
    if fastga_entry and fastga_entry.get("status") == "success":
        fastga_run_dir = Path(fastga_entry.get("run_dir", ""))
        if fastga_run_dir.exists():
            from grit.steps.optional.fastga import _fastga_scp_tip
            fastga_tip = _fastga_scp_tip(farm_host, fastga_run_dir, tol_id)
            if fastga_tip:
                print_tip(fastga_tip)

    if hic_success_run_dir:
        remapped_pattern = str(
            hic_success_run_dir / "pretext_maps_processed" / f"{tol_id}*normal.pretext"
        )
        print_tip(
            f"To copy remapped pretext map to your local machine:\n"
            f"[bold cyan]scp {farm_host}:'{remapped_pattern}' "
            f"~/curations/work/{tol_id}/{tol_id}_remapped.pretext[/bold cyan]"
        )
    if hic_hap2_success_run_dir:
        remapped_pattern_hap2 = str(
            hic_hap2_success_run_dir / "pretext_maps_processed" / f"{tol_id}*normal.pretext"
        )
        print_tip(
            f"To copy remapped hap2 pretext map to your local machine:\n"
            f"[bold cyan]scp {farm_host}:'{remapped_pattern_hap2}' "
            f"~/curations/work/{tol_id}/{tol_id}_hap2_remapped.pretext[/bold cyan]"
        )

    print_tip(
        f"To copy AGP from your local machine:\n"
        f"[bold cyan]scp ~/curations/work/{tol_id}/{tol_id}*.pretext.agp_1 "
        f"{farm_host}:{workdir}/[/bold cyan]"
    )

    from grit.utils.helpers import agp_newer_than_curated_fa
    pta_dir = tracker.latest_run_dir("pretext_to_asm")
    if agp_newer_than_curated_fa(workdir, tol_id, pta_dir):
        print_tip(
            f"AGP is newer than curated FASTA — re-run all post-curation steps:\n"
            f"[bold cyan]grit post-curation -t {ticket_id}[/bold cyan] "
            f"[dim](add --hap2 if you need to build both hap maps)[/dim]"
        )
    elif agp_files and not pta_dir:
        print_tip(
            f"AGP copied — run post-curation steps:\n"
            f"[bold cyan]grit post-curation -t {ticket_id}[/bold cyan] "
            f"[dim](add --hap2 if you need to build both hap maps)[/dim]"
        )
    elif hic_success_run_dir:
        print_tip(
            f"HiC remapping done — next step:\n"
            f"[bold cyan]grit finalize-qc -t {ticket_id}[/bold cyan]"
        )

    if curated_dir and (curated_dir / "merquryk").exists():
        print_tip("Submission notes: https://gist.github.com/zilov/93b1e6c68a6e2553b7c12770d6a0a3ef")
