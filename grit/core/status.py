"""Status display logic for `grit status` — global ticket list and per-ticket step history."""

from __future__ import annotations

import datetime
from pathlib import Path

from rich.table import Table

from grit.utils.output import console, print_curation_results, print_tip, shorten_path
from grit.utils.result_parsers import find_lsf_log, parse_lsf_exit_reason


def show_global_status(registry) -> None:
    """Print a table of all active tickets."""
    from grit.core.run_tracker import RunTracker

    tickets = registry.all_tickets()
    if not tickets:
        console.print(
            "[dim]No active tickets. Run [bold]grit setup[/bold] to start curation.[/dim]"
        )
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
            console.print(
                f"  [dim]{t['ticket_id']} ({t.get('tol_id', '')}) — {t.get('status', '')}[/dim]"
            )


def _parse_ts(ts: str) -> datetime.datetime | None:
    """Parse either registry timestamp format (added_at or step timestamp)."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H_%M_%S"):
        try:
            return datetime.datetime.strptime(ts, fmt).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
    return None


def _last_ticket_timestamp(ticket: dict) -> datetime.datetime | None:
    """Best-effort timestamp for when a ticket last changed — latest step, else added_at."""
    steps = ticket.get("steps", [])
    if steps:
        parsed = _parse_ts(steps[-1].get("timestamp", ""))
        if parsed:
            return parsed
    return _parse_ts(ticket.get("added_at", ""))


def show_summary(registry) -> None:
    """Print active ticket counts by status, and done-ticket counts by time period."""
    from collections import Counter

    tickets = registry._load()
    active = [t for t in tickets if t.get("status") != "done"]
    done = [t for t in tickets if t.get("status") == "done"]

    status_counts = Counter(t.get("status", "unknown") for t in active)

    table = Table(title="Active tickets by status", show_header=True, header_style="bold cyan")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for status, count in sorted(status_counts.items(), key=lambda kv: -kv[1]):
        table.add_row(status, str(count))
    console.print(table)

    now = datetime.datetime.now(datetime.timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - datetime.timedelta(days=now.weekday())
    month_start = day_start.replace(day=1)
    quarter_start_month = (now.month - 1) // 3 * 3 + 1
    quarter_start = day_start.replace(month=quarter_start_month, day=1)

    week_n = month_n = quarter_n = 0
    for t in done:
        completed = _last_ticket_timestamp(t)
        if completed is None:
            continue
        if completed >= week_start:
            week_n += 1
        if completed >= month_start:
            month_n += 1
        if completed >= quarter_start:
            quarter_n += 1

    console.print()
    console.print(
        f"[bold]Done:[/bold] {len(done)} total — "
        f"{week_n} this week, {month_n} this month, {quarter_n} this quarter"
    )


def _canonical_haps(ctx) -> list[str]:
    """Haplotype prefixes to resolve canonical files for, given this ticket's assembly type."""
    return (
        [ctx.hap1_prefix]
        if ctx.hap1_prefix in ("primary", "paternal")
        else [ctx.hap1_prefix, ctx.hap2_prefix]
    )


def _resolve_canonical_files(ctx, haps: list[str]) -> dict[str, dict[str, Path | None]]:
    """
    Resolve the canonical fa/haplotigs/chr_list path per haplotype, keyed by
    hap then by "fa"/"haplotigs"/"chr_list". A value is None when the
    corresponding finder raised FileNotFoundError (nothing resolved yet).
    """
    from grit.utils.helpers import (
        find_canonical_chr_list,
        find_canonical_fa,
        find_canonical_haplotigs,
    )

    finders = {
        "fa": find_canonical_fa,
        "haplotigs": find_canonical_haplotigs,
        "chr_list": find_canonical_chr_list,
    }

    resolved: dict[str, dict[str, Path | None]] = {}
    for hap in haps:
        resolved[hap] = {}
        for key, finder in finders.items():
            try:
                resolved[hap][key] = finder(ctx, hap)
            except FileNotFoundError:
                resolved[hap][key] = None
    return resolved


_CANONICAL_TYPE_LABELS = {
    "fa": "assembly FA",
    "haplotigs": "haplotigs FA",
    "chr_list": "chr list",
}


def _print_canonical_files(ctx, resolved: dict[str, dict[str, Path | None]]) -> None:
    """Print a table of canonical output files found for this ticket."""
    table = Table(title="Canonical files", show_header=True, header_style="bold cyan")
    table.add_column("Hap")
    table.add_column("Type")
    table.add_column("File")
    table.add_column("Found", justify="center")

    for hap, by_type in resolved.items():
        for key, label in _CANONICAL_TYPE_LABELS.items():
            p = by_type.get(key)
            if p is None:
                found = "[red]✗[/red]"
                path_str = "[dim]not found[/dim]"
            else:
                found = "[green]✓[/green]"
                path_str = (
                    shorten_path(p, ctx.workdir)
                    if p.exists()
                    else f"[yellow]{shorten_path(p, ctx.workdir)}[/yellow]"
                )
            table.add_row(hap, label, path_str, found)

    console.print(table)
    console.print()


def _auto_step_outputs(
    step: str, run_dir: Path | None, tol_id: str, hap1: str = "hap1", hap2: str = "hap2"
) -> dict[str, str]:
    """
    Scan for known output files after a bsub job completes and return a populated
    outputs dict for storage in the tracker. Returns an empty dict when nothing
    can be determined (caller should pass None rather than {}).

    Same spec source (`_OUTPUT_SPECS` via `_get_step_specs`) as the normal
    `_state-update` epilogue path — this is the bjobs-polling fallback for when
    that epilogue never fired.
    """
    from grit.utils.helpers import _get_step_specs, collect_outputs

    if not run_dir or not run_dir.exists():
        return {}
    specs = _get_step_specs(step)
    if not specs:
        return {}
    return collect_outputs(specs, run_dir, tol_id, hap1=hap1, hap2=hap2)


# Steps whose recorded `outputs` (populated by the bsub -Ep epilogue, or by the
# bjobs-polling fallback in show_ticket_history for steps that don't use one)
# are worth offering to scp to the curator's local machine.
#
# `key_filter` restricts which output keys are offered — hic_remapping's
# specs include both the hr.pretext (curation input, stays on the farm) and
# normal.pretext (the one to download and view), so only the latter should
# be offered here.
_SCP_TIP_STEPS = [
    ("fastga", "FastGA results", None),
    ("busco_synteny", "busco-synteny plot", None),
    ("fastga_synteny", "fastga-synteny plot", None),
    ("hic_remapping", "remapped pretext map", ["hap1_normal_pretext"]),
    ("hic_remapping_hap2", "remapped hap2 pretext map", ["hap2_normal_pretext"]),
]

# Steps whose downloaded file should be renamed on copy rather than keeping
# its remote basename (e.g. "<tol_id>.hap1_normal.pretext" -> "<tol_id>.hap1_remapped.pretext").
_SCP_TIP_RENAME_STEPS = {"hic_remapping", "hic_remapping_hap2"}


def _print_scp_tips(step_latest: dict[str, dict], farm_host: str, tol_id: str) -> None:
    """Print an scp-download tip for each successful step in `_SCP_TIP_STEPS`."""
    from grit.utils.helpers import build_scp_tip

    for step, label, key_filter in _SCP_TIP_STEPS:
        entry = step_latest.get(step)
        if not entry or entry.get("status") != "success":
            continue
        outputs = entry.get("outputs") or {}
        if key_filter is not None:
            outputs = {k: v for k, v in outputs.items() if k in key_filter}
        files = sorted(outputs.values())
        dest_names = None
        if step in _SCP_TIP_RENAME_STEPS:
            dest_names = [
                Path(f).name.replace("_normal.pretext", "_remapped.pretext") for f in files
            ]
        tip = build_scp_tip(farm_host, tol_id, files, label, dest_names=dest_names)
        if tip:
            print_tip(tip)


# Steps whose recorded `outputs` hold a specific text file worth reading
# directly on the farm (via `less`) rather than downloading.
_LESS_TIP_STEPS = [
    ("fastga", "top_targets_summary", "top alignment targets"),
]


def _print_less_tips(step_latest: dict[str, dict]) -> None:
    """Print a `less`-on-the-farm tip for each successful step in `_LESS_TIP_STEPS`."""
    from grit.utils.helpers import build_less_tip

    for step, output_key, label in _LESS_TIP_STEPS:
        entry = step_latest.get(step)
        if not entry or entry.get("status") != "success":
            continue
        file = (entry.get("outputs") or {}).get(output_key)
        tip = build_less_tip(file, label)
        if tip:
            print_tip(tip)


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

    # Build CurationContext for summary + canonical files (requires Jira access)
    ctx = None
    try:
        from grit.core.context import CurationContext

        ctx = CurationContext.from_ticket(ticket_id, user_config, print_only=True)
    except Exception as exc:
        console.print(f"[dim]Could not build curation context: {exc}[/dim]")

    canonical_paths: set[str] = set()
    if ctx:
        from grit.steps.pre_curation.setup import print_curation_summary

        print_curation_summary(ctx)
        console.print()
        resolved_canonical = _resolve_canonical_files(ctx, _canonical_haps(ctx))
        _print_canonical_files(ctx, resolved_canonical)
        canonical_paths = {
            str(p) for by_type in resolved_canonical.values() for p in by_type.values() if p
        }

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
        if r.get("status") in ("success", "failed"):
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
    table.add_column("Canonical", justify="center")
    table.add_column("Job ID")

    memlimit_steps: list[str] = []

    for step, entry in step_latest.items():
        status = entry.get("status", "")
        job_id = entry.get("job_id") or ""
        ts = entry.get("timestamp", "")
        run_dir = Path(entry["run_dir"]) if entry.get("run_dir") else None

        # Enrich bsub job status from live bjobs query
        if status == "started" and job_id and job_id in live_job_statuses:
            bjobs_status = live_job_statuses[job_id]
            if bjobs_status in ("DONE", "gone"):
                # LSF reports the job itself as finished, but for steps that
                # shell out to an external pipeline (e.g. hic_remapping's
                # curationpretext.sh) grit never submitted the job itself, so
                # no -Ep epilogue was wired up to confirm real completion.
                # Check for the expected output files now rather than waiting
                # for the job to age out of `bjobs` history (which can take
                # hours) before ever verifying.
                if tracker.verify_outputs(step, tol_id, run_dir) in ("ok", "no_files"):
                    outputs = _auto_step_outputs(
                        step,
                        run_dir,
                        tol_id,
                        ticket.get("hap1_prefix", "hap1"),
                        ticket.get("hap2_prefix", "hap2"),
                    )
                    tracker.finish(step, run_dir, "success", outputs=outputs or None)
                    entry["outputs"] = outputs
                    entry["status"] = "success"
                    status = "success"
                else:
                    status = "done (check)" if bjobs_status == "DONE" else "unknown (gone)"
            elif bjobs_status == "EXIT":
                status = "failed (job exited)"
            elif bjobs_status in ("RUN", "PEND"):
                status = f"running ({bjobs_status})"

        if status == "started":
            status = "running"

        # Surface the LSF TERM_ reason (e.g. TERM_MEMLIMIT) for failed steps
        if "fail" in status and run_dir is not None:
            log_file = find_lsf_log(run_dir)
            reason = parse_lsf_exit_reason(log_file) if log_file else None
            if reason:
                status = f"{status} ({reason})"
                if reason == "TERM_MEMLIMIT":
                    memlimit_steps.append(step)

        style = ""
        if "success" in status:
            style = "green"
        elif "fail" in status or "EXIT" in status:
            style = "red"
        elif "running" in status or status == "started":
            style = "yellow"
        elif status == "untracked":
            style = "dim"

        outputs = entry.get("outputs") or {}
        is_canonical = any(v in canonical_paths for v in outputs.values())

        table.add_row(
            step,
            str(step_counts.get(step, 1)),
            ts,
            f"[{style}]{status}[/{style}]" if style else status,
            "[green]★[/green]" if is_canonical else "",
            job_id,
        )

    agp_files = sorted(workdir.glob(f"{tol_id}*.pretext.agp_1"), key=lambda p: p.stat().st_mtime)
    if agp_files:
        agp_mtime = datetime.datetime.fromtimestamp(agp_files[-1].stat().st_mtime).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        table.add_row("agp_copied", "-", agp_mtime, "[green]found[/green]", "", "")
    else:
        table.add_row("agp_copied", "-", "", "[yellow]missing[/yellow]", "", "")

    console.print(table)
    console.print()

    for step in memlimit_steps:
        print_tip(
            f"{step} hit the memory limit — re-run with a higher limit:\n"
            f"  grit {step.replace('_', '-')} -t {ticket_id} --bsub-ram <higher value>"
        )

    # Prefer the actually-used dir recorded by finalize_qc; fall back to deriving it:
    # workdir = .../working/<user>_curation/<tol_id>/
    # assembly_curated_dir = .../assembly/curated/<tol_id>.<release>/
    curated_dir_out = tracker.get_output("finalize_qc", "curated_dir") if tracker else None
    if curated_dir_out:
        curated_dir = Path(curated_dir_out)
    else:
        curated_base = workdir.parent.parent.parent / "assembly" / "curated"
        curated_dirs = sorted(curated_base.glob(f"{tol_id}.*")) if curated_base.exists() else []
        curated_dir = curated_dirs[0] if curated_dirs else None

    print_curation_results(tracker, workdir, tol_id, curated_dir=curated_dir)
    console.print()

    farm_host = user_config.get("farm_host", "<farm_host>")

    _print_scp_tips(step_latest, farm_host, tol_id)
    _print_less_tips(step_latest)

    print_tip(
        f"To copy AGP from your local machine:\n"
        f"[bold cyan]scp ~/curations/work/{tol_id}/{tol_id}*.pretext.agp_1 "
        f"{farm_host}:{workdir}/[/bold cyan]"
    )

    from grit.utils.helpers import inputs_newer_than_curated_fa

    pta_dir = tracker.latest_run_dir("pretext_to_asm")
    if inputs_newer_than_curated_fa(
        workdir, tol_id, pta_dir, extra_inputs=[workdir / "original.fa"]
    ):
        print_tip(
            f"AGP or original.fa is newer than curated FASTA — re-run all post-curation steps:\n"
            f"[bold cyan]grit post-curation -t {ticket_id}[/bold cyan] "
            f"[dim](add --hap2 if you need to build both hap maps)[/dim]"
        )
    elif agp_files and not pta_dir:
        print_tip(
            f"AGP copied — run post-curation steps:\n"
            f"[bold cyan]grit post-curation -t {ticket_id}[/bold cyan] "
            f"[dim](add --hap2 if you need to build both hap maps)[/dim]"
        )
    elif step_latest.get("hic_remapping", {}).get("status") == "success":
        print_tip(
            f"HiC remapping done — next step:\n"
            f"[bold cyan]grit finalize-qc -t {ticket_id}[/bold cyan]"
        )

    if (
        tol_id.startswith("b")
        and "microchromosome_second_shot" not in step_latest
        and "microchromosome_combine" not in step_latest
    ):
        print_tip(
            f"Bird genome — if it needs second-shot microchromosome curation:\n"
            f"[bold cyan]grit pretext-to-asm -t {ticket_id}[/bold cyan] then "
            f"[bold cyan]grit microchromosome-second-shot -t {ticket_id}[/bold cyan]"
        )

    if curated_dir and (curated_dir / "merquryk").exists():
        print_tip(
            "Submission notes: https://gist.github.com/zilov/93b1e6c68a6e2553b7c12770d6a0a3ef"
        )
