# 20. Reorganization Plan for Curation Pipeline Library

## Current Organization Analysis

The current structure of the `curation_pipeline` package is as follows:

```
curation_pipeline/
├── __init__.py
├── cli.py              # Main CLI entry point
├── context.py          # CurationContext dataclass and build_context()
├── modules.py          # Likely imports/utilities
├── output.py           # Output formatting functions
└── steps/
    ├── __init__.py
    ├── _helpers.py     # Common utility functions
    ├── bedgraph_track.py
    ├── blast_contaminants.py
    ├── busco_curated.py
    ├── busco_synteny.py
    ├── deprecated_optional.py
    ├── fastga.py
    ├── finalize_qc.py
    ├── find_reference.py
    ├── gap_track.py
    ├── haplotig_files.py
    ├── hic_remapping.py
    ├── microchromosome.py
    ├── optional.py
    ├── post_curation.py
    ├── pre_curation.py
    ├── pretext_to_asm.py
    ├── qv.py
    ├── rename_and_orient.py
    ├── sex_matcher.py
    ├── telo_track.py
    └── validate_files.py
```

### Issues with Current Structure:
1. **Flat steps directory**: All curation steps are in one flat `steps/` directory, making it hard to categorize pre-curation vs post-curation vs optional steps.
2. **Mixed responsibilities**: `cli.py` handles all commands, `modules.py` is unclear, utilities scattered.
3. **No clear separation**: Core logic, configuration, utilities, and steps are not well-separated.
4. **Scalability**: As more features are added (steps 21-25), the flat structure will become unwieldy.
5. **Testing and maintenance**: Hard to isolate and test individual components.

## Proposed New Organization

Reorganize into a more modular, maintainable structure:

```
curation_pipeline/
├── __init__.py
├── core/
│   ├── __init__.py
│   ├── context.py          # CurationContext, build_context(), context persistence
│   └── cli.py              # Main CLI with subcommands (step 21)
├── steps/
│   ├── __init__.py
│   ├── pre_curation/
│   │   ├── __init__.py
│   │   ├── setup.py        # setup_curation, copy_pretext_maps, etc.
│   │   ├── optional_tracks.py  # gap_track, telo_track, bedgraph_track
│   │   ├── sex_matcher.py
│   │   ├── microchromosome.py
│   │   └── find_reference.py
│   ├── post_curation/
│   │   ├── __init__.py
│   │   ├── pretext_to_asm.py
│   │   ├── hic_remapping.py
│   │   ├── qv.py
│   │   ├── validate_files.py
│   │   ├── finalize_qc.py
│   │   └── haplotig_files.py
│   └── optional/
│       ├── __init__.py
│       ├── blast_contaminants.py
│       ├── busco_synteny.py
│       ├── busco_curated.py
│       ├── fastga.py
│       └── rename_and_orient.py
├── utils/
│   ├── __init__.py
│   ├── helpers.py          # Renamed from _helpers.py
│   └── output.py           # Moved from root
├── config/
│   ├── __init__.py
│   ├── settings.py         # Environment-specific configs (Sanger, local, slurm)
│   └── environments.py     # Environment detection and setup
└── __init__.py
```

### Benefits of New Structure:
1. **Logical grouping**: Pre-curation, post-curation, and optional steps are clearly separated.
2. **Modularity**: Each step can be developed, tested, and maintained independently.
3. **Clear responsibilities**: Core (context/CLI), steps (business logic), utils (shared code), config (environment setup).
4. **Easier CLI organization**: Subcommands can map directly to step modules (step 21).
5. **Better testing**: Isolated modules make unit/integration testing simpler (steps 22-23).
6. **Context persistence**: `core/context.py` can handle saving/loading context from workdir (step 24).
7. **Documentation ready**: Structure supports Sphinx documentation organization (step 25).
8. **External users**: `config/` can handle different environments (Sanger, local, slurm) for outside users (XXX).

## Migration Plan

1. **Create new directory structure** with empty `__init__.py` files.
2. **Move files** to appropriate locations:
   - `context.py` → `core/context.py`
   - `cli.py` → `core/cli.py`
   - `output.py` → `utils/output.py`
   - `_helpers.py` → `utils/helpers.py`
   - Categorize steps into `pre_curation/`, `post_curation/`, `optional/`
3. **Update imports** throughout the codebase.

## Considerations for Future Steps

- **Step 21 (CLI)**: New structure makes subcommand implementation straightforward - each step module can have its own CLI handler.
- **Steps 22-23 (Testing)**: Modular structure enables better testing isolation and CI/CD setup.
- **Step 24 (Workdir parsing)**: Context persistence in `core/context.py` can save/load state from workdir.
- **Step 25 (Documentation)**: Sphinx can mirror the package structure for API docs.
- **XXX (External users)**: `config/` module can provide environment-specific runners (local, slurm, etc.) and minimal YAML configs.

This reorganization will make the codebase more maintainable, scalable, and user-friendly for both internal and external users.