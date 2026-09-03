# 43. `grit remove` command

## Problem

There's no way to fully erase a ticket from grit's history. `grit done` only
flips status to `"done"` (still counted/listed via `grit summary` history and
`registry.done_tickets()`); there's no equivalent for "this ticket should
never have been tracked, or the curator wants to wipe it and start over."

Without this, re-running `grit setup -t RC-1234` for a ticket that was
abandoned and re-added collides with a stale registry entry, and there's no
sanctioned way to reclaim the disk space of a workdir the curator no longer
wants at all (as opposed to `grit cleanup`, which only trims a *done*
ticket's workdir down to canonical outputs).

## Design

### `RegistryManager.delete_ticket`

New method in `grit/core/registry.py`:

```python
def delete_ticket(self, ticket_id: str) -> dict | None:
    """Remove a ticket's entry from the registry entirely. Returns the removed
    entry, or None if no ticket with that ID was found."""
```

Loads all tickets, finds the entry matching `ticket_id`, filters it out,
saves, and returns the removed entry (so the caller has `tol_id`/`workdir`
for logging without a second lookup). Unlike `mark_done`/`update_status`,
this is a hard delete — no trace stays in `grit_registry.json`.

### `grit remove -t <ticket>` command

New command in `grit/core/click_cli.py` (same file/pattern as `done_cmd` /
`reopen_cmd`, no separate module needed — the logic is short):

```python
@cli.command("remove")
@click.option("--ticket", "-t", required=True, help="Ticket ID to permanently remove.")
@click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")
@click.pass_context
def remove_cmd(ctx, ticket, yes):
    """Permanently delete a ticket's registry entry and its workdir. Cannot be undone."""
```

Behavior:

1. Look up `ticket` via `reg.find_ticket()`. Error + exit 1 if not found —
   works for a ticket in any status (active or done).
2. Resolve `workdir = Path(entry["workdir"])`. Guard against a corrupted
   registry entry pointing somewhere dangerous: refuse (error + exit 1,
   without touching anything) if `workdir` is `Path.home()`, `Path("/")`, or
   has fewer than 4 path parts.
3. Print a `[bold red]WARNING[/bold red]` panel via `console.print()`
   listing exactly what will be deleted: the ticket ID, `tol_id`, and the
   full `workdir` path — and that this cannot be undone.
4. Unless `--yes`: prompt the user to type the ticket ID back
   (`click.prompt`); if the typed value doesn't match exactly, abort with
   exit 1 and touch nothing. `--yes` skips this prompt (for scripting) but
   the warning is still printed either way.
5. If `workdir.exists()`: `shutil.rmtree(workdir)`. If it's already gone,
   just log that and continue (not an error — the entry can still be stale
   without its workdir).
6. `reg.delete_ticket(ticket)`.
7. `print_done(...)` confirming both the workdir and registry entry are
   gone.

No `--print-only` support is needed — this command doesn't build a
`CurationContext` (same as `done`/`reopen`), so it's outside `ctx.print_only`
scope entirely; the confirmation prompt (or required `--yes`) is the dry-run
equivalent.

No new "removed" status, and no changes to `all_tickets()` /
`done_tickets()` / `refresh_statuses()` / `show_summary()` — the ticket is
just gone, so every existing status/summary query already excludes it for
free.

### Testing

`tests/test_registry.py`: unit tests for `delete_ticket` — deletes an
existing ticket and returns its entry; returns `None` and leaves the
registry untouched for a missing ticket ID.

A CLI-level test for `remove_cmd` using `CliRunner` + a `RegistryManager`
pointed at `tmp_path` (patch `_DEFAULT_DIR` or construct with
`registry_dir=tmp_path`, matching the existing `reg` fixture in
`test_registry.py`) and a real throwaway workdir under `tmp_path`:

- typed confirmation matching the ticket → workdir removed from disk,
  registry entry gone
- typed confirmation *not* matching → nothing deleted, exit code 1
- `--yes` → skips the prompt, still deletes
- ticket not in registry → error, exit code 1
- workdir already missing on disk → registry entry still removed, no crash
- workdir guard (e.g. entry patched to point at `Path.home()`) → refuses,
  nothing deleted

## Implementation plan

### Task 1 — `RegistryManager.delete_ticket`

- File: `grit/core/registry.py` — add `delete_ticket(self, ticket_id: str) -> dict | None`
  right after `mark_cleaned_up` (keeps the mutation methods grouped together).
  Load tickets, find the matching entry, filter it out, save, return the
  removed entry (or `None`/log a warning if not found — mirror the
  not-found handling already used in `update_status`).
- Tests: `tests/test_registry.py` — add near the existing `mark_done` tests,
  using the same `reg` fixture:
  - deleting an existing ticket returns its entry and removes it from
    `reg.all_tickets()` / `reg._load()`.
  - deleting a missing ticket ID returns `None` and leaves the registry
    file's contents unchanged.

### Task 2 — `grit remove` command

- File: `grit/core/click_cli.py` — add `remove_cmd` right after `reopen_cmd`
  (same section as `done`/`reopen`), registered the same way (decorated
  `@cli.command`, no explicit `cli.add_command` needed since it's declared
  directly under `@cli`, matching `done_cmd`/`reopen_cmd` above it).
  Implement exactly the 7 steps from the Design section above, including the
  path guard, the red warning via `console` (import from
  `grit.utils.output`), the typed-confirmation prompt, `shutil.rmtree`, and
  `print_done`.
- Tests: new `tests/test_remove_cmd.py` using `CliRunner` (see
  `tests/test_base_command.py` for the invocation pattern) and a
  `RegistryManager(registry_dir=tmp_path)` seeded with one ticket entry
  pointing at a real throwaway workdir under `tmp_path` (e.g.
  `tmp_path / "workdir"`, created with a dummy file inside so `rmtree`
  has something to remove). Since `remove_cmd` constructs
  `RegistryManager()` with no args internally, patch
  `grit.core.registry._DEFAULT_DIR` to `tmp_path` for the duration of each
  test (monkeypatch), rather than trying to inject a registry instance.
  Cover:
  - typed confirmation matching the ticket → workdir gone from disk,
    registry entry gone, exit code 0.
  - typed confirmation *not* matching the ticket → workdir and registry
    entry both still present, exit code 1.
  - `--yes` → no prompt, workdir and registry entry both gone, exit code 0.
  - ticket ID not in registry → exit code 1, error message, nothing on
    disk touched.
  - workdir already missing from disk (delete it in the test before
    invoking) but registry entry present → command still succeeds,
    registry entry removed, no traceback.
  - path guard: patch the entry's `workdir` to `str(Path.home())` before
    invoking → exit code 1, registry entry untouched, nothing deleted.

### Task 3 — verify and commit

- Run `ruff check . && ruff format .`
- Run `pytest tests/ -v` — full suite, not just the new files, to catch any
  regression (e.g. in `test_smoke.py`, which parametrizes over all
  registered commands' `--help`).
- One commit covering this spec file plus both code changes and both test
  files — do not commit the spec separately.
