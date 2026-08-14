# grit

Genome curation pipeline CLI and library for the Tree of Life curation team.

## Overview

`grit` provides a set of command-line tools and Python functions for pre- and post-curation steps in genome assembly curation. It wraps HPC job submission (`bsub`), file operations, and external tools behind a consistent interface.

## Installation

```bash
# With uv (recommended) — installs the `grit` command globally as a uv tool
uv tool install .

# For local development instead (editable install into a project-local .venv;
# `grit` is only on PATH after `source .venv/bin/activate` or via `uv run grit`)
uv sync

# Or with pip
pip install -e .
```

To pick up a newer version, pull the latest changes and reinstall the tool:

```bash
git pull && uv tool upgrade grit --reinstall
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
grit RC-1234 setup
grit RC-1234 sex-matcher

# Post-curation
grit RC-1234 pretext-to-asm
grit RC-1234 haplotig-files
grit RC-1234 hic-remapping
grit RC-1234 qv
grit RC-1234 finalize-qc

# Optional
grit RC-1234 fastga
grit RC-1234 blast-contaminants
grit RC-1234 busco-curated
grit RC-1234 busco-synteny
grit RC-1234 rename-and-orient

# Dry run — print commands without executing
grit RC-1234 --print-only setup

# Use a local YAML instead of fetching from Jira
grit --yaml ticket.yaml setup
```

Pass a Jira ticket ID (e.g. `RC-1234`, `GRIT-567`) as the first argument — all metadata is fetched automatically. Use `--yaml` to provide a local YAML file instead. Use `--print-only` to preview commands before running.

### Python API

```python
from grit.core.context import CurationContext
from grit.steps.pre_curation.setup import setup_curation
from grit.steps.post_curation.pretext_to_asm import run_pretext_to_asm

user_config = { ... }
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
