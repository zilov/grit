# Tiny TODOs

Small fixes and improvements — close in one batch when still relevant.

---

- [ ] **`grit reopen -t RC-XXXX`** — set ticket status back to active after it's been
  marked done (currently requires manual JSON edit in `~/.grit/registry.json`).
  One-liner: `registry.find_ticket(ticket_id)["status"] = "in_curation"` + save.

- [ ] **`grit summary`** — show ticket counts from registry.json grouped by status
  and time period (done this week / month / quarter). Read-only, no new data needed.

- [ ] **Pre-existing test failures** — `test_pre_curation.py::test_setup_curation_initial_single_hap`
  fails with `RuntimeError: generator raised StopIteration`, unrelated to recent work.
  Investigate and fix.

- [ ] **Autosome count off by one** — genome with 30 autosomes + ZZ sex chromosomes
  shows `Autosomes: 31`. Sex chromosomes are being counted as autosomes.
  Fix: exclude sex chromosome scaffolds from the autosome count in `result_parsers.py`.

- [ ] **Status: runs count inflated 2x** — runs.jsonl writes one entry on
  `start` (status=started) and one on `finish` (status=success/failed).
  `step_counts` in `status.py` counts both, so a single run shows as 2.
  Fix: count only terminal entries (`success` or `failed`) per step,
  or count unique `run_dir` values instead of raw lines.
