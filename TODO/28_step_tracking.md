## 28. Step Run Tracking

### Goal

- Record every step execution with timestamp, inputs, outputs, and exit status.
- Allow a curator to re-run `pretext-to-asm` (or any step) multiple times; old outputs are not overwritten silently.
- Provide a simple way to inspect what has been run (`grit status`).

### Storage: timestamped run directories in workdir

```
{workdir}/
    pretext_to_asm/
        2025-06-02T14:05:22/        # first run — outputs here
            xbLimHian1.fa
            xbLimHian1.agp
        2025-06-02T17:30:11/        # second run
            xbLimHian1.fa
            xbLimHian1.agp
    .grit/
        runs.jsonl                  # append-only execution log
        pretext_to_asm/
            2025-06-02T14:05:22.log # copy of stdout/stderr per run
            2025-06-02T17:30:11.log
```

- `runs.jsonl`: one JSON object per line. Fields: `step`, `timestamp`, `status` (`started` / `success` / `failed`), `ticket_id`, `tol_id`, `run_dir`.
- Output files always live in `workdir/<step>/<timestamp>/` — easy to browse, no hidden directories.
- `.grit/` contains only the execution log and per-run log files — lightweight, nothing critical.
- Downstream steps are responsible for finding the latest run dir via `RunTracker.latest_run_dir(step)`.

### RunTracker — minimal API

```python
# grit/core/run_tracker.py

from __future__ import annotations
import json, logging, subprocess
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

class RunTracker:
    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.grit_dir = workdir / ".grit"
        self.runs_log = self.grit_dir / "runs.jsonl"
        self.grit_dir.mkdir(exist_ok=True)

    def start(self, step: str, ticket_id: str, tol_id: str) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        run_dir = self.workdir / step / ts
        run_dir.mkdir(parents=True, exist_ok=True)
        self._append({"step": step, "timestamp": ts, "status": "started",
                      "ticket_id": ticket_id, "tol_id": tol_id, "run_dir": str(run_dir)})
        log.debug("Run started: step=%s run_dir=%s", step, run_dir)
        return run_dir

    def finish(self, step: str, run_dir: Path, status: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        self._append({"step": step, "timestamp": ts, "status": status,
                      "run_dir": str(run_dir)})

    def history(self, step: str | None = None) -> list[dict]:
        if not self.runs_log.exists():
            return []
        records = [json.loads(l) for l in self.runs_log.read_text().splitlines()]
        return [r for r in records if step is None or r["step"] == step]

    def latest_run_dir(self, step: str) -> Path | None:
        """Return the run_dir of the last successful run for a step, or None."""
        runs = [r for r in self.history(step) if r["status"] == "success"]
        if not runs:
            return None
        return Path(runs[-1]["run_dir"])

    def log_path(self, step: str, run_dir: Path) -> Path:
        """Return path for the per-run log file inside .grit/<step>/<ts>.log."""
        ts = run_dir.name
        log_dir = self.grit_dir / step
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"{ts}.log"

    def _append(self, record: dict) -> None:
        with self.runs_log.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
```

### Integration in step functions

```python
def run_pretext_to_asm(ctx: CurationContext) -> None:
    tracker = RunTracker(ctx.workdir)
    run_dir = tracker.start("pretext_to_asm", ctx.ticket_id, ctx.tol_id)
    # run_dir = workdir/pretext_to_asm/2025-06-02T17:30:11/
    try:
        ...
        _run(cmd_with_output_to(run_dir), log_file=tracker.log_path("pretext_to_asm", run_dir))
        tracker.finish("pretext_to_asm", run_dir, "success")
    except Exception:
        tracker.finish("pretext_to_asm", run_dir, "failed")
        raise
```

- `run_dir` is always `workdir/<step>/<timestamp>/` — outputs go directly there.
- `tracker.log_path(step, run_dir)` returns `.grit/<step>/<timestamp>.log`.
- `tracker.latest_run_dir(step)` lets downstream steps resolve the latest successful output dir.

### Concurrent writes to `runs.jsonl`

For a CLI tool invoked one-at-a-time, appending a single JSON line is atomic enough on most filesystems (lines are short, writes are sequential). If parallel execution becomes a requirement, replace the plain `open("a")` append with `fcntl.flock` or write per-run sidecar files (`.grit/<step>/<ts>.json`) and scan them on read.

### `grit status` command

```
$ grit status -t RC-1234
step                  runs  last run              last status   outputs
--------------------  ----  --------------------  -----------   -------
setup_curation           1  2025-06-02T10:12:01   success       ok
pretext_to_asm           2  2025-06-02T17:30:11   success       MISSING
hic_remapping            1  2025-06-02T10:45:00   failed        —
```

- Filtered by `ticket_id` — with 20+ tickets in flight, an unfiltered view would be noisy.
- `outputs` column checks whether `run_dir` still exists on disk:
  - `ok` — directory present
  - `MISSING` — directory was deleted or moved manually (logged status says success but files are gone)
  - `—` — step failed, no outputs expected
- Reads `runs.jsonl`, groups by step, prints a Rich table.
- `grit status` without a ticket ID is not planned for now; filter by ticket is the primary UX.

---
