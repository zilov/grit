"""Status display logic for `grit status` — global ticket list and per-ticket step history."""

from __future__ import annotations

import datetime
from pathlib import Path

from rich.table import Table

from grit.utils.output import console, print_curation_results, print_tip, shorten_path
from grit.utils.result_parsers import find_lsf_log, parse_lsf_exit_reason


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


_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)  # fmt: skip


def _prior_month_bounds(
    now: datetime.datetime, months_back: int
) -> tuple[datetime.datetime, datetime.datetime, str]:
    """Return (start, end, short label) for the calendar month `months_back`
    months before `now`'s month — e.g. months_back=1 is last month."""
    month = now.month - months_back
    year = now.year
    while month <= 0:
        month += 12
        year -= 1
    start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=year + 1, month=1) if month == 12 else start.replace(month=month + 1)
    return start, end, _MONTH_ABBR[month - 1]


def _last_ticket_timestamp(ticket: dict) -> datetime.datetime | None:
    """Best-effort timestamp for when a ticket last changed — latest step, else added_at."""
    steps = ticket.get("steps", [])
    if steps:
        parsed = _parse_ts(steps[-1].get("timestamp", ""))
        if parsed:
            return parsed
    return _parse_ts(ticket.get("added_at", ""))


def _ticket_age_display(added_at: str) -> str:
    """Render "days since added_at", colored green (<10d) / yellow (<20d) / red (>=20d)."""
    added = _parse_ts(added_at)
    if added is None:
        return ""
    age_days = (datetime.datetime.now(datetime.timezone.utc) - added).days
    style = "green" if age_days < 10 else "yellow" if age_days < 20 else "red"
    return f"[{style}]{age_days}[/{style}]"


def show_global_status(registry) -> None:
    """Print a table of all active tickets, plus overall done-ticket counts."""
    from grit.core.run_tracker import RunTracker

    tickets = registry.all_tickets()
    if not tickets:
        console.print(
            "[dim]No active tickets. Run [bold]grit setup[/bold] to start curation.[/dim]"
        )
    else:
        table = Table(title="Active Curation Tickets", show_header=True, header_style="bold cyan")
        table.add_column("Ticket", style="bold")
        table.add_column("Age (days)", justify="right")
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
                tracker = RunTracker(workdir, registry=registry)
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
                _ticket_age_display(t.get("added_at", "")),
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

    # Include already-cleaned-up tickets here (unlike the "Recently completed"
    # list above, which intentionally only surfaces done_tickets()'s still-relevant
    # set) — this is a historical throughput count, not a "what to look at" list.
    all_done = [t for t in registry._load() if t.get("status") == "done"]
    completed_dates = [d for t in all_done if (d := _last_ticket_timestamp(t)) is not None]

    now = datetime.datetime.now(datetime.timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - datetime.timedelta(days=now.weekday())
    month_start = day_start.replace(day=1)
    quarter_start_month = (now.month - 1) // 3 * 3 + 1
    quarter_start = day_start.replace(month=quarter_start_month, day=1)

    week_n = sum(1 for d in completed_dates if d >= week_start)
    month_n = sum(1 for d in completed_dates if d >= month_start)
    quarter_n = sum(1 for d in completed_dates if d >= quarter_start)

    console.print()
    console.print(
        f"[bold]Done:[/bold] {len(all_done)} total — "
        f"{week_n} this week, {month_n} this month, {quarter_n} this quarter"
    )

    monthly = [
        (label, sum(1 for d in completed_dates if start <= d < end))
        for start, end, label in (_prior_month_bounds(now, n) for n in (1, 2, 3))
    ]
    console.print(
        "[dim]Last 3 months:[/dim] " + ", ".join(f"{label} {count}" for label, count in monthly)
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

# Short codes for the step-history table's "Canonical" column — kept distinct
# from _CANONICAL_TYPE_LABELS (used by the wider "Canonical files" table).
_CANONICAL_TYPE_MARKS = {
    "fa": "fa",
    "haplotigs": "hap",
    "chr_list": "chr",
}


def _canonical_type_index(
    resolved: dict[str, dict[str, Path | None]],
) -> dict[str, list[tuple[str, str]]]:
    """Invert `_resolve_canonical_files`'s output into path -> [(type, hap), ...]."""
    index: dict[str, list[tuple[str, str]]] = {}
    for hap, by_type in resolved.items():
        for key, p in by_type.items():
            if p is None:
                continue
            index.setdefault(str(p), []).append((key, hap))
    return index


def _canonical_mark(
    outputs: dict, canonical_index: dict[str, list[tuple[str, str]]], haps: list
) -> str:
    """
    Render this row's "Canonical" cell: which output type(s) — and, when a
    ticket has more than one haplotype, which haplotype-index(es) — of its
    recorded `outputs` currently resolve as canonical. Empty string when none do.

    Kept deliberately compact (e.g. "fa(1),hap(1)") since this cell sits in a
    fixed-width table column alongside step names that already run long.
    """
    matches: list[tuple[str, str]] = []
    for v in outputs.values():
        matches.extend(canonical_index.get(str(v), []))
    if not matches:
        return ""

    hap_index = {hap: i + 1 for i, hap in enumerate(haps)}
    show_hap = len(haps) > 1

    haps_by_type: dict[str, list[str]] = {}
    for type_key, hap in matches:
        haps_by_type.setdefault(type_key, [])
        if hap not in haps_by_type[type_key]:
            haps_by_type[type_key].append(hap)

    parts = []
    for type_key in ("fa", "haplotigs", "chr_list"):
        matched_haps = haps_by_type.get(type_key)
        if not matched_haps:
            continue
        mark = _CANONICAL_TYPE_MARKS[type_key]
        if show_hap:
            indices = ",".join(str(hap_index.get(h, h)) for h in matched_haps)
            mark += f"({indices})"
        parts.append(mark)

    return f"[green]{','.join(parts)}[/green]"


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
    ("fastga_stats", "fastga-stats results", None),
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
    from grit.utils.helpers import MULTI_OUTPUT_SEP, build_scp_tip

    for step, label, key_filter in _SCP_TIP_STEPS:
        entry = step_latest.get(step)
        if not entry or entry.get("status") != "success":
            continue
        outputs = entry.get("outputs") or {}
        if key_filter is not None:
            outputs = {k: v for k, v in outputs.items() if k in key_filter}
        # A "multi" spec (e.g. fastga's "idx": one file per genome) joins its
        # matches into a single string — split back out into individual files.
        files = sorted(f for value in outputs.values() for f in value.split(MULTI_OUTPUT_SEP))
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
    ("fastga_stats", "top_targets_summary", "top alignment targets"),
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


def show_ticket_history(
    registry,
    ticket_id: str,
    user_config: dict,
    dry_run: bool = False,
    yaml_override: dict | None = None,
) -> None:
    """Print per-step run history and curation results for a single ticket.

    *yaml_override*, when set (from the group-level ``--yaml FILE`` option),
    bypasses the real Jira fetch when building the CurationContext — required
    for a synthetic dry-run ticket that has no real Jira issue to look up.
    """
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

    # Build CurationContext for summary + canonical files (requires Jira access
    # unless yaml_override is set)
    ctx = None
    try:
        from grit.core.context import CurationContext

        # print_only=True guards a real (non-dry-run) ticket from any accidental
        # side effect; for a dry-run ticket it must be False, since print_only
        # takes precedence over dry_run (CurationContext.from_yaml) and would
        # otherwise silently resolve ctx.workdir to the real, non-sandboxed path.
        ctx = CurationContext.from_ticket(
            ticket_id,
            user_config,
            yaml_override=yaml_override,
            print_only=not dry_run,
            dry_run=dry_run,
        )
    except Exception as exc:
        console.print(f"[dim]Could not build curation context: {exc}[/dim]")

    canonical_index: dict[str, list[tuple[str, str]]] = {}
    canonical_haps: list[str] = []
    if ctx:
        from grit.steps.pre_curation.setup import print_curation_summary

        print_curation_summary(ctx)
        console.print()
        canonical_haps = _canonical_haps(ctx)
        resolved_canonical = _resolve_canonical_files(ctx, canonical_haps)
        _print_canonical_files(ctx, resolved_canonical)
        canonical_index = _canonical_type_index(resolved_canonical)

    tracker = RunTracker(workdir, registry=registry)
    history = tracker.history()
    tol_id = ticket.get("tol_id", "")

    # Poll bjobs for any pending jobs
    pending = tracker.pending_jobs()
    live_job_statuses: dict[str, str] = {}
    if pending:
        job_ids = [r["job_id"] for r in pending if r.get("job_id")]
        if job_ids:
            live_job_statuses = _check_bjobs(job_ids)

    # Aggregate by step: full run history per step (in first-seen step order).
    step_history: dict[str, list[dict]] = {}
    for r in history:
        step_history.setdefault(r.get("step", ""), []).append(r)

    # Collapse all records of one run into a single row: a run accumulates
    # several records over its life ("started", the finish record, a later
    # `untrack`/`retrack`), and only the newest status for its run_dir is
    # current. The row keeps the run's own timestamp, its job_id and the
    # freshest recorded outputs.
    for step, entries in step_history.items():
        merged: list[dict] = []
        rows_by_run_dir: dict[str, dict] = {}
        for entry in entries:
            run_dir = entry.get("run_dir")
            if run_dir is None:
                merged.append(entry)
                continue
            row = rows_by_run_dir.get(run_dir)
            if row is None:
                row = dict(entry)
                rows_by_run_dir[run_dir] = row
                merged.append(row)
                continue
            row["status"] = entry.get("status", row.get("status"))
            if entry.get("job_id"):
                row["job_id"] = entry["job_id"]
            if entry.get("outputs"):
                row["outputs"] = entry["outputs"]
        step_history[step] = merged

    # Last run per step (used only by the tips below, not the table) — taken
    # from the merged rows so the table's bjobs-recovery updates are visible.
    step_latest: dict[str, dict] = {
        step: entries[-1] for step, entries in step_history.items() if entries
    }

    table = Table(
        title=f"Step history — {ticket_id} ({tol_id})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Step")
    table.add_column("Last Run")
    table.add_column("Status")
    table.add_column("Canonical", justify="center", no_wrap=True)
    table.add_column("Job ID")

    memlimit_steps: list[str] = []

    for step, entries in step_history.items():
        for entry in entries:
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
            canonical_mark = _canonical_mark(outputs, canonical_index, canonical_haps)

            table.add_row(
                step,
                ts,
                f"[{style}]{status}[/{style}]" if style else status,
                canonical_mark,
                job_id,
            )

    agp_files = sorted(workdir.glob(f"{tol_id}*.pretext.agp_1"), key=lambda p: p.stat().st_mtime)
    if agp_files:
        agp_mtime = datetime.datetime.fromtimestamp(agp_files[-1].stat().st_mtime).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        table.add_row("agp_copied", agp_mtime, "[green]found[/green]", "", "")
    else:
        table.add_row("agp_copied", "", "[yellow]missing[/yellow]", "", "")

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

    if step_latest.get("hic_remapping", {}).get("status") == "success":
        print_tip(
            "Curation of curated map (optional, before finalize-qc):\n"
            "1. cp the curated map locally, make edits — tag haplotigs/contaminants/unlocs "
            "as usual (don't forget to tag old unlocs), paint scaffolds, create an AGP file.\n"
            "2. scp the AGP file to the recurate folder:\n"
            f"   [bold cyan]scp ~/curations/work/{tol_id}/{tol_id}*remapped*.agp_1 "
            f"{farm_host}:{workdir}/recurate/[/bold cyan]\n"
            "3. Run it: "
            f"[bold cyan]grit post-curation-recurate -t {ticket_id}[/bold cyan] "
            f"(or [bold cyan]grit pretext-to-asm-recurate -t {ticket_id}[/bold cyan])\n"
            "4. Prefer running blast-contaminants / microchromosome-combine / "
            "rename-and-orient before this — recuration uses the current canonical FASTA "
            "as input."
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
