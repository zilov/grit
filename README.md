# grit

Genome curation pipeline CLI and library for the Tree of Life curation team.

## Overview

`grit` provides a set of command-line tools and Python functions for pre- and post-curation steps in genome assembly curation. It wraps HPC job submission (`bsub`), file operations, and external tools behind a consistent interface.

See [examples.md](examples.md) for a walkthrough of installation, the standard curation workflow, optional steps, and `grit status`.

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
grit sex-matcher -t RC-1234

# Post-curation
grit pretext-to-asm -t RC-1234
grit haplotig-files -t RC-1234
grit hic-remapping -t RC-1234
grit qv -t RC-1234
grit finalize-qc -t RC-1234

# Optional
grit fastga -t RC-1234
grit blast-contaminants -t RC-1234
grit busco-curated -t RC-1234
grit busco-synteny -t RC-1234
grit rename-and-orient -t RC-1234

# Dry run — print commands without executing
grit setup -t RC-1234 --print-only

# Use a local YAML instead of fetching from Jira (ticket_id is derived from the filename stem)
grit --yaml ticket.yaml setup
```

Pass a Jira ticket ID (e.g. `RC-1234`, `GRIT-567`) via `-t`/`--ticket` after the subcommand — all metadata is fetched automatically. Use `--yaml` to provide a local YAML file instead (omit `-t` in that case). Use `--print-only` to preview commands before running — either globally before the subcommand or as a per-command flag after it.

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
├── core/           # Context, CLI entry point
├── steps/
│   ├── pre_curation/   # Steps before manual curation in PretextView
│   ├── post_curation/  # Steps after manual curation
│   └── optional/       # Optional / conditional steps
└── utils/          # Shared helpers
tests/
```
