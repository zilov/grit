# 32. Control Plane — Global Registry + Per-Ticket State

> **STATUS: ✅ РЕАЛИЗОВАНО** — ветка `claude/hungry-booth-48f1a3`, коммит `625da0e`
>
> Реализовано:
> - `grit/core/run_tracker.py` — RunTracker с timestamped run dirs + runs.jsonl
> - `grit/core/registry.py` — RegistryManager (~/.grit/registry.json + done.json)
> - `grit/core/manifests.py` — STEP_MANIFESTS + STEP_TO_STATUS
> - `grit status` — глобальная таблица + per-ticket история с bjobs-поллингом
> - `grit _state-update` — скрытая команда для bsub -Ep эпилога
> - Все step-функции обновлены (tracker.start/finish + registry lifecycle)
> - 24 теста: tests/test_run_tracker.py + tests/test_registry.py
>
> Отличия от плана:
> - `epilogue_cmd` параметр добавлен в `_submit_bsub()`, но реальный -Ep не подключён
>   к шагам (только инфраструктура готова; доделать при server testing, шаг 31)
> - `grit status` показывает live bjobs статус через поллинг, не через -Ep
> - Статус `post_curation` добавлен в STEP_TO_STATUS (не был в оригинале)

---

## Context

Task 28 (`28_step_tracking.md`) already specifies `RunTracker` with `runs.jsonl`,
timestamped run directories, and per-ticket `grit status -t RC-1234`.

This task extends that foundation with three new pieces:

1. **Global registry** (`~/.grit/registry.json`) — tracks all tickets that have passed through `grit setup`
2. **File manifest per step** — defines what outputs prove a step succeeded; used for status scanning
3. **bsub job tracking** — resolves `started` → `success`/`failed` without requiring the curator to re-run grit
4. **`grit status` (global)** — aggregated view across all tickets in flight

Tasks 29 and 30 are subsumed here.

---

## 1. Global Registry

### File: `~/.grit/registry.json`

Written on every `grit setup` call. Format:

```json
[
  {
    "ticket_id": "RC-1234",
    "tol_id": "xbLimHian1",
    "species": "Limanda limanda",
    "workdir": "/lustre/.../working/dz11_curation/xbLimHian1",
    "added_at": "2025-06-02T10:00:00Z",
    "status": "in_curation"
  }
]
```

**`status` values** (coarse-grained, manually derivable from `runs.jsonl`):

| Value | Meaning |
|---|---|
| `setup` | setup done, no post steps yet |
| `in_curation` | pretext maps copied; waiting for manual curation in PretextView |
| `remapping` | hic-remapping submitted |
| `remapping_done` | hic-remapping succeeded |
| `qc` | finalize-qc done; ticket sent for QC |
| `post_processing_ready` | QC passed; ready for final post-processing |
| `done` | all steps complete |

Status is updated by `RegistryManager` each time a step finishes. It is derived from the
last successful step in `runs.jsonl`, not stored independently — the registry holds a
cached snapshot. On `grit status`, the registry is refreshed by scanning `runs.jsonl`.

**`RegistryManager`** — lives in `grit/core/registry.py`:

```python
class RegistryManager:
    path: Path  # default: ~/.grit/registry.json

    def add_ticket(self, ctx: CurationContext) -> None: ...
    def update_status(self, ticket_id: str, status: str) -> None: ...
    def remove_ticket(self, ticket_id: str) -> None: ...  # move to done list
    def all_tickets(self) -> list[dict]: ...
```

Tickets stay in the registry until `grit finalize-qc` succeeds, after which they are
moved to `~/.grit/done.json` (same format). This mirrors task 29's original intent.

---

## 2. File Manifest Per Step

Each step declares a list of key output patterns. If these files exist in the step's latest
`run_dir`, the step is considered verified on disk — separate from the `runs.jsonl` status.

```python
# grit/core/manifests.py

STEP_MANIFESTS: dict[str, list[str]] = {
    "setup_curation": ["original.fa"],
    "pretext_to_asm": ["{tol_id}*.hap1.curated.fa", "{tol_id}*.agp"],
    "haplotig_files": ["{tol_id}*.all_haplotigs.curated.fa"],
    "hic_remapping": ["{tol_id}*hr.pretext"],
    "qv": ["{tol_id}*.merqury.qv"],
    "validate_files": [],  # no output files; success = exit code 0
    "finalize_qc": ["{tol_id}*.curated.fa"],
}
```

Patterns are resolved with `tol_id` substituted. Missing manifest = step not tracked on disk.

`RunTracker.verify_outputs(step, run_dir, tol_id)` checks all patterns → returns `ok` / `missing` / `partial`.

---

## 3. bsub Job Tracking

### Approach: `-Ep` callback

When submitting a bsub job, attach an end-of-job command via `-Ep`:

```bash
bsub -Ep "grit _state-update --workdir {workdir} --step {step} --run-dir {run_dir} --status {exit_status}"
    ...
```

`grit _state-update` is a hidden CLI command (prefixed `_` to indicate internal use). It calls
`RunTracker.finish(step, run_dir, status)`. Exit status is passed as LSF variable `$LSB_JOBID`
or derived from exit code via `$?` inside the epilogue.

**LSF epilogue semantics**: `-Ep` receives the job's exit code in `$LSB_JOB_EXIT_CODE`.
Example epilogue command:

```bash
grit _state-update --workdir /lustre/.../working/dz11_curation/xbLimHian1 \
    --step pretext_to_asm \
    --run-dir /lustre/.../pretext_to_asm/2025-06-02T14:05:22 \
    --status $([[ $LSB_JOB_EXIT_CODE -eq 0 ]] && echo success || echo failed)
```

`_submit_bsub()` in `helpers.py` gains an optional `callback: bool = False` parameter.
When `True`, it appends `-Ep "..."` to the bsub command.

### Fallback: lazy polling on `grit status`

For jobs submitted before this feature was added, or if `-Ep` is unavailable, `grit status`
polls `bjobs <job_id>` for entries with status `started` in `runs.jsonl` that have a stored
`job_id`. `runs.jsonl` gains a `job_id` field (optional, null for steps that don't use bsub).

```json
{"step": "hic_remapping", "timestamp": "...", "status": "started",
 "job_id": "12345678", "run_dir": "..."}
```

`grit status` resolves pending jobs:
```
bjobs 12345678 → DONE / EXIT → update runs.jsonl entry in memory for display
```
(Does not mutate `runs.jsonl` during polling — only `_state-update` writes.)

---

## 4. `grit status` (Global View)

```
$ grit status

 In progress (3 tickets)
 ─────────────────────────────────────────────────────────────────
 RC-1234  xbLimHian1   Limanda limanda        remapping_done
 RC-1289  ilHelSara1   Heliconius sara        in_curation
 RC-1301  sDipInt39    Dipturus intermedius   remapping      [job 12345 RUNNING]

 Recently done (last 5)
 ─────────────────────────────────────────────────────────────────
 RC-1190  uoEpiScra1   Episyrphus scaber      done           2025-06-01
```

Implementation: reads `~/.grit/registry.json`, for each ticket reads `runs.jsonl` to refresh
status, polls `bjobs` for any `started`+`job_id` entries. Renders with `rich.table`.

---

## 5. Integration with Existing Architecture

| Component | Change |
|---|---|
| `CurationContext` | Add `tracker: RunTracker` field, populated in `build_context()` |
| `_submit_bsub()` | Add `callback: bool` param; attach `-Ep` when True |
| `setup_curation()` | Call `RegistryManager.add_ticket(ctx)` at end |
| `finalize_qc()` | Call `RegistryManager.update_status(..., "done")` and move to `done.json` |
| Each bsub step | `tracker.start()` before submit, `-Ep` callback handles `finish()` |
| Non-bsub steps | Wrap with `tracker.start()` / `tracker.finish()` directly |

`RunTracker` is already in scope (task 28). `RegistryManager` is the new addition.

---

## 6. Open Questions

- **`_state-update` availability on compute nodes**: the `grit` command must be on `$PATH`
  on LSF workers where `-Ep` runs. May require sourcing the conda env in the epilogue.
  Alternative: write a small self-contained Python script instead of calling `grit`.
- **Workdir scanning on startup**: task 30 proposes scanning workdir before each step to
  extend context (e.g., detect a downloaded reference, sex-matcher results). This is
  complementary and can use `STEP_MANIFESTS` as the scan target. Defer to task 30.
- **`grit status` performance**: if `~/.grit/registry.json` grows large, reading all
  `runs.jsonl` files on every invocation may be slow over NFS. Consider caching last-known
  status in the registry and only re-reading on `--refresh` flag.

---

## Implementation Order

1. `STEP_MANIFESTS` + `RunTracker.verify_outputs()` (extend task 28 impl)
2. `RegistryManager` + `~/.grit/registry.json`
3. `grit status` global view (Rich table)
4. `job_id` field in `runs.jsonl` + `bjobs` polling in `grit status`
5. `_state-update` hidden command + `-Ep` bsub integration
6. Hook `setup_curation` and `finalize_qc` into registry lifecycle
