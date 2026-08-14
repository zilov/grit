# 27 Logging
---

## 27. Logging Design

### Decision: Python `logging` + Rich handler

- Use the standard `logging` module everywhere in the library (no `print` for diagnostics).
- Keep `print_*` helpers in `output.py` only for **user-facing progress messages** (step headers, "done", next-step hints). These are intentional UI, not logs.
- Add a single **Rich logging handler** (`rich.logging.RichHandler`) configured in the CLI entry point (`grit/core/click_cli.py`).
- Library code never configures handlers — it only `getLogger(__name__)` and emits records. This is the standard library-safe pattern.

### Log levels

| Level | Used for |
|---|---|
| `DEBUG` | LSF command strings, resolved paths, intermediate values |
| `INFO` | Step start/end, files found, parameters chosen |
| `WARNING` | Missing optional files, fallback behaviour |
| `ERROR` | Caught exceptions before re-raise, failed subprocess |
| `CRITICAL` | (not used) |

### CLI activation

```
grit [--logging-level {DEBUG,INFO,WARNING,ERROR}] <command> ...
```

- Default: `INFO` level, Rich handler with `show_path=False`.
- `--logging-level DEBUG`: `DEBUG` level, `show_path=True` (file + line numbers visible).

```python
# grit/core/click_cli.py  (sketch)
import logging
from rich.logging import RichHandler


def configure_logging(logging_level: str) -> None:
    level = getattr(logging, logging_level.upper(), logging.INFO)
    show_path = level == logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(show_path=show_path, rich_tracebacks=True)],
    )
```

### Library usage (no CLI)

When used as a library the caller controls logging. If they configure nothing, records are silently dropped (standard Python behaviour). They can add their own handler:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
import grit
```

### Error handling in steps

Each step function:
1. Logs `INFO` at entry (`log.info("Starting pretext-to-asm for %s", ctx.tol_id)`).
2. Raises built-in exceptions (`FileNotFoundError`, `RuntimeError`, `subprocess.CalledProcessError`) — **no swallowing**.
3. CLI layer catches at the top-level Click command, logs `ERROR` with `rich_tracebacks`, exits non-zero.

```python
# In a step
log = logging.getLogger(__name__)


def run_pretext_to_asm(ctx: CurationContext) -> None:
    log.info("pretext-to-asm | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    ...
    log.debug("AGP pattern: %s", agp_pattern)
    ...
    log.debug("Command: %s", cmd)
```

```python
# In Click command wrapper
@click.command()
@click.pass_obj
def pretext_to_asm(ctx):
    try:
        run_pretext_to_asm(ctx)
    except Exception:
        log.exception("pretext-to-asm failed")
        raise SystemExit(1)
```
