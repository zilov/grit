"""
HPC module versions used by the curation pipeline.

All ``module load`` commands in the pipeline are assembled here.
To upgrade a tool, change the version string in this file only —
every step that uses the module will pick up the change automatically.

Usage in step functions::

    from grit.modules import module_cmd
    cmd = f"{module_cmd('PRETEXT_TO_ASM')} && pretext-to-asm ..."
"""

# ---------------------------------------------------------------------------
# Module version registry
# ---------------------------------------------------------------------------
# Keys are logical tool names used by step functions.
# Values are the exact module names passed to ``module load``.

MODULE_VERSIONS: dict[str, str] = {
    # generic grit module (used wherever the grit environment is needed)
    "GRIT": "grit",
    # pretext-to-asm (convert AGP + FASTA → curated assembly)
    "PRETEXT_TO_ASM": "grit",
    # HiC remapping pipeline
    "CURATIONPRETEXT": "sanger-tol/curationpretext/1.5.1",
    # PretextGraph (gap / telo / bedgraph tracks)
    "PRETEXTGRAPH": "pretextgraph/0.0.7--h4ac6f70_0",
    # FastGA reference comparison
    "FASTGA": "grit",
}


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def module_cmd(tool_key: str) -> str:
    """
    Return a shell fragment that purges all loaded modules then loads the
    requested tool module.

    ``module purge`` is prepended to avoid conflicts with previously loaded
    modules in the same shell environment.

    Args:
        tool_key: Key from :data:`MODULE_VERSIONS`, e.g. ``"PRETEXT_TO_ASM"``.

    Returns:
        Shell fragment, e.g.::

            "module purge && module load grit"

    Raises:
        KeyError: If *tool_key* is not found in :data:`MODULE_VERSIONS`.

    Example::

        >>> module_cmd("PRETEXT_TO_ASM")
        'module purge && module load grit'
    """
    if tool_key not in MODULE_VERSIONS:
        raise KeyError(
            f"Unknown module key: {tool_key!r}. Available keys: {sorted(MODULE_VERSIONS)}"
        )
    return f"module purge && module load {MODULE_VERSIONS[tool_key]}"
