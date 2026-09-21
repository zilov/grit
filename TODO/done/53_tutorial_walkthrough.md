# 53 — `grit tutorial`: an interactive dry-run walkthrough

## Problem

New curators have no way to learn the CLI without a real ticket, farm access
and the fear of touching a real assembly. The knowledge exists — the dry-run
sandbox, `tests/local_smoke_test.sh`'s scenarios, the canonical-priority doc —
but it is spread across a test script and prose, and none of it explains *why*
a step exists at the moment you run it.

Everything needed for a guided walkthrough was already in place: `--dry-run`
covers the whole main chain, `write_fake_outputs()` gives each step a plausible
result, and `grit status -t` shows the canonical table that makes each step's
effect visible. Only the narrator was missing.

## Design

`grit/core/tutorial.py` holds a list of `Lesson` records:

```python
Lesson(title=..., why=..., command="pretext-to-asm", args=["--hap2"],
       watch="what to look for in the status table", status_after=True)
```

The loop prints the explanation, prints the command as the curator would type
it (`grit pretext-to-asm -t TUTORIAL-1 --dry-run`), waits for Enter/`s`/`q`,
runs it, optionally runs `status`, then points at what changed.

Key decisions:

- **Run the real CLI, not a copy.** `_run_grit()` calls
  `cli.main(argv, standalone_mode=False)` in-process. A lesson names a command
  and its flags; it never duplicates a command string a step owns. A renamed
  step breaks the tutorial loudly instead of teaching a stale interface.
- **Bundled fictional ticket.** `grit/config/tutorial_demo.yaml` (specimen
  `xxTutDemo1`, hap1/hap2) is passed as the group-level `--yaml` override, so
  `CurationContext.from_ticket` never reaches Jira. The tutorial only needs
  `~/.grit/grit_curation_config.yaml` to exist, and says `grit init` if it
  doesn't.
- **Sandbox reset up front**, per ticket (`dry_run_root()/<ticket>` plus its
  registry entry) rather than `rm -rf ~/.grit/dry_run` — a curator may have
  their own dry runs in there.
- **The lesson plan teaches canonical resolution, not a fixed order.** The
  chain deliberately includes `hic-remapping` (produces a map, must *not* take
  canonical), the hap1/hap2 split (`--hap2` exclusive for hic-remapping and
  recurate, additive for rename-and-orient), and an untrack/retrack round trip
  before `finalize-qc`.
- **`--auto`** runs every lesson unprompted. Scenario 5 of
  `tests/local_smoke_test.sh` uses it and asserts the *final* canonical table,
  so a drifted lesson fails in CI rather than in front of a new curator.

Out of scope for the MVP: branching scenario menus (single-hap,
microchromosomes, recuration-only), and the `add-*-track` steps, which have no
dry-run branch by design.
