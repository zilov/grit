"""Internal helpers shared by all post-curation step modules."""

from __future__ import annotations

import glob
import logging
import re
import subprocess
import sys
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


def _submit_bsub(
    inner_cmd: str,
    bsub_opts: str,
    print_only: bool = False,
    *,
    epilogue_cmd: str | None = None,
) -> str:
    """
    Wrap *inner_cmd* in a bsub call, submit it, and return the job ID string.

    *bsub_opts* is inserted between ``bsub`` and the quoted command, e.g.
    ``'-q oversubscribed -M 1200'``.

    *epilogue_cmd*: when provided, appended as ``-Ep '...'`` so LSF runs it
    after the job completes. Typically used to call ``grit _state-update``.
    """
    epilogue_part = f" -Ep '{epilogue_cmd}'" if epilogue_cmd else ""
    bsub_cmd = f'bsub{epilogue_part} {bsub_opts} "{inner_cmd}"'
    output = _run(bsub_cmd, print_only)
    # bsub outputs: Job <12345> is submitted to queue ...
    if output and "Job <" in output:
        job_id = output.split("<")[1].split(">")[0]
        log.info("Job ID: %s", job_id)
        return job_id
    return output


def _state_update_epilogue(workdir: Path, step: str, run_dir: Path) -> str:
    """
    Build the bsub -Ep epilogue command that calls `grit _state-update` when a job finishes.

    Uses $LSB_JOBEXIT_STAT (set by LSF in epilogue environment) to determine success vs failed.
    The `grit` command must be on $PATH on compute nodes.
    """
    grit_bin = sys.argv[0]  # full path — ensures grit is found in bsub epilogue environment
    return (
        f"{grit_bin} _state-update --workdir {workdir} --step {step} --run-dir {run_dir} "
        f"--status $([ $LSB_JOBEXIT_STAT -eq 0 ] && echo success || echo failed)"
    )


def _check_bjobs(job_ids: list[str]) -> dict[str, str]:
    """
    Query LSF for the status of the given job IDs.

    Returns a dict of {job_id: status_string} where status_string is one of:
    'PEND', 'RUN', 'DONE', 'EXIT', 'ZOMBI', 'UNKWN', or 'gone' (not found).
    """
    if not job_ids:
        return {}
    result: dict[str, str] = {jid: "gone" for jid in job_ids}
    try:
        ids_arg = " ".join(job_ids)
        output = subprocess.run(
            f"bjobs -noheader {ids_arg}",
            shell=True,
            capture_output=True,
            text=True,
        )
        for line in output.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                jid, _user, status = parts[0], parts[1], parts[2]
                if jid in result:
                    result[jid] = status
    except Exception:
        log.debug("bjobs query failed — LSF may not be available")
    return result


def build_bsub_opts(
    *,
    queue: str = "normal",
    memory_mb: int = 4000,
    cores: int = 1,
    output: str = "lsf.log",
    error: str | None = None,
    group: str | None = None,
    wait: bool = False,
    run_dir: Path | None = None,
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
        run_dir:   If provided, relative *output*/*error* names are prefixed with
                   this directory so LSF writes logs into the step's output folder
                   rather than wherever ``grit`` was invoked from.

    Returns:
        Space-joined options string ready to pass to :func:`_submit_bsub`.

    Example::

        >>> build_bsub_opts(memory_mb=50000, wait=True,
        ...                 output="sex_matcher.out", error="sex_matcher.err")
        "-q normal -K -o sex_matcher.out -e sex_matcher.err -M 50000 -R'select[mem>50000] rusage[mem=50000] span[hosts=1]'"
    """
    if run_dir is not None:
        if "/" not in output:
            output = str(run_dir / output)
        if error and "/" not in error:
            error = str(run_dir / error)
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


def agp_newer_than_curated_fa(workdir: Path, tol_id: str, pta_dir: Path | None) -> bool:
    """Return True if the AGP in workdir is newer than the curated FASTA in pta_dir."""
    curated_fas = list(pta_dir.glob(f"{tol_id}*.curated.fa")) if pta_dir else []
    if not curated_fas:
        return False
    agp_files = list(workdir.glob(f"{tol_id}*.pretext.agp_1")) or list(workdir.glob(f"{tol_id}*.agp*"))
    if not agp_files:
        return False
    return max(f.stat().st_mtime for f in agp_files) > min(f.stat().st_mtime for f in curated_fas)


def find_curated_fa(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the primary curated FASTA for *hap_prefix* in the latest pretext_to_asm run dir.

    Excludes ``all_haplotigs`` files so only the main assembly is returned.
    Raises FileNotFoundError if nothing matches.
    """
    pta_dir = find_latest_dir(ctx, "pretext_to_asm")
    matches = [
        f for f in glob.glob(str(pta_dir / f"{ctx.tol_id}*{hap_prefix}*.curated.fa"))
        if "all_haplotigs" not in f
    ]
    if not matches:
        raise FileNotFoundError(
            f"No curated FASTA for {hap_prefix!r} found in {pta_dir}. "
            "Run pretext-to-asm first."
        )
    return Path(sorted(matches)[-1])


def find_canonical_fa(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the canonical assembly FASTA for *hap_prefix*.

    Priority:
      1. ``rename_and_orient`` output — {workdir}/rename_and_orient/{tol_id}*{hap_prefix}*.fa
      2. ``pretext_to_asm`` output   — via find_curated_fa (excludes all_haplotigs)

    Use this in any step that consumes a curated assembly so that renamed
    assemblies are automatically preferred over raw pretext_to_asm output.
    """
    rao_dir = ctx.workdir / "rename_and_orient"
    if rao_dir.exists():
        matches = [
            f for f in glob.glob(str(rao_dir / f"{ctx.tol_id}*{hap_prefix}*.fa"))
            if "all_haplotigs" not in f
        ]
        if matches:
            return Path(sorted(matches)[-1])
    return find_curated_fa(ctx, hap_prefix)


def find_canonical_haplotigs(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the haplotig FASTA for *hap_prefix* in the latest pretext_to_asm run dir.

    pretext-to-asm naming by curation type:
      - dual hap:   ``{tol_id}.1.haplotigs.fa``                      (no hap prefix, combined)
      - single hap: ``{tol_id}.1.additional_haplotigs.curated.fa``
      - merged:     ``{tol_id}.1.all_haplotigs.curated.fa``
      - after haplotig-files step: ``{tol_id}.{hap_prefix}.1.all_haplotigs.curated.fa``

    Hap-specific patterns are tried first; no-prefix patterns are only tried for
    ``hap1_prefix`` to avoid double-copying the same file for both haps.

    Raises FileNotFoundError if nothing is found.
    """
    pta_dir = find_latest_dir(ctx, "pretext_to_asm")

    # Hap-specific patterns (haplotig-files step output or hypothetical per-hap files)
    for pattern in (
        str(pta_dir / f"{ctx.tol_id}*{hap_prefix}*all_haplotigs*.curated.fa"),
        str(pta_dir / f"{ctx.tol_id}*{hap_prefix}*haplotigs*.fa"),
    ):
        matches = glob.glob(pattern)
        if matches:
            return Path(sorted(matches)[-1])

    # No-hap-prefix patterns — assign to hap1 only to avoid double-copying
    if hap_prefix == ctx.hap1_prefix:
        for pattern in (
            str(pta_dir / f"{ctx.tol_id}*.haplotigs.fa"),                     # dual hap combined
            str(pta_dir / f"{ctx.tol_id}*.all_haplotigs.curated.fa"),          # merged
            str(pta_dir / f"{ctx.tol_id}*.additional_haplotigs.curated.fa"),   # single hap
        ):
            matches = glob.glob(pattern)
            # Exclude any file that is already hap-specific
            combined = [
                m for m in matches
                if ctx.hap1_prefix not in Path(m).name
                and ctx.hap2_prefix not in Path(m).name
            ]
            if combined:
                return Path(sorted(combined)[-1])

    raise FileNotFoundError(
        f"No haplotig FASTA for {hap_prefix!r} found in {pta_dir}."
    )


def find_canonical_chr_list(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the canonical chromosome list CSV for *hap_prefix*.

    Priority:
      1. ``rename_and_orient`` output — {workdir}/rename_and_orient/{tol_id}*{hap_prefix}*.chromosome.list.csv
      2. ``pretext_to_asm`` output

    Use this alongside ``find_canonical_fa`` so that both FA and chromosome list
    come from the same processing stage.
    Raises FileNotFoundError if nothing is found in either location.
    """
    rao_dir = ctx.workdir / "rename_and_orient"
    if rao_dir.exists():
        matches = glob.glob(str(rao_dir / f"{ctx.tol_id}*{hap_prefix}*.chromosome.list.csv"))
        if matches:
            return Path(sorted(matches)[-1])
    pta_dir = find_latest_dir(ctx, "pretext_to_asm")
    matches = glob.glob(str(pta_dir / f"{ctx.tol_id}*{hap_prefix}*.chromosome.list.csv"))
    if not matches:
        raise FileNotFoundError(
            f"No chromosome list for {hap_prefix!r} found in rename_and_orient or {pta_dir}. "
            "Run pretext-to-asm first."
        )
    return Path(sorted(matches)[-1])


def find_latest_dir(ctx: "CurationContext", step: str) -> Path:
    """
    Return the output directory for *step*, trying locations in priority order:
      1. tracker.latest_run_dir(step)     — tracked run (success or started)
      2. workdir / step / "untracked"    — run before tracking, convention from tracker.start()
      3. workdir                          — last resort

    All steps follow the convention: if tracker is absent, run_dir falls back to
    ``workdir/<step>/untracked``.  Steps that don't create that dir (bsub-only)
    safely skip to workdir.
    """
    if ctx.tracker:
        tracked = ctx.tracker.latest_run_dir(step)
        if tracked and tracked.exists():
            return tracked
    untracked = ctx.workdir / step / "untracked"
    if untracked.exists():
        return untracked
    return ctx.workdir


def _find_pretext_map_in_workdir(ctx: "CurationContext") -> Path:
    """
    Returns the HR pretext map that was copied to workdir.

    Raises FileNotFoundError if not found.
    """
    pattern = str(ctx.workdir / f"{ctx.tol_id}*hr.pretext")
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
