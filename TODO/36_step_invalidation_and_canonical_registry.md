# 36 — Step invalidation and explicit canonical registry

## Problem

`find_canonical_fa` (and siblings) use implicit glob-based discovery with a fixed
priority: `rename_and_orient` output beats `pretext_to_asm` output.  When a step
runs but produces bad output (e.g. `rename_and_orient` with an incomplete reference
→ wrong chromosome names), grit silently picks up the bad files as canonical with
no way to override short of deleting the run dir by hand.

General pattern: **any step can produce plausible-looking but wrong output**, and
there is no lightweight mechanism to say "ignore that run, fall back to the
previous good state".

## Concrete example

`rename_and_orient` ran against a reference that had fewer chromosomes than the
assembly → output files exist but naming is wrong.  `finalize-qc` and
`grit status -t` then show/copy those bad files as canonical.

## Proposed solution

### 1. Register step outputs in tracker

When a step finishes successfully, record canonical output paths in the tracker
entry alongside `run_dir`:

```json
{
  "step": "rename_and_orient",
  "status": "success",
  "run_dir": ".../<ts>/",
  "outputs": {
    "hap1_fa": ".../ilFoo1.hap1.1.curated.fa",
    "hap2_fa": ".../ilFoo1.hap2.1.curated.fa"
  }
}
```

`find_canonical_fa` would then do:
1. `tracker.get_output("rename_and_orient", "hap1_fa")` — fast, no glob
2. fallback: `tracker.get_output("pretext_to_asm", "hap1_fa")`
3. fallback: current glob logic (for untracked / legacy runs)

### 2. `grit invalidate -s <step>` command

Mark the latest run of a step as `invalidated` in the tracker.  Invalidated runs
are skipped by `get_output` / `latest_run_dir`, so grit automatically falls back
to the previous canonical state.

```
grit invalidate -t RC-1234 -s rename_and_orient
# → marks latest rename_and_orient run as invalidated
# → find_canonical_fa now returns pretext_to_asm output instead
```

No files are deleted.  The run dir and its files stay on disk.  Only the tracker
record changes (`status: invalidated`).  Can be undone by `grit invalidate --undo`.

### 3. Show invalidated runs in `grit status -t`

Step history table: show invalidated runs with a strikethrough / dim style so the
curator can see what happened.

---

## Design questions

- Should `grit invalidate` target the **latest** run only, or allow `--run-dir`?
  (latest-only seems sufficient for now)
- Should invalidated runs be excluded from `grit cleanup`'s "keep latest" logic?
  (yes — cleanup should keep the latest **non-invalidated** run as canonical)
- Does registering outputs need to be retroactive (scan existing run dirs on first
  use), or only for new runs going forward?  Retroactive is nicer UX but adds
  complexity; a one-time `grit migrate-tracker` command could handle it.

### 4. `--invalidated` / `-i` flag on step commands

Run a step but record it as `invalidated` from the start — the run executes
normally, files are written to disk, but grit never treats the output as
canonical.  Useful when experimenting with parameters or a bad reference without
polluting the canonical state.

```
grit rename-and-orient -t RC-1234 -i
# → runs the step, creates run dir, writes outputs
# → tracker entry: status: invalidated (not "started" → "success")
# → find_canonical_fa ignores this run entirely
```

`GritCommand` base class should inject the `-i / --invalidated` option
automatically so every step gets it for free.  The flag is passed down to
`tracker.start(..., invalidated=True)` and `tracker.finish(...)` writes
`invalidated` status regardless of job outcome.

## Scope

Medium.  Touches:
- `RunTracker` — add `get_output`, update `latest_run_dir` to skip invalidated
- Each step that writes canonical files — record outputs on finish
- `find_canonical_*` in `helpers.py` — add tracker lookup before glob fallback
- `click_cli.py` — new `invalidate` command
- `cleanup.py` — skip invalidated runs in "keep latest" logic
- `status.py` — show invalidated runs in history table
