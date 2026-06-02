# Task 24: Fix help messages in subcommands ✅ DONE

## Problem

`curate pretext-to-asm --help` fails with "Missing option '--ticket'" instead of showing help.
Root cause: `--ticket` is `required=True` on the `cli` group, so Click validates it before processing `--help` on subcommands.

## Solution

Created `curation_pipeline/core/base_command.py` with `GritCommand(click.RichCommand)`:
- In `__init__`: auto-inserts `--ticket/-t` as the first required param on every subcommand
- In `invoke`: extracts `ticket` from `ctx.params` before callback, writes it to `ctx.obj.ticket`

All 17 step files updated with `cls=GritCommand`. Removed `--ticket` from the `cli` group entirely.

## Results

- `curate pretext-to-asm --help` → rich help with `--ticket -t TEXT  Jira ticket ID. [required]` ✓
- `curate pretext-to-asm` (no ticket) → `Missing option '--ticket' / '-t'.` ✓
- `curate pretext-to-asm -t TICKET` → runs normally ✓
- All subcommands have meaningful docstrings ✓
