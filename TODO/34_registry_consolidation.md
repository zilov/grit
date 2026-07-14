# TODO 34: Consolidate runs.jsonl into registry.json

## Motivation

Currently state is split across two places:
- `~/.grit/registry.json` — ticket index (ticket_id, tol_id, workdir, status)
- `{workdir}/.grit/runs.jsonl` — per-ticket step history (append-only JSONL)

Goal: merge everything into `~/.grit/registry.json`. Single source of truth,
outputs tracked per step, cleaner `grit status`, easy path to SQLite later.

---

## Registry schema (proposed)

```json
[
  {
    "ticket_id": "RC-4414",
    "tol_id": "icCocUnde3",
    "species": "Coccinella undecimpunctata",
    "workdir": "/lustre/.../working/dz11_curation/icCocUnde3/",
    "status": "in_curation",
    "steps": [
      {
        "step": "hic_remapping",
        "timestamp": "2026-06-25T11_00_10",
        "status": "success",
        "run_dir": "/lustre/.../hic_remapping/2026-06-25T11_00_10",
        "job_id": null,
        "outputs": {
          "hap1_pretext": "/lustre/.../pretext_maps_processed/icCocUnde3_hr.pretext"
        }
      }
    ]
  }
]
```

### Allowed output keys per step (to document + enforce)

| step | outputs keys |
|------|-------------|
| pretext_to_asm | hap1_fa, hap2_fa |
| rename_and_orient | hap1_fa, hap1_mapping_tsv |
| rename_and_orient_hap2 | hap2_fa, hap2_mapping_tsv |
| hic_remapping | hap1_pretext |
| hic_remapping_hap2 | hap2_pretext |
| finalize_qc | curated_dir |

Add to `grit/core/manifests.py` alongside STEP_MANIFESTS.

---

## Safe read-modify-write (replaces append-only)

Problem with append-only JSONL: entries accumulate, hard to query, gets messy.
Problem with naive read-modify-write: crash mid-write corrupts the file.

Solution: **atomic write via temp file + rename**
```python
import os, tempfile, json
def _save(data, path):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)  # atomic on POSIX
```
`os.replace` is atomic on POSIX — either the old file or the new file exists,
never a partial write. No file locking needed for single-user sequential use.

---

## Step functions return outputs

Change signature from `-> None` to `-> dict[str, Path] | None`:
- Returns `dict` with output paths on success
- Returns `None` if step was skipped (already done)
- Raises on failure (existing behaviour)

Registry.finish() accepts the dict and stores it under `outputs`.

`find_canonical_fa` queries registry first:
```python
# priority: rename_and_orient outputs → pretext_to_asm outputs → filesystem glob
```
Filesystem glob stays as fallback for tickets migrated from old format.

---

## RunTracker

Keep as thin wrapper over Registry for the transition period. Delegates all
reads/writes to Registry. Once all call sites are updated, remove it.

---

## Implementation order

1. Extend Registry with `steps` array + `start/finish/history/pending_jobs` methods
2. Add atomic `_save` (temp + rename)
3. Make RunTracker delegate to Registry (no behaviour change, all tests pass)
4. Update step functions to return `dict[str, Path] | None`
5. Update `find_canonical_fa` to query registry outputs first
6. Update `grit status` to read outputs from registry (show canonical FA)
7. Write migration script: reads each ticket's runs.jsonl → appends to registry steps
8. Delete RunTracker, delete .grit/runs.jsonl creation code

---

## Migration script

One-off: `grit migrate-registry` command (or standalone script).
For each active ticket in registry:
  - Read `{workdir}/.grit/runs.jsonl` if exists
  - Append entries to `ticket["steps"]` in registry
  - Outputs will be empty for migrated entries (no backfill needed)
