# grit

Genome curation pipeline CLI and library for the Tree of Life curation team.

## Overview

`grit` provides a set of command-line tools and Python functions for pre- and post-curation steps in genome assembly curation. It wraps HPC job submission (`bsub`), file operations, and external tools behind a consistent interface.

See [docs/examples.md](docs/examples.md) for a walkthrough of installation, the standard curation workflow, optional steps, and `grit status`.

## Installation

```bash
# With uv (recommended) — installs the `grit` command globally as a uv tool
uv tool install "grit @ git+ssh://git@github.com/zilov/grit.git"

# For local development instead (editable install into a project-local .venv;
# `grit` is only on PATH after `source .venv/bin/activate` or via `uv run grit`)
uv sync

# Or with pip
pip install -e .
```

To pick up a newer version:

```bash
uv tool upgrade grit --reinstall
```

## Configuration

Run `grit init` to create `~/.grit/grit_curation_config.yaml`, pre-filled with your
Sanger username and Sanger-wide defaults (NFS paths, farm host, `GritJiraIssue` path).
Review it and adjust anything that doesn't match your setup — no manual setup needed
otherwise.

## Usage

### CLI

The `grit` command is installed with the package:

```bash
# Pre-curation
grit setup -t RC-1234
grit find-reference -t RC-1234
grit sex-matcher -t RC-1234
grit microchromosome-second-shot -t RC-1234

# Post-curation
grit pretext-to-asm -t RC-1234
grit haplotig-files -t RC-1234
grit hic-remapping -t RC-1234
grit microchromosome-combine -t RC-1234
grit pretext-to-asm-recurate -t RC-1234
grit qv -t RC-1234
grit finalize-qc -t RC-1234

# Composites
grit post-curation -t RC-1234
grit post-curation-recurate -t RC-1234
grit post-processing -t RC-1234      # alias: pp

# Optional
grit fastga -t RC-1234
grit fastga-stats -t RC-1234
grit fastga-synteny -t RC-1234
grit blast-contaminants -t RC-1234
grit busco-curated -t RC-1234
grit busco-synteny -t RC-1234
grit rename-and-orient -t RC-1234
grit super-to-scaffold -t RC-1234

# Tickets and tracking
grit status [-t RC-1234]
grit untrack / retrack -t RC-1234 --step STEP
grit done / reopen / remove / cleanup -t RC-1234

# Use a local YAML instead of fetching from Jira (ticket_id is derived from the filename stem)
grit --yaml ticket.yaml setup
```

Pass a Jira ticket ID (e.g. `RC-1234`, `GRIT-567`) via `-t`/`--ticket` after the subcommand — all metadata is fetched automatically. Use `--yaml` to provide a local YAML file instead (omit `-t` in that case).

Two flags change what a step actually does, and they are not the same thing:

```bash
# Print the commands a step would run, changing nothing
grit setup -t RC-1234 --print-only

# Placeholder outputs in an isolated ~/.grit/dry_run/ sandbox — for developing
# grit itself, not for curation work
grit --dry-run setup -t RC-1234
```

`--print-only` works either globally before the subcommand or as a per-command flag after it, and wins if both are given.

### Python API

```python
from grit.core.context import CurationContext
from grit.steps.pre_curation.setup import setup_curation
from grit.steps.post_curation.pretext_to_asm import run_pretext_to_asm

user_config = {...}
ctx = CurationContext.from_ticket("RC-1234", user_config)

setup_curation(ctx)
run_pretext_to_asm(ctx)
```

## Development

```bash
# Run tests
pytest tests/ -v

# Lint and format
ruff check .
ruff format .
```

## Project structure

```
grit/
├── core/           # Context, CLI entry point, registry and run tracking
├── config/         # `grit init` and the Sanger config template
├── scripts/        # Bundled shell/Python wrappers around external tools
├── steps/
│   ├── pre_curation/   # Steps before manual curation in PretextView
│   ├── post_curation/  # Steps after manual curation
│   └── optional/       # Optional / conditional steps
└── utils/          # Shared helpers
docs/
tests/
```
