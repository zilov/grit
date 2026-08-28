# Tiny TODOs

Small fixes and improvements — close in one batch when still relevant.

---

- [x] **`grit reopen -t RC-XXXX`** — set ticket status back to active after it's been
  marked done (currently requires manual JSON edit in `~/.grit/registry.json`).
  One-liner: `registry.find_ticket(ticket_id)["status"] = "in_curation"` + save.

- [x] **`grit summary`** — show ticket counts from registry.json grouped by status
  and time period (done this week / month / quarter). Read-only, no new data needed.

- [x] **Sex chromsome count off when some sex-chromsome unlocs are in genome ** — genome with 30 autosomes + ZZ and 10 Z unlocks `Sex chromsomes: ZZZZZZZZZZZZ`.

- [x] **Status: runs count inflated 2x** — runs.jsonl writes one entry on
  `start` (status=started) and one on `finish` (status=success/failed).
  `step_counts` in `status.py` counts both, so a single run shows as 2.
  Fix: count only terminal entries (`success` or `failed`) per step,
  or count unique `run_dir` values instead of raw lines.

- [x] **Any step's `--untracked` run becomes canonical once it finishes** —
  root cause: `RunTracker.start(untracked=True)` wrote `status="untracked"`,
  but `RunTracker.finish()` had no idea the run was untracked and always
  overwrote it with `status="success"/"failed"` — since `_untracked_dirs()`
  keys off the *last* record per `run_dir`, the finish record always won,
  silently promoting the untracked run to canonical (this is what corrupted
  `pretext-to-asm`'s canonical resolution after a `post-curation --untracked`
  run, and what made `blast-contaminants -t RC-4896 --untracked` show up as
  `fa(1,2)` canonical in `grit status`). Fixed by threading `untracked=...`
  into `finish()` (and the bsub `-Ep` epilogue path via `_state-update
  --untracked`) so it keeps writing `status="untracked"` instead of
  clobbering it — `grit untrack --undo` still works (and now also promotes a
  run that was `--untracked` from the start, not just one marked untracked
  after the fact, using the outputs its own finish() call recorded).

- [ ] **Generalize `--untracked` to all steps** — currently only some steps
  wire `ctx.untracked` through to `tracker.start(..., untracked=...)`. Worth
  making this a default option every step gets (via `GritCommand` base class,
  same pattern as `-t`/`--print-only`) rather than something each step opts
  into individually. Came up while designing TODO 38 (shared `busco` step)
  as the mechanism for running a step without it counting as canonical
  registry state.
