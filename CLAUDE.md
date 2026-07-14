# grit — CLAUDE.md

Genome curation pipeline CLI for the Sanger Tree of Life curation team. Wraps HPC job submission (`bsub`), file operations, and external tools behind a consistent interface.

## What it does

Automates pre- and post-curation steps around manual genome assembly curation in PretextView. A curator runs `grit RC-1234 setup`, curates manually, then runs a chain of post-curation steps (`pretext-to-asm`, `hic-remapping`, `qv`, `finalize-qc`).

## Architecture

### Core pattern: `CurationContext` passed everywhere

`CurationContext` is a frozen dataclass created once from a Jira ticket ID + user config. It holds all parsed YAML fields, computed file paths, and flags (`print_only`). All step functions accept `ctx: CurationContext` and have no global state.

```python
ctx = CurationContext.from_ticket("RC-1234", user_config)
# or for tests / local YAML:
ctx = CurationContext.from_yaml("RC-1234", yaml_data, user_config)
```

**Workdir derivation:** computed from the draft assembly path by replacing `assembly/draft` → `working`, appending `/<username>_curation/<tol_id>/`. No separate `curations_dir` setting.

### Step structure

```
grit/steps/
├── pre_curation/    # setup, pretext tracks, sex-matcher, microchromosome, find-reference
├── post_curation/   # pretext-to-asm, haplotig-files, hic-remapping, qv, validate, finalize-qc
└── optional/        # blast-contaminants, busco-curated, busco-synteny, fastga, rename-and-orient
```

Each step file exports:
- A plain function (`setup_curation(ctx)`) — usable from Python/notebooks
- A Click command (`setup_cmd`) — registered in `click_cli.py`

### Command execution

All shell commands go through `_run(cmd, print_only)` in `grit/utils/helpers.py`. When `print_only=True`, commands are printed but not executed — enables dry-run mode via `--print-only` flag.

`bsub` jobs are submitted via `_submit_bsub()` → `_run()`. Job IDs are parsed and logged; execution is non-blocking (fire-and-forget).

### HPC module loading

`grit/utils/modules.py` centralises all `module load` version strings in `MODULE_VERSIONS`. Step functions call `module_cmd("TOOL_KEY")` to get the shell fragment `". /etc/profile.d/modules.sh && module purge && module load <module>"`. Updating a tool version = changing one line in `modules.py`.

### CLI

Built with `rich-click`. Entry point: `grit/core/click_cli.py`.

```
grit [--yaml FILE] [--print-only] [--logging-level LEVEL] <COMMAND> -t RC-1234
```

`GlobalState` carries shared flags; `build_context()` constructs `CurationContext` from it. `GritCommand` (in `base_command.py`) is a shared Click base class that auto-injects `--ticket / -t`.

External config: `~/.grit_curation_config.yaml` (not committed). In tests / CI use `--yaml` with a local fixture file.

## Key conventions

- **No global state** — everything flows through `ctx`
- **`print_only` everywhere** — every step respects `ctx.print_only`; `_run()` enforces it
- **`require_workdir(ctx)`** — guards steps that need an existing workdir; skipped in print_only mode
- **`log.*` not `print()`** — use Python `logging`; `RichHandler` formats output
- **`console.print()`** for structured step output (headers, tips, done messages) via `grit/utils/output.py`
- **Assembly type detection** — `_detect_assembly_type(yaml_data)` maps YAML keys to `(assembly_type, hap1_prefix, hap2_prefix)`: `hap1/hap2`, `primary/alternate`
- **`GritJiraIssue`** is a shared server library injected via `sys.path` (path in user config), not a pip dependency

## Dev

```bash
uv sync
pytest tests/ -v
ruff check . && ruff format .
```

Tests use `mock_ctx` fixture (from `tests/conftest.py`) — builds `CurationContext` from fixture YAML files in `tests/fixtures/`, no Jira or filesystem access. Functions calling `subprocess` / `bsub` are mocked; tested via call inspection.
