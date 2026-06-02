"""Internal helpers shared by all post-curation step modules."""

from __future__ import annotations

import glob
import re
import subprocess
from pathlib import Path

from grit.core.context import CurationContext
from grit.utils.output import console, print_info


def _run(cmd: str, print_only: bool = False) -> str:
    """
    Print *cmd*; execute it unless print_only is True.

    Returns stdout (stripped) when run, otherwise an empty string.
    """
    console.print(f"\n[yellow]Command:[/yellow] [green]{cmd}[/green]")
    if print_only:
        return ""
    result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
    return result.stdout.strip()


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
        print_info("Job ID", job_id)
        return job_id
    return output


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
