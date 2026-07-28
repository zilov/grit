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
