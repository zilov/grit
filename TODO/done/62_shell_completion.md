# 62 — bash completion for commands, tickets and ToL IDs

## Problem

Curators type step names (`pretext-to-asm-recurate`, `microchromosome-second-shot`)
and Jira ticket IDs by hand. A ticket ID is also the thing nobody remembers — a
curator thinks in ToL IDs (`ilTutDemo1`), then has to look the `RC-` number up in
`grit status`.

## Design

### 1. Command names — already free

Click (via rich-click) ships bash completion: `_GRIT_COMPLETE=bash_source grit`
prints the bash script. Verified on farm22: `grit pre<Tab>` →
`pretext-to-asm`, `pretext-to-asm-recurate` in ~0.46 s (the full step-module
import; fine for Tab, no lazy-import work needed). Flags (`--hap2`, …) complete
the same way. No code — only activation (section 4).

Hidden commands (`_state-update`) are already excluded by Click.

### 2. `-t` completion: ticket IDs and ToL IDs

One `shell_complete` callback, `complete_ticket(ctx, param, incomplete)`, next to
`RegistryManager` in `grit/core/registry.py`, attached to:

- `--ticket` in `GritCommand` (`base_command.py`), i.e. every step;
- the plain commands' own `-t`: `status`, `untrack`, `retrack`, `done`,
  `reopen`, `remove` (`click_cli.py`).

It returns, for every matching registry entry, **both** `ticket_id` and
`tol_id` as candidates (prefix match on `incomplete`, case-sensitive like the
IDs). bash shows no per-item help text, so offering both strings is the only
way the ToL ID is visible at Tab time.

Which entries:
- active tickets (`all_tickets()`) by default;
- `reopen` completes done tickets instead (`done_tickets(limit=None)`) — it's the
  only command whose valid inputs are the done ones.

Registry choice: honour the group-level `--dry-run` already parsed by the time
completion runs (`ctx.find_root().params.get("dry_run")`) → `dry_run_root()`
registry, so the tutorial sandbox tickets complete under `grit --dry-run`.

Rules for the callback (completion runs on every Tab, must never hurt):
- read only — never `refresh_statuses()`, never `_save()`;
- wrap everything in `try/except Exception: return []` — a corrupt registry
  raises `RegistryError` by design (fail closed), and that must not print a
  traceback into the curator's prompt;
- no Jira, no bjobs.

### 3. `-t <tol_id>` accepted as input

Completing a ToL ID is pointless unless `-t ilTutDemo1` then works. One resolver,
`RegistryManager.resolve_ticket(value) -> str`:

1. `value` is a registry `ticket_id` → return it unchanged;
2. else entries whose `tol_id == value`:
   - exactly one active → its `ticket_id`;
   - none active, exactly one overall → its `ticket_id` (so `reopen -t <tol_id>` works);
   - more than one candidate → `click.UsageError` listing them
     (`RC-1234 (v1, done)`, `RC-5678 (v2, active)`). This is real: the registry
     stores the plain `tol_id`, so a re-release (release_version ≥ 2, see
     `61_release_version.md`) shares it with the v1 ticket.
3. no match → return `value` unchanged, so `grit setup -t RC-9999` on a ticket
   not yet in the registry still goes to Jira as before.

Called once in `GritCommand.invoke()` where `ctx.obj.ticket` is set, and at the
top of each plain command that takes `-t`. Log at info when a ToL ID was
resolved (`ilTutDemo1 → RC-1234`) so the curator sees which ticket was used.

`setup` cannot take a ToL ID for a new ticket (it isn't in the registry yet) —
falls through to step 3 and fails at Jira as any bad ticket does today.

Tutorial: `parse_command()` compares the typed ticket literally, so a learner
typing the ToL ID gets "wrong ticket". Leave as is; the tutorial teaches `-t RC-…`.

### 4. Activation — `grit init` offers it

`init_cmd` asks once (`click.confirm`, default yes) whether to enable Tab
completion; on yes, appends to `~/.bashrc` if not already present (grep for the
marker line first, so re-running `init` never duplicates it):

```bash
# grit tab completion
command -v grit >/dev/null && eval "$(_GRIT_COMPLETE=bash_source grit)"
```

- The `command -v` guard: `grit` exists only after `module load grit`; without
  the guard a fresh shell without the module prints an error.
- `eval` at shell start costs one `grit` import (~0.5 s) per new shell. If that
  bothers people, cache: write the script once to `~/.grit/completion.bash` and
  `source` it. Start with eval; switch only on complaint.
- Must ask on the existing-config path too, since every current curator already
  has a config and `init` currently exits early with "leaving it untouched".
- Bash ≥ 4.4 is required by Click's script; farm bash is newer.

Mention the line in `README`/`grit init` output so a curator who said no can
paste it later.

### Tests

`tests/test_completion.py`:
- `complete_ticket` on a tmp registry: prefix on `RC-` and on a ToL ID returns
  both forms; `reopen` returns done only; corrupt registry → `[]`.
- `resolve_ticket`: ticket passthrough, unique ToL ID, re-release ambiguity →
  `UsageError`, unknown value passthrough.
- one end-to-end via Click's `CliRunner` with
  `env={"_GRIT_COMPLETE": "bash_complete", "COMP_WORDS": "grit qv -t RC", "COMP_CWORD": "3"}`.

### Docs

CLAUDE.md: one line under CLI — `-t` accepts a ToL ID (resolved via the
registry), and completion is Click's built-in, enabled by `grit init`.

## Out of scope

- zsh/fish (bash only on the farm; Click supports them if ever needed —
  `zsh_source` would also show the tol_id as help text).
- `-r` run-ID completion for `untrack`/`retrack`.
