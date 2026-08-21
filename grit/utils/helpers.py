"""Internal helpers shared by all post-curation step modules."""

from __future__ import annotations

import glob
import logging
import re
import subprocess
import sys
from pathlib import Path

from rich.markup import escape

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
            "Workdir does not exist: %s\nRun 'grit setup -t %s' first.",
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
    console.print(f"\n[yellow]Command:[/yellow] [green]{escape(cmd)}[/green]")
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

        >>> build_bsub_opts(memory_mb=50000, wait=True, output="out", error="err")
        "-q normal -K -o out -e err -M 50000 -R'select[mem>50000] rusage[mem=50000] span[hosts=1]'"
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


def build_scp_tip(
    farm_host: str,
    tol_id: str,
    files: list[str],
    label: str,
    dest_names: list[str] | None = None,
) -> str | None:
    """
    Build a print_tip string with scp commands to download *files* to the
    curator's local machine, or None if *files* is empty.

    Args:
        farm_host:  Farm host to scp from (e.g. ``ctx.farm_host``).
        tol_id:     ToL ID, used to build the local destination directory
                    (``~/curations/work/{tol_id}``).
        files:      Absolute remote file paths to download.
        label:      Short description of what's being downloaded, e.g.
                    ``"FastGA results"`` or ``"busco-synteny plot"``.
        dest_names: Optional per-file destination filenames (same order as
                    *files*) — copies each file into the destination
                    directory under this name instead of its remote
                    basename. Used to rename remapped pretext maps on
                    download.

    Returns:
        A ``"Download {label}:\\n[bold cyan]scp ...[/bold cyan]"`` string, or
        None if *files* is empty (nothing to print a tip for).
    """
    if not files:
        return None
    local_dir = f"~/curations/work/{tol_id}"
    if dest_names:
        cmds = " && \\\n".join(
            f"scp {farm_host}:{f} {local_dir}/{d}" for f, d in zip(files, dest_names)
        )
    else:
        cmds = " && \\\n".join(f"scp {farm_host}:{f} {local_dir}" for f in files)
    return f"Download {label}:\n[bold cyan]{cmds}[/bold cyan]"


def build_less_tip(file: str | None, label: str) -> str | None:
    """
    Build a print_tip string suggesting the curator read *file* on the farm
    with ``less``, or None if *file* is falsy.

    Args:
        file:  Absolute remote file path to inspect, or None/empty if not
               yet available.
        label: Short description of what's in the file, e.g.
               ``"top alignment targets"``.

    Returns:
        A ``"Check {label}:\\n[bold cyan]less ...[/bold cyan]"`` string, or
        None if *file* is falsy (nothing to print a tip for).
    """
    if not file:
        return None
    return f"Check {label}:\n[bold cyan]less {file}[/bold cyan]"


def inputs_newer_than_curated_fa(
    workdir: Path,
    tol_id: str,
    pta_dir: Path | None,
    extra_inputs: list[Path] = (),
    *,
    agp_glob: str | None = None,
) -> bool:
    """
    Return True if the AGP or any extra_inputs are newer than the curated FASTA in pta_dir.

    *agp_glob* is a filename pattern (not a full path) globbed inside *workdir*;
    pass it to scope the check to one specific AGP (e.g. a single haplotype's
    recuration AGP) so unrelated AGPs in the same directory can't trigger a
    spurious re-run. Defaults to the generic
    ``{tol_id}*.pretext.agp_1`` → ``{tol_id}*.agp*`` fallback chain.
    """
    curated_fas = list(pta_dir.glob(f"{tol_id}*.curated.fa")) if pta_dir else []
    if not curated_fas:
        return False
    if agp_glob:
        agp_files = list(workdir.glob(agp_glob))
    else:
        agp_files = list(workdir.glob(f"{tol_id}*.pretext.agp_1")) or list(
            workdir.glob(f"{tol_id}*.agp*")
        )
    input_files = agp_files + [p for p in extra_inputs if p.exists()]
    if not input_files:
        return False
    return max(f.stat().st_mtime for f in input_files) > min(f.stat().st_mtime for f in curated_fas)


_HAPLOTIG_FILENAME_KEYWORDS = ("all_haplotigs", "additional_haplotigs", "haplotigs")


def pta_curated_fa_exists(pta_dir: Path, tol_id: str, hap_token: str) -> bool:
    """
    True if a non-haplotig curated FASTA named with the literal *hap_token*
    ("hap1" or "hap2") exists in *pta_dir* — i.e. pretext-to-asm actually
    produced dual-hap output, regardless of what the YAML declares.
    """
    return any(
        not any(kw in f for kw in _HAPLOTIG_FILENAME_KEYWORDS)
        for f in glob.glob(str(pta_dir / f"{tol_id}.{hap_token}.*.curated.fa"))
    )


def find_curated_fa(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the primary curated FASTA for *hap_prefix* in the latest pretext_to_asm run dir.

    Excludes haplotig files so only the main assembly is returned.
    Raises FileNotFoundError if nothing matches.

    pretext-to-asm always names dual-hap files with literal "hap1"/"hap2" regardless of
    the YAML key.  When the YAML uses "primary"/"alternate" or "paternal"/"maternal", we
    map those to the expected pretext-to-asm token as a fallback:
        primary / paternal  → hap1
        alternate / maternal → hap2
    The pattern uses a dot-delimited token (``{tol_id}.{token}.``) so "primary" in the
    YAML-prefix cannot accidentally match the ".primary.curated.fa" filename suffix.
    """
    _HAPLOTIG_KEYWORDS = ("all_haplotigs", "additional_haplotigs", "haplotigs")
    _PTA_ALIASES: dict[str, str] = {
        "primary": "hap1",
        "paternal": "hap1",
        "alternate": "hap2",
        "maternal": "hap2",
    }

    pta_dir = find_latest_dir(ctx, "pretext_to_asm")

    def _search(token: str) -> list[str]:
        return [
            f
            for f in glob.glob(str(pta_dir / f"{ctx.tol_id}.{token}.*.curated.fa"))
            if not any(kw in f for kw in _HAPLOTIG_KEYWORDS)
        ]

    # 1. Exact YAML-prefix token
    matches = _search(hap_prefix)
    # 2. pretext-to-asm alias (hap1/hap2 for primary/alternate assemblies)
    if not matches and hap_prefix in _PTA_ALIASES:
        matches = _search(_PTA_ALIASES[hap_prefix])
    # 3. No-hap-prefix format: {tol_id}.{version}.primary.curated.fa (single hap / merged).
    # Only valid for single-hap YAML prefixes — for a dual-hap ("hap1"/"hap2") prefix this
    # fallback would match the same unprefixed file for both haplotypes.
    if not matches and hap_prefix not in ("hap1", "hap2"):
        matches = [
            f
            for f in glob.glob(str(pta_dir / f"{ctx.tol_id}.*.primary.curated.fa"))
            if not any(kw in f for kw in _HAPLOTIG_KEYWORDS)
            and "hap1" not in Path(f).name
            and "hap2" not in Path(f).name
        ]

    if not matches:
        raise FileNotFoundError(
            f"No curated FASTA for {hap_prefix!r} found in {pta_dir}. Run pretext-to-asm first."
        )
    return Path(sorted(matches)[-1])


def _recurate_step_name(ctx: "CurationContext", hap_prefix: str) -> str:
    """Tracker step name recording this haplotype's pretext-to-asm-recurate run."""
    if hap_prefix == ctx.hap2_prefix:
        return "pretext_to_asm_recurate_hap2"
    return "pretext_to_asm_recurate"


def _latest_tracked_output(
    ctx: "CurationContext",
    steps: list[str],
    key_variants: list[str],
) -> Path | None:
    """
    Among *steps* (tracker step names), return the Path with the newest
    mtime whose tracker output for any of *key_variants* still exists on
    disk. Steps with no matching output are skipped. Ties (equal mtime, or
    only one candidate) resolve to the first-listed step in *steps*.
    """
    if not ctx.tracker:
        return None
    best: tuple[float, int, Path] | None = None  # (mtime, -priority_index, path)
    for idx, step in enumerate(steps):
        for k in key_variants:
            val = ctx.tracker.get_output(step, k)
            if val and Path(val).exists():
                p = Path(val)
                mtime = p.stat().st_mtime
                candidate = (mtime, -idx, p)
                if best is None or candidate[:2] > best[:2]:
                    best = candidate
                break
    return best[2] if best else None


def find_canonical_fa(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the canonical assembly FASTA for *hap_prefix*.

    Resolution order:
      1. Tracker outputs across a single ordered pool (``pretext_to_asm``,
         ``microchromosome_combine``, ``blast_contaminants``,
         ``rename_and_orient``, ``rename_and_orient_hap2``, this haplotype's
         ``pretext_to_asm_recurate``), compared by mtime — the freshest
         existing file wins outright, ties going to the first-listed step.
      2. Filesystem glob in {workdir}/rename_and_orient*/*/{tol_id}.{hap_prefix}.*.fa
      3. ``pretext_to_asm`` output via find_curated_fa (excludes haplotig files)

    Dot-delimited token matching avoids "primary" prefix colliding with the
    ".primary.curated.fa" filename suffix shared by all curated FAs.
    """
    _HAPLOTIG_KEYWORDS = ("all_haplotigs", "additional_haplotigs", "haplotigs")
    _PTA_ALIASES: dict[str, str] = {
        "primary": "hap1",
        "paternal": "hap1",
        "alternate": "hap2",
        "maternal": "hap2",
    }

    if ctx.tracker:
        keys = [f"{hap_prefix}_fa", f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_fa"]
        pool = [
            "pretext_to_asm",
            "microchromosome_combine",
            "blast_contaminants",
            "rename_and_orient",
            "rename_and_orient_hap2",
            _recurate_step_name(ctx, hap_prefix),
        ]
        canonical = _latest_tracked_output(ctx, pool, keys)
        if canonical:
            return canonical

    def _rao_search(token: str) -> list[str]:
        rao_pattern = ctx.workdir / "rename_and_orient*" / "*" / f"{ctx.tol_id}.{token}.*.fa"
        return [
            f for f in glob.glob(str(rao_pattern)) if not any(kw in f for kw in _HAPLOTIG_KEYWORDS)
        ]

    matches = _rao_search(hap_prefix)
    if not matches and hap_prefix in _PTA_ALIASES:
        matches = _rao_search(_PTA_ALIASES[hap_prefix])
    if matches:
        return Path(sorted(matches)[-1])
    return find_curated_fa(ctx, hap_prefix)


def find_canonical_haplotigs(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the haplotig FASTA for *hap_prefix*.

    Resolution order:
      1. Tracker outputs across a small ordered pool (``pretext_to_asm``,
         this haplotype's ``pretext_to_asm_recurate``), compared by mtime —
         the freshest existing file wins outright, ties going to the
         first-listed step.
      2. Filesystem glob in the latest pretext_to_asm run dir.

    pretext-to-asm naming by curation type:
      - dual hap:   ``{tol_id}.1.haplotigs.fa``                      (no hap prefix, combined)
      - single hap: ``{tol_id}.1.additional_haplotigs.curated.fa``
      - merged:     ``{tol_id}.1.all_haplotigs.curated.fa``
      - after haplotig-files step: ``{tol_id}.{hap_prefix}.1.all_haplotigs.curated.fa``
      - after pretext-to-asm-recurate (prior + new merged):
        ``{tol_id}.{hap_prefix}.{release_version}.all_haplotigs.curated.fa``

    Hap-specific patterns are tried first (dot-delimited token + alias); no-prefix
    patterns are only tried for ``hap1_prefix`` to avoid double-copying the same file.

    Raises FileNotFoundError if nothing is found.
    """
    _PTA_ALIASES: dict[str, str] = {
        "primary": "hap1",
        "paternal": "hap1",
        "alternate": "hap2",
        "maternal": "hap2",
    }

    if ctx.tracker:
        keys = [
            f"{hap_prefix}_haplotigs",
            f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_haplotigs",
        ]
        pool = ["pretext_to_asm", _recurate_step_name(ctx, hap_prefix)]
        canonical = _latest_tracked_output(ctx, pool, keys)
        if canonical:
            return canonical

    pta_dir = find_latest_dir(ctx, "pretext_to_asm")

    def _hap_specific(token: str) -> Path | None:
        for pattern in (
            str(pta_dir / f"{ctx.tol_id}.{token}.*.all_haplotigs*.curated.fa"),
            str(pta_dir / f"{ctx.tol_id}.{token}.*.haplotigs*.fa"),
        ):
            matches = glob.glob(pattern)
            if matches:
                return Path(sorted(matches)[-1])
        return None

    # 1. Exact token
    result = _hap_specific(hap_prefix)
    if result:
        return result
    # 2. Alias (primary→hap1, alternate→hap2)
    if hap_prefix in _PTA_ALIASES:
        result = _hap_specific(_PTA_ALIASES[hap_prefix])
        if result:
            return result

    # 3. No-hap-prefix patterns — assign to hap1 only to avoid double-copying
    if hap_prefix == ctx.hap1_prefix:
        for pattern in (
            str(pta_dir / f"{ctx.tol_id}*.haplotigs.fa"),  # dual hap combined
            str(pta_dir / f"{ctx.tol_id}*.all_haplotigs.curated.fa"),  # merged
            str(pta_dir / f"{ctx.tol_id}*.additional_haplotigs.curated.fa"),  # single hap
        ):
            matches = glob.glob(pattern)
            # Exclude any file that is already hap-specific (contains hap1 or hap2 token)
            combined = [
                m
                for m in matches
                if "hap1" not in Path(m).name
                and "hap2" not in Path(m).name
                and ctx.hap1_prefix not in Path(m).name
                and ctx.hap2_prefix not in Path(m).name
            ]
            if combined:
                return Path(sorted(combined)[-1])

    raise FileNotFoundError(f"No haplotig FASTA for {hap_prefix!r} found in {pta_dir}.")


def find_canonical_chr_list(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the canonical chromosome list CSV for *hap_prefix*.

    Resolution order:
      1. Tracker outputs across a single ordered pool (``pretext_to_asm``,
         ``microchromosome_combine``, ``rename_and_orient``,
         ``rename_and_orient_hap2``, this haplotype's
         ``pretext_to_asm_recurate``), compared by mtime — the freshest
         existing file wins outright, ties going to the first-listed step.
      2. ``rename_and_orient`` output —
         {workdir}/rename_and_orient*/*/{tol_id}.{hap_prefix}.*.chromosome.list.csv
      3. ``pretext_to_asm`` output — {tol_id}.{hap_prefix}.*.chromosome.list.csv
      4. ``pretext_to_asm`` no-hap-prefix format (single hap / merged) —
         {tol_id}.{version}.primary.chromosome.list.csv

    Dot-delimited token matching avoids "primary" prefix colliding with the
    ".primary." suffix that appears in all chromosome list filenames.
    Falls back to pretext-to-asm alias (primary→hap1, alternate→hap2) when the
    YAML key differs from the pretext-to-asm naming convention.

    Raises FileNotFoundError if nothing is found in either location.
    """
    _PTA_ALIASES: dict[str, str] = {
        "primary": "hap1",
        "paternal": "hap1",
        "alternate": "hap2",
        "maternal": "hap2",
    }

    if ctx.tracker:
        keys = [f"{hap_prefix}_chr_list", f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_chr_list"]
        pool = [
            "pretext_to_asm",
            "microchromosome_combine",
            "rename_and_orient",
            "rename_and_orient_hap2",
            _recurate_step_name(ctx, hap_prefix),
        ]
        canonical = _latest_tracked_output(ctx, pool, keys)
        if canonical:
            return canonical

    def _search_dir(directory: Path, token: str) -> list[str]:
        return glob.glob(str(directory / f"{ctx.tol_id}.{token}.*.chromosome.list.csv"))

    def _search_rao(token: str) -> list[str]:
        rao_pattern = (
            ctx.workdir / "rename_and_orient*" / "*" / f"{ctx.tol_id}.{token}.*.chromosome.list.csv"
        )
        return glob.glob(str(rao_pattern))

    matches = _search_rao(hap_prefix)
    if not matches and hap_prefix in _PTA_ALIASES:
        matches = _search_rao(_PTA_ALIASES[hap_prefix])
    if matches:
        return Path(sorted(matches)[-1])

    pta_dir = find_latest_dir(ctx, "pretext_to_asm")
    matches = _search_dir(pta_dir, hap_prefix)
    if not matches and hap_prefix in _PTA_ALIASES:
        matches = _search_dir(pta_dir, _PTA_ALIASES[hap_prefix])
    # No-hap-prefix format: {tol_id}.{version}.primary.chromosome.list.csv (single hap / merged)
    if not matches:
        matches = [
            f
            for f in glob.glob(str(pta_dir / f"{ctx.tol_id}.*.primary.chromosome.list.csv"))
            if "hap1" not in Path(f).name and "hap2" not in Path(f).name
        ]
    if not matches:
        raise FileNotFoundError(
            f"No chromosome list for {hap_prefix!r} found in rename_and_orient or {pta_dir}."
        )
    return Path(sorted(matches)[-1])


def find_hap_agp(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the curated AGP for *hap_prefix* in the latest ``pretext_to_asm`` run dir.

    Two pretext-to-asm output layouts exist:
      - dual-window (hap1 and hap2 each curated separately):
        {tol_id}.{hap_prefix}.*.curated.agp, hap_prefix literally "hap1"/"hap2"
        (falls back to the primary→hap1 / alternate→hap2 alias when the YAML
        key differs from the pretext-to-asm naming convention).
      - single/combined window (e.g. ``combine_for_curation``, or a
        primary/alternate assembly with only one curated window): no hap
        token in the filename — {tol_id}.*.primary.curated.agp. Only matched
        for hap1_prefix, since the combined AGP has no per-hap counterpart.

    Raises FileNotFoundError if nothing is found.
    """
    _PTA_ALIASES: dict[str, str] = {"primary": "hap1", "alternate": "hap2"}

    pta_dir = find_latest_dir(ctx, "pretext_to_asm")

    def _search(token: str) -> list[str]:
        return glob.glob(str(pta_dir / f"{ctx.tol_id}.{token}.*.curated.agp"))

    matches = _search(hap_prefix)
    if not matches and hap_prefix in _PTA_ALIASES:
        matches = _search(_PTA_ALIASES[hap_prefix])
    if not matches and hap_prefix == ctx.hap1_prefix:
        matches = [
            f
            for f in glob.glob(str(pta_dir / f"{ctx.tol_id}.*.primary.curated.agp"))
            if "hap1" not in Path(f).name and "hap2" not in Path(f).name
        ]
    if not matches:
        raise FileNotFoundError(
            f"No curated AGP for {hap_prefix!r} found in {pta_dir}. Run pretext-to-asm first."
        )
    return Path(sorted(matches)[-1])


def find_latest_dir(ctx: "CurationContext", step: str) -> Path:
    """
    Return the output directory for *step*, trying locations in priority order:
      1. Alphabetically-last subdir of workdir/step/ that exists on filesystem,
         compared with tracker.latest_run_dir(step) — whichever is newer wins.
         (Nextflow submits bsub internally so the epilogue may not fire; a newer
          run dir on disk may not yet be recorded as 'success' in the tracker.)
      2. tracker.latest_run_dir(step) alone if no filesystem subdirs exist.
      3. workdir / step / "untracked"    — run before tracking was introduced.
      4. workdir                          — last resort.

    In print-only mode the tracker path is accepted even if it does not exist yet
    (so printed commands show the expected real path rather than a fallback).
    """
    # Filesystem scan: pick the alphabetically-last (newest timestamp) subdir
    step_dir = ctx.workdir / step
    fs_latest: Path | None = None
    if step_dir.is_dir():
        subdirs = sorted(d for d in step_dir.iterdir() if d.is_dir())
        if subdirs:
            fs_latest = subdirs[-1]

    tracked: Path | None = None
    if ctx.tracker:
        tracked = ctx.tracker.latest_run_dir(step)
        if tracked and not tracked.exists() and not ctx.print_only:
            tracked = None  # stale tracker entry

    # Return whichever is newer (later alphabetically = later timestamp)
    if fs_latest and tracked and tracked.exists():
        return fs_latest if str(fs_latest.name) >= str(tracked.name) else tracked
    if fs_latest:
        return fs_latest
    if tracked:
        if tracked.exists() or ctx.print_only:
            return tracked

    untracked = ctx.workdir / step / "untracked"
    if untracked.exists():
        return untracked
    return ctx.workdir


def find_reheadered_reference(ctx: "CurationContext") -> Path:
    """
    Locate the reheadered reference FASTA produced by ``grit find-reference``
    (``{prefix}_reheader.fna``). Shared by fastga and busco-synteny, which both
    consume that file directly.

    find_latest_dir() falls back to ctx.workdir itself when find-reference has
    never been run/tracked. Globbing there would pick up unrelated files (e.g.
    original.fa), so that fallback is treated as "no reference dir yet".

    Raises FileNotFoundError with a tip to run find-reference first if nothing
    is found.
    """
    ref_dir = find_latest_dir(ctx, "find_reference")
    ref_reheader = None
    if ref_dir != ctx.workdir:
        ref_matches = glob.glob(str(ref_dir / "*_reheader.fna"))
        if ref_matches:
            ref_reheader = Path(sorted(ref_matches)[-1])

    if ref_reheader is None or (not ctx.print_only and not ref_reheader.exists()):
        raise FileNotFoundError(
            f"No reference found for {ctx.tol_id}.\n"
            f"Run 'grit find-reference -t {ctx.ticket_id}' first."
        )
    return ref_reheader


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


def collect_outputs(
    specs: list[tuple[str, str, list[str]]],
    run_dir: Path,
    tol_id: str,
    *,
    hap1: str = "hap1",
    hap2: str = "hap2",
) -> dict[str, str]:
    """Glob for step outputs once and return {key: path_str} dict."""
    outputs: dict[str, str] = {}
    for key, pattern, excludes in specs:
        if key in outputs:  # already found via earlier spec (fallback skip)
            continue
        glob_pattern = pattern.format(tol_id=tol_id, hap1=hap1, hap2=hap2)
        matches = [f for f in run_dir.glob(glob_pattern) if not any(e in f.name for e in excludes)]
        if matches:
            outputs[key] = str(sorted(matches)[-1])
    return outputs


def write_fake_outputs(
    step: str,
    run_dir: Path,
    tol_id: str,
    *,
    hap1: str = "hap1",
    hap2: str = "hap2",
    content: dict[str, bytes] | None = None,
) -> dict[str, str]:
    """Write one placeholder file per _OUTPUT_SPECS entry for *step*, returning {key: path}."""
    outputs: dict[str, str] = {}
    for key, pattern, _excludes in _get_step_specs(step):
        if key in outputs:  # already written via earlier spec (fallback skip)
            continue
        rel_path = (
            pattern.format(tol_id=tol_id, hap1=hap1, hap2=hap2).replace("*", "1").replace("?", "1")
        )
        file_path = run_dir / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data = content.get(key, b">fake\nACGT\n") if content else b">fake\nACGT\n"
        file_path.write_bytes(data)
        outputs[key] = str(file_path)
    return outputs


def _get_step_specs(step: str) -> list[tuple[str, str, list[str]]]:
    """Return _OUTPUT_SPECS for a step by lazy import. Returns [] for unknown steps."""
    from importlib import import_module

    _MAP = {
        "pretext_to_asm": ("grit.steps.post_curation.pretext_to_asm", "_OUTPUT_SPECS"),
        "rename_and_orient": ("grit.steps.optional.rename_and_orient", "_OUTPUT_SPECS"),
        "rename_and_orient_hap2": ("grit.steps.optional.rename_and_orient", "_OUTPUT_SPECS_HAP2"),
        "hic_remapping": ("grit.steps.post_curation.hic_remapping", "_OUTPUT_SPECS"),
        "hic_remapping_hap2": ("grit.steps.post_curation.hic_remapping", "_OUTPUT_SPECS_HAP2"),
        "fastga": ("grit.steps.optional.fastga", "_OUTPUT_SPECS"),
        "busco_synteny": ("grit.steps.optional.busco_synteny", "_OUTPUT_SPECS"),
        "fastga_synteny": ("grit.steps.optional.fastga_synteny", "_OUTPUT_SPECS"),
        "microchromosome_second_shot": (
            "grit.steps.pre_curation.microchromosome_second_shot",
            "_OUTPUT_SPECS",
        ),
        "pretext_to_asm_micro": (
            "grit.steps.post_curation.microchromosome_combine",
            "_MICRO_PTA_OUTPUT_SPECS",
        ),
        "microchromosome_combine": (
            "grit.steps.post_curation.microchromosome_combine",
            "_OUTPUT_SPECS",
        ),
    }
    if step not in _MAP:
        return []
    mod_path, attr = _MAP[step]
    try:
        return getattr(import_module(mod_path), attr, [])
    except ImportError:
        return []


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
