# grit

Genome curation pipeline CLI and library for the Tree of Life curation team.

## Overview

`grit` provides a set of command-line tools and Python functions for pre- and post-curation steps in genome assembly curation. It wraps HPC job submission (`bsub`), file operations, and external tools behind a consistent interface.

## Installation

```bash
# With uv (recommended)
uv sync

# Or with pip
pip install -e .
```

## Configuration

Create `~/.grit_curation_config.yaml` with your personal settings:

```yaml
username: <USERNAME>
email: <USERNAME>@sanger.ac.uk
farm_host: <FARM_HOST>
pretext_maps_nfs: /nfs/.../teams/grit/data/pretext_maps
curated_pretext_maps_nfs: /nfs/.../teams/grit/data/curated_pretext_maps
curation_savestates_nfs: /nfs/.../teams/grit/data/curation_savestates
gritjiraissue_path: <GRITJIRAISSUE_PATH>
```

## Usage

### CLI

The `grit` command is installed with the package:

```bash
# Pre-curation
grit RC-1234 setup
grit RC-1234 add-gap-track
grit RC-1234 add-telo-track
grit RC-1234 sex-matcher

# Post-curation
grit RC-1234 pretext-to-asm
grit RC-1234 haplotig-files
grit RC-1234 hic-remapping
grit RC-1234 qv
grit RC-1234 validate-files
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
