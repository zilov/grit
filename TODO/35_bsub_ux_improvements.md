# TODO 35: bsub UX improvements

## 1. Global `--bsub-memory` flag

Add `--bsub-memory` to the shared `GritCommand` base (same pattern as `--print-only`
and `-t`), so any bsub step can override the memory limit at the command line.

### Behaviour

```
grit fastga -t RC-4414 --bsub-memory 64000
grit hic-remapping -t RC-4414 --bsub-memory 128000
```

- Units: MB (same as LSF `-M` flag)
- Default is per-step and **shown in the help text** so the user knows what
  they're overriding without reading the source:

```
Options:
  --bsub-memory INT  LSF memory limit in MB [default: 24000]
  -t, --ticket TEXT  Jira ticket ID  [required]
```

### Implementation

- Add `bsub_memory: int | None` to `GlobalState` (default `None`)
- Pass through `build_context()` → `CurationContext` as optional field,
  or keep in GlobalState and pass to `build_bsub_opts()` directly
- `build_bsub_opts()` in `helpers.py` already takes `mem_mb` — just wire
  the override in: `mem_mb = ctx.bsub_memory or STEP_DEFAULT_MEM`
- Each step defines its default in a module-level constant:
  ```python
  _DEFAULT_MEM_MB = 24000   # shown in click help as default
  ```

### Steps to update
- fastga.py (current default: 24000)
- hic_remapping.py (check current default in build_bsub_opts call)
- qv.py, finalize_qc.py, any other bsub steps

---

## 2. LSF exit reason in `grit status`

Parse the LSF termination reason from job logs and surface it in the status table
so the user knows *why* a job failed without digging into log files.

### Example LSF output to parse
```
TERM_MEMLIMIT: job killed after reaching LSF memory usage limit.
Exited with exit code 143.
```

Other common LSF TERM_ codes to handle:
| Code | Meaning |
|------|---------|
| TERM_MEMLIMIT | Memory limit exceeded |
| TERM_RUNLIMIT | Runtime limit exceeded |
| TERM_OWNER | Killed by owner |
| TERM_FORCE_OWNER | Force-killed by owner |

### Implementation

- Add `parse_lsf_exit_reason(log_path: Path) -> str | None` to
  `grit/utils/result_parsers.py`
- Scan the last N lines of the bsub stdout/stderr log for `TERM_*:` pattern
- Log files are at `{workdir}/.grit/{step}/{timestamp}.log`
  (written by `RunTracker.log_path()`)
- In `show_ticket_history()` (status.py): for failed steps, call
  `parse_lsf_exit_reason` and append to the status cell:
  ```
  │ fastga  │ 1 │ 2026-06-25 │ failed (TERM_MEMLIMIT) │ 12345 │
  ```

### Hint in status output

When the reason is TERM_MEMLIMIT, add a tip:
```
Tip: fastga hit the memory limit — re-run with a higher limit:
  grit fastga -t RC-4414 --bsub-memory 48000
```
