"""Internal helpers shared by all post-curation step modules."""

from __future__ import annotations

import glob
import logging
import re
import subprocess
from pathlib import Path

from grit.core.context import CurationContext
from grit.utils.output import console

log = logging.getLogger(__name__)


def require_workdir(ctx: CurationContext) -> None:
    """
    Abort with a helpful message if ctx.workdir does not exist on disk.

    Skipped in print_only mode (workdir may not exist yet during dry-runs).
    """
    if ctx.print_only:
        return
    if not ctx.workdir.exists():
        log.error(
            "Workdir does not exist: %s\n"
            "Run 'grit setup -t %s' first.",
            ctx.workdir,
            ctx.ticket_id,
        )
        raise SystemExit(1)


def _run(cmd: str, print_only: bool = False, *, capture: bool = True) -> str:
    """
    Print *cmd*; execute it unless print_only is True.

    When *capture* is ``True`` (default), stdout is captured and returned.
    When *capture* is ``False``, stdout and stderr are passed through to the
    terminal so the caller can see live output; the return value is ``""``.

    Returns stdout (stripped) when captured, otherwise an empty string.
    """
    console.print(f"\n[yellow]Command:[/yellow] [green]{cmd}[/green]")
    if print_only:
        return ""
    if capture:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        return result.stdout.strip()
    subprocess.run(cmd, shell=True, check=True)
    return ""


def _submit_bsub(inner_cmd: str, bsub_opts: str, print_only: bool = False) -> str:
    """
    Wrap *inner_cmd* in a bsub call, submit it, and return the job ID string.

    *bsub_opts* is inserted between ``bsub`` and the quoted command, e.g.
    ``'-q oversubscribed -M 1200'``.
    """
    bsub_cmd = f'bsub {bsub_opts} "{inner_cmd}"'
    output = _run(bsub_cmd, print_only)
    # bsub outputs: Job <12345> is submitted to queue ...
    if output and "Job <" in output:
        job_id = output.split("<")[1].split(">")[0]
        log.info("Job ID: %s", job_id)
        return job_id
    return output


def build_bsub_opts(
    *,
    queue: str = "normal",
    memory_mb: int = 4000,
    cores: int = 1,
    output: str = "lsf.log",
    error: str | None = None,
    group: str | None = None,
    wait: bool = False,
) -> str:
    """
    Build a bsub options string from named parameters.

    Automatically derives ``-R 'select[mem>M] rusage[mem=M] span[hosts=1]'``
    from *memory_mb* so callers do not repeat the boilerplate.

    Args:
        queue:     LSF queue name (default ``"normal"``).
        memory_mb: Memory limit in MB; also used in the ``-R`` resource string.
        cores:     Number of cores (``-n``). Omitted when 1.
        output:    Path/name for job stdout log (``-o``).
        error:     Path/name for job stderr log (``-e``). Omitted when ``None``.
        group:     LSF accounting group (``-G``). Omitted when ``None``.
        wait:      If ``True``, add ``-K`` (block caller until job finishes).

    Returns:
        Space-joined options string ready to pass to :func:`_submit_bsub`.

    Example::

        >>> build_bsub_opts(memory_mb=50000, wait=True,
        ...                 output="sex_matcher.out", error="sex_matcher.err")
        "-q normal -K -o sex_matcher.out -e sex_matcher.err -M 50000 -R'select[mem>50000] rusage[mem=50000] span[hosts=1]'"
    """
    parts = [f"-q {queue}"]
    if cores > 1:
        parts.append(f"-n {cores}")
    if group:
        parts.append(f"-G {group}")
    if wait:
        parts.append("-K")
    parts.append(f"-o {output}")
    if error:
        parts.append(f"-e {error}")
    parts.append(f"-M {memory_mb}")
    parts.append(f"-R'select[mem>{memory_mb}] rusage[mem={memory_mb}] span[hosts=1]'")
    return " ".join(parts)


def _find_pretext_map_in_workdir(ctx: CurationContext) -> Path:
    """
    Returns the HR pretext map that was copied to workdir.

    Raises FileNotFoundError if not found (unless print_only).
    """
    pattern = str(ctx.workdir / f"{ctx.tol_id}*hr.pretext")
    if ctx.print_only:
        return ctx.workdir / f"{ctx.tol_id}_hr.pretext"
    matches = glob.glob(pattern)
    if not matches:
        raise FileNotFoundError(
            f"No HR pretext map found in workdir: {pattern}\nRun copy_pretext_maps first."
        )
    return Path(sorted(matches)[-1])


def _clean_species_name(species: str) -> str:
    """
    Normalise a species name for use with get_nearest_comparator.rb.

    Rules:
        - Strip anything in parentheses (alternative names).
        - Take the first two words.
        - If the second word is "sp." or contains any digit, use only the first word.

    Examples:
        "Anopheles rufipes"                       -> "Anopheles rufipes"
        "Anopheles sp. 123"                        -> "Anopheles"
        "Heliconius melpomene (postman butterfly)" -> "Heliconius melpomene"
        "Genus sp. (some form)"                    -> "Genus"
    """
    # Remove parenthetical remarks
    cleaned = re.sub(r"\(.*?\)", "", species).strip()
    words = cleaned.split()
    if len(words) == 0:
        return species.strip()
    if len(words) == 1:
        return words[0]
    second = words[1]
    if second == "sp." or any(ch.isdigit() for ch in second):
        return words[0]
    return f"{words[0]} {second}"


def _sort_by_mtime(files: list[str]) -> list[str]:
    """Return files sorted by modification time, newest first."""
    return sorted(files, key=lambda x: Path(x).stat().st_mtime, reverse=True)


def _pick_highest_version(files: list[str]) -> str:
    """
    From a list of matching pretext map paths, return the most relevant one.

    Priority:
        1. File whose name contains "RC" (ticket marker).
        2. Otherwise the file with the highest numeric version index
           (the second-to-last ``_``-separated token).
    """
    if len(files) == 1:
        return files[0]

    for f in files:
        if "RC" in Path(f).name:
            return f

    try:
        return sorted(files, key=lambda x: int(Path(x).stem.split("_")[-2]), reverse=True)[0]
    except (ValueError, IndexError):
        return files[-1]
