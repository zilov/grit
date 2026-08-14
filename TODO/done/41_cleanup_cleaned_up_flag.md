# TODO 41: track `cleaned_up` per ticket, skip re-scanning cleaned done tickets

## Problem

`grit cleanup` (`grit/core/cleanup.py::run_cleanup`) re-scans every done
ticket in the registry on every invocation via `plan_cleanup()`, which does
`du`/`stat` calls per file/dir. As the registry accumulates done tickets,
most of them have already been cleaned up in a prior run and have nothing
left to do — re-scanning them is pure overhead on Lustre.

## Design

### Registry: `cleaned_up` field

New per-ticket boolean field in `~/.grit/grit_registry.json` records:
`"cleaned_up": true`. Absent/`False` for tickets never cleaned (including
all pre-existing records — no migration needed, `.get("cleaned_up")` treats
missing as falsy).

`RegistryManager.done_tickets(limit=None, include_cleaned=False)`: by
default excludes tickets with `cleaned_up=True`; `include_cleaned=True`
returns all done tickets regardless of the flag.

New `RegistryManager.mark_cleaned_up(ticket_id)`, mirroring `mark_done()`.

### `run_cleanup`: mark tickets clean after a successful pass

`run_cleanup(dry_run=True, include_cleaned=False)` passes `include_cleaned`
through to `reg.done_tickets(limit=None, include_cleaned=include_cleaned)`.

Only on a real run (`not dry_run`): track errors per ticket_id while
applying delete/truncate/gzip-submit actions. After all actions for a
ticket are applied, if that ticket had zero errors, call
`reg.mark_cleaned_up(ticket_id)` — this also covers tickets whose
`plan_cleanup()` returned zero actions (already clean, no need to ever
rescan them again). Tickets with any `OSError` during delete/truncate, or a
failed gzip submission, are left unmarked so the next `grit cleanup` run
retries them.

Gzip jobs are fire-and-forget bsub submissions with no epilogue tracking
(unlike `_submit_bsub(..., epilogue_cmd=...)` elsewhere) — "success" here
means the job was submitted without error, not that pigz has finished. This
matches the existing fire-and-forget nature of this step; wiring up
epilogue-based completion tracking for gzip jobs is out of scope.

### CLI

`cleanup_cmd` gets a new flag:

```python
@click.option(
    "--include-cleaned",
    is_flag=True,
    default=False,
    help="Also rescan done tickets already marked cleaned_up (ignores the skip).",
)
```

passed through to `run_cleanup(dry_run=not yes, include_cleaned=include_cleaned)`.

### Tests

`tests/test_cleanup.py`:
- `done_tickets` called with `include_cleaned=False` by default from
  `run_cleanup`, and `include_cleaned=True` when the CLI flag is passed.
- `mark_cleaned_up` called for a ticket with zero actions.
- `mark_cleaned_up` called for a ticket whose actions all succeed.
- `mark_cleaned_up` NOT called when a delete raises `OSError`.
- `mark_cleaned_up` NOT called in dry-run mode.

`RegistryManager` itself may already have direct tests (check
`tests/test_registry.py` if it exists) — add cases for
`done_tickets(include_cleaned=...)` filtering and `mark_cleaned_up`.
