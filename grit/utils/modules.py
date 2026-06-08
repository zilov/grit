"""
HPC module versions used by the curation pipeline.

All ``module load`` commands in the pipeline are assembled here.
To upgrade a tool, change the version string in this file only —
every step that uses the module will pick up the change automatically.

Usage in step functions::

    from grit.modules import module_cmd
    cmd = f"{module_cmd('PRETEXT_TO_ASM')} && pretext-to-asm ..."
    # expands to:
    # ". /etc/profile.d/modules.sh && module purge && module load grit && pretext-to-asm ..."
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
# Module system initialisation
# ---------------------------------------------------------------------------
# Path to the shell script that defines the ``module`` function.
# bsub jobs run in a non-login, non-interactive shell, so /etc/profile.d/ is
# NOT sourced automatically.  We source this file explicitly at the start of
# every module-related shell fragment so that ``module load`` is available on
# the compute nodes.
_MODULES_INIT = "/etc/profile.d/modules.sh"


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------


def module_cmd(tool_key: str) -> str:
    """
    Return a shell fragment that initialises the module system, purges all
    loaded modules, then loads the requested tool module.

    :data:`_MODULES_INIT` is sourced first so that the ``module`` shell
    function is available even in non-login bsub job environments (where
    ``/etc/profile.d/`` is **not** sourced automatically).

    ``module purge`` is prepended to avoid conflicts with previously loaded
    modules in the same shell environment.

    Args:
        tool_key: Key from :data:`MODULE_VERSIONS`, e.g. ``"PRETEXT_TO_ASM"``.

    Returns:
        Shell fragment, e.g.::

            ". /etc/profile.d/modules.sh && module purge && module load grit"

    Raises:
        KeyError: If *tool_key* is not found in :data:`MODULE_VERSIONS`.

    Example::

        >>> module_cmd("PRETEXT_TO_ASM")
        '. /etc/profile.d/modules.sh && module purge && module load grit'
    """
    if tool_key not in MODULE_VERSIONS:
        raise KeyError(
            f"Unknown module key: {tool_key!r}. Available keys: {sorted(MODULE_VERSIONS)}"
        )
    return f". {_MODULES_INIT} && module purge && module load {MODULE_VERSIONS[tool_key]}"
