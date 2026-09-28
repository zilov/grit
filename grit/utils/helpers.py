"""Internal helpers shared by all post-curation step modules."""

from __future__ import annotations

import contextlib
import glob
import logging
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from rich.markup import escape

from grit.core.context import CurationContext
from grit.utils.output import console

log = logging.getLogger(__name__)


def is_single_hap(ctx: CurationContext) -> bool:
    """True if this ticket's assembly has no genuine second haplotype (primary/paternal)."""
    return ctx.hap1_prefix in ("primary", "paternal")


def refuse_hap2_on_single_hap(ctx: CurationContext) -> None:
    """Raise UsageError for a ``--hap2`` request on a ticket with no second haplotype."""
    if is_single_hap(ctx):
        import rich_click as click

        raise click.UsageError(
            f"{ctx.tol_id} is a single-haplotype ({ctx.hap1_prefix}) assembly — "
            f"there is no {ctx.hap2_prefix!r} haplotype, so --hap2 does not apply."
        )


def require_workdir(ctx: CurationContext) -> None:
    """
    Abort with a helpful message if ctx.workdir does not exist on disk.

    Skipped in print_only and dry_run mode (workdir may not exist yet).
    """
    if ctx.print_only or ctx.dry_run:
        return
    if not ctx.workdir.exists():
        log.error(
            "Workdir does not exist: %s\nRun 'grit setup -t %s' first.",
            ctx.workdir,
            ctx.ticket_id,
        )
        raise SystemExit(1)


_STDERR_TAIL_LINES = 40


def _stderr_tail(stderr: str | None) -> str:
    """Return the last _STDERR_TAIL_LINES lines of *stderr*, stripped."""
    return "\n".join((stderr or "").strip().splitlines()[-_STDERR_TAIL_LINES:])


class CommandError(subprocess.CalledProcessError):
    """A failed `_run` command whose message ends with the tail of the tool's stderr."""

    def __str__(self) -> str:
        tail = _stderr_tail(self.stderr)
        return f"{super().__str__()}\n{tail}" if tail else super().__str__()


def _run_with_timeout(
    cmd: str, capture: bool, timeout: float
) -> tuple[int, str | None, str | None]:
    """Run *cmd* in its own process group and kill the whole group if *timeout* expires."""
    pipe = subprocess.PIPE if capture else None
    proc = subprocess.Popen(
        cmd, shell=True, stdout=pipe, stderr=pipe, text=True, start_new_session=True
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except BaseException as exc:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        if not isinstance(exc, subprocess.TimeoutExpired):
            raise
        tail = _stderr_tail(stderr)
        log.error("Command timed out after %ss%s", timeout, f", stderr:\n{tail}" if tail else "")
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr) from None
    return proc.returncode, stdout, stderr


def _run(
    cmd: str, print_only: bool = False, *, capture: bool = True, timeout: float | None = None
) -> str:
    """
    Print *cmd*; execute it unless print_only is True.

    When *capture* is ``True`` (default), stdout is captured and returned.
    When *capture* is ``False``, stdout and stderr are passed through to the
    terminal so the caller can see live output; the return value is ``""``.

    Returns stdout (stripped) when captured, otherwise an empty string. A captured
    command that fails raises CommandError carrying its stderr, which is also logged.
    With *timeout* (seconds), the command and its children are killed and
    TimeoutExpired is raised once it expires; the default waits indefinitely.
    """
    console.print(f"\n[yellow]Command:[/yellow] [green]{escape(cmd)}[/green]")
    if print_only:
        return ""
    if timeout is not None:
        returncode, stdout, stderr = _run_with_timeout(cmd, capture, timeout)
    elif capture:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        returncode, stdout, stderr = result.returncode, result.stdout, result.stderr
    else:
        subprocess.run(cmd, shell=True, check=True)
        return ""
    if returncode != 0:
        if not capture:
            raise subprocess.CalledProcessError(returncode, cmd)
        tail = _stderr_tail(stderr)
        if tail:
            log.error("Command failed (exit %d), stderr:\n%s", returncode, tail)
        raise CommandError(returncode, cmd, output=stdout, stderr=stderr)
    if stderr and stderr.strip():
        log.debug("stderr: %s", stderr.strip())
    return stdout.strip() if capture and stdout else ""


_JOB_SUBMITTED_RE = re.compile(r"^Job <(\d+)> is submitted", re.MULTILINE)


class BsubSubmissionError(RuntimeError):
    """bsub returned without a parseable numeric job ID."""


def _submit_bsub(
    inner_cmd: str,
    bsub_opts: str,
    print_only: bool = False,
    *,
    epilogue_cmd: str | None = None,
) -> str:
    """
    Wrap *inner_cmd* in a bsub call, submit it, and return the numeric job ID string.

    Returns ``""`` in print_only mode; raises BsubSubmissionError when bsub prints no job ID.

    *bsub_opts* is inserted between ``bsub`` and the quoted command, e.g.
    ``'-q oversubscribed -M 1200'``.

    *epilogue_cmd*: when provided, appended as ``-Ep '...'`` so LSF runs it
    after the job completes. Typically used to call ``grit _state-update``.
    """
    epilogue_part = f" -Ep {shlex.quote(epilogue_cmd)}" if epilogue_cmd else ""
    bsub_cmd = f'bsub{epilogue_part} {bsub_opts} "{inner_cmd}"'
    output = _run(bsub_cmd, print_only)
    if print_only:
        return ""
    match = _JOB_SUBMITTED_RE.search(output)
    if not match:
        raise BsubSubmissionError(
            "bsub exited 0 but printed no job ID, so grit cannot track this job; "
            f"check bjobs before resubmitting. bsub said: {output!r}"
        )
    job_id = match.group(1)
    log.info("Job ID: %s", job_id)
    return job_id


def _grit_executable() -> str:
    """Return an absolute path to the running grit executable, else `grit` from $PATH."""
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if argv0 and os.path.isfile(argv0) and os.access(argv0, os.X_OK):
        return argv0
    on_path = shutil.which("grit")
    if on_path:
        return os.path.abspath(on_path)
    log.warning("No grit executable found for the bsub epilogue; relying on $PATH on the node")
    return "grit"


def _state_update_epilogue(workdir: Path, step: str, run_dir: Path, untracked: bool = False) -> str:
    """
    Build the bsub -Ep epilogue command that calls `grit _state-update` when a job finishes.

    Reports success/failed from $LSB_JOBEXIT_STAT, and calls nothing when it is unset
    or non-numeric, leaving the run for the bjobs sweep.

    Pass ``untracked=True`` when the job was submitted for a run started with
    ``tracker.start(untracked=True)``, so the epilogue's `finish()` call doesn't
    clobber the untracked marker with 'success'/'failed'.
    """
    call = shlex.join(
        [
            _grit_executable(),
            "_state-update",
            "--workdir",
            str(workdir),
            "--step",
            step,
            "--run-dir",
            str(run_dir),
            "--status",
        ]
    )
    untracked_flag = " --untracked" if untracked else ""
    return (
        'case "${LSB_JOBEXIT_STAT:-}" in 0) s=success ;; ""|*[!0-9]*) s= ;; *) s=failed ;; esac; '
        f'[ -z "$s" ] || {call} "$s"{untracked_flag}'
    )


_JOB_NOT_FOUND_RE = re.compile(r"Job <(\d+)> is not found")


def lsf_cluster() -> str | None:
    """Return the name of the LSF cluster this host queries, or None if not on LSF."""
    envdir = os.environ.get("LSF_ENVDIR")
    if not envdir:
        return None
    match = re.search(r"lsf-([^/]+)", envdir)
    return match.group(1) if match else envdir


def _check_bjobs(job_ids: list[str]) -> dict[str, str]:
    """
    Query LSF for the status of the given job IDs.

    Returns a dict of {job_id: status_string} where status_string is an LSF
    state ('PEND', 'RUN', 'DONE', 'EXIT', 'ZOMBI', 'UNKWN'), 'gone' when LSF
    explicitly answered that it has no record of the job, or 'unknown' when LSF
    could not be asked at all. 'gone' and 'unknown' must stay distinct: only the
    first is evidence about the job.
    """
    if not job_ids:
        return {}
    result: dict[str, str] = dict.fromkeys(job_ids, "unknown")
    try:
        output = subprocess.run(
            ["bjobs", "-noheader", *job_ids],
            capture_output=True,
            text=True,
        )
    except OSError:
        log.debug("bjobs query failed — LSF may not be available")
        return result
    for line in output.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in result:
            result[parts[0]] = parts[2]
    for job_id in _JOB_NOT_FOUND_RE.findall(output.stderr):
        if job_id in result:
            result[job_id] = "gone"
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


def _refuse_missing_hap2(ctx: "CurationContext", hap_prefix: str, what: str) -> None:
    """Raise FileNotFoundError when *hap_prefix* is the absent hap2 of a single-hap ticket."""
    if hap_prefix == ctx.hap2_prefix and is_single_hap(ctx):
        raise FileNotFoundError(
            f"{ctx.tol_id} is a single-haplotype assembly — no {hap_prefix!r} {what}."
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

    _refuse_missing_hap2(ctx, hap_prefix, "curated FASTA")
    pta_dir = find_latest_dir(ctx, "pretext_to_asm", settled_only=True)

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


def _stat(path: Path) -> os.stat_result | None:
    """*path*'s stat, or None when it cannot be stat'ed (missing, stale NFS handle, …)."""
    try:
        return path.stat()
    except OSError:
        return None


def _rename_and_orient_step_name(ctx: "CurationContext", hap_prefix: str) -> str:
    """Tracker step name recording this haplotype's rename-and-orient run."""
    if hap_prefix == ctx.hap2_prefix:
        return "rename_and_orient_hap2"
    return "rename_and_orient"


def _step_output(
    ctx: "CurationContext", step: str, key_variants: list[str], hap_prefix: str
) -> Path | None:
    """
    Path *step* currently offers for any of *key_variants*, or None.

    Falls back to re-globbing the step's latest successful run dir with its
    output specs when the tracked outputs hold no such key, so a run whose
    outputs were recorded incompletely still competes with its real on-disk
    files instead of handing the canonical slot to an older step. A run still
    in flight never competes: its files may be mid-write.
    """
    for k in key_variants:
        val = ctx.tracker.get_output(step, k)
        if val and _stat(Path(val)) is not None:
            return Path(val)

    run_dir = ctx.tracker.latest_run_dir(step, include_started=False)
    if not run_dir or _stat(run_dir) is None:
        return None
    if step.startswith("pretext_to_asm_recurate"):
        from grit.steps.post_curation.pretext_to_asm_recurate import _output_specs_for_hap

        specs = _output_specs_for_hap(ctx, hap_prefix)
    else:
        specs = _get_step_specs(step)
    if not specs:
        return None
    outputs = collect_outputs(
        specs, run_dir, ctx.tol_id, hap1=ctx.hap1_prefix, hap2=ctx.hap2_prefix
    )
    for k in key_variants:
        val = outputs.get(k)
        if val and _stat(Path(val)) is not None:
            return Path(val)
    return None


def _latest_tracked_output(
    ctx: "CurationContext",
    steps: list[str],
    key_variants: list[str],
    hap_prefix: str,
) -> Path | None:
    """
    Among *steps* (tracker step names), return the Path with the newest
    mtime whose output for any of *key_variants* still exists on disk. Steps
    with no matching output are skipped. Ties (equal mtime, or only one
    candidate) resolve to the first-listed step in *steps*.
    """
    if not ctx.tracker:
        return None
    best: tuple[float, int, Path] | None = None  # (mtime, -priority_index, path)
    for idx, step in enumerate(steps):
        p = _step_output(ctx, step, key_variants, hap_prefix)
        st = _stat(p) if p else None
        if st is not None:
            candidate = (st.st_mtime, -idx, p)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    return best[2] if best else None


def find_canonical_fa(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the canonical assembly FASTA for *hap_prefix*.

    Resolution order:
      1. Tracker outputs across a single ordered pool (``pretext_to_asm``,
         ``microchromosome_combine``, ``blast_contaminants``,
         and this haplotype's ``rename_and_orient`` and
         ``pretext_to_asm_recurate`` steps), compared by mtime — the freshest
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

    _refuse_missing_hap2(ctx, hap_prefix, "assembly FASTA")
    if ctx.tracker:
        keys = [f"{hap_prefix}_fa", f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_fa"]
        pool = [
            "pretext_to_asm",
            "microchromosome_combine",
            "blast_contaminants",
            _rename_and_orient_step_name(ctx, hap_prefix),
            _recurate_step_name(ctx, hap_prefix),
        ]
        canonical = _latest_tracked_output(ctx, pool, keys, hap_prefix)
        if canonical:
            return canonical

    def _rao_search(token: str) -> list[str]:
        rao_pattern = ctx.workdir / "rename_and_orient*" / "*" / f"{ctx.tol_id}.{token}.*.fa"
        return [
            f
            for f in _settled_matches(ctx, glob.glob(str(rao_pattern)))
            if not any(kw in f for kw in _HAPLOTIG_KEYWORDS)
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
    An empty hap-specific file (haplotig-files' placeholder) yields to a non-empty
    no-prefix file in the same directory.

    Raises FileNotFoundError if nothing is found.
    """
    _PTA_ALIASES: dict[str, str] = {
        "primary": "hap1",
        "paternal": "hap1",
        "alternate": "hap2",
        "maternal": "hap2",
    }

    _refuse_missing_hap2(ctx, hap_prefix, "haplotig FASTA")

    def _combined(directory: Path, *, non_empty: bool = False) -> Path | None:
        # No-hap-prefix files — assigned to hap1 only, to avoid double-copying
        if hap_prefix != ctx.hap1_prefix:
            return None
        for pattern in (
            f"{ctx.tol_id}*.haplotigs.fa",  # dual hap combined
            f"{ctx.tol_id}*.all_haplotigs.curated.fa",  # merged
            f"{ctx.tol_id}*.additional_haplotigs.curated.fa",  # single hap
        ):
            combined = [
                m
                for m in glob.glob(str(directory / pattern))
                if "hap1" not in Path(m).name
                and "hap2" not in Path(m).name
                and ctx.hap1_prefix not in Path(m).name
                and ctx.hap2_prefix not in Path(m).name
                and (not non_empty or ((st := _stat(Path(m))) and st.st_size))
            ]
            if combined:
                return Path(sorted(combined)[-1])
        return None

    def _real(candidate: Path) -> Path:
        # haplotig-files' empty placeholder never hides the real haplotigs beside it
        st = _stat(candidate)
        if st and st.st_size == 0:
            return _combined(candidate.parent, non_empty=True) or candidate
        return candidate

    if ctx.tracker:
        keys = [
            f"{hap_prefix}_haplotigs",
            f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_haplotigs",
        ]
        pool = ["pretext_to_asm", _recurate_step_name(ctx, hap_prefix)]
        canonical = _latest_tracked_output(ctx, pool, keys, hap_prefix)
        if canonical:
            return _real(canonical)

    pta_dir = find_latest_dir(ctx, "pretext_to_asm", settled_only=True)

    def _hap_specific(token: str) -> Path | None:
        for pattern in (
            str(pta_dir / f"{ctx.tol_id}.{token}.*.all_haplotigs*.curated.fa"),
            str(pta_dir / f"{ctx.tol_id}.{token}.*.haplotigs*.fa"),
        ):
            matches = glob.glob(pattern)
            if matches:
                return Path(sorted(matches)[-1])
        return None

    # 1. Exact token, then 2. alias (primary→hap1, alternate→hap2)
    result = _hap_specific(hap_prefix)
    if not result and hap_prefix in _PTA_ALIASES:
        result = _hap_specific(_PTA_ALIASES[hap_prefix])
    if result:
        return _real(result)

    # 3. No-hap-prefix patterns
    result = _combined(pta_dir)
    if result:
        return result

    raise FileNotFoundError(f"No haplotig FASTA for {hap_prefix!r} found in {pta_dir}.")


def find_canonical_chr_list(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the canonical chromosome list CSV for *hap_prefix*.

    Resolution order:
      1. Tracker outputs across a single ordered pool (``pretext_to_asm``,
         ``microchromosome_combine``, and this haplotype's
         ``rename_and_orient`` and ``pretext_to_asm_recurate`` steps), compared
         by mtime — the freshest existing file wins outright, ties going to the
         first-listed step.
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

    _refuse_missing_hap2(ctx, hap_prefix, "chromosome list")
    if ctx.tracker:
        keys = [f"{hap_prefix}_chr_list", f"{_PTA_ALIASES.get(hap_prefix, hap_prefix)}_chr_list"]
        pool = [
            "pretext_to_asm",
            "microchromosome_combine",
            _rename_and_orient_step_name(ctx, hap_prefix),
            _recurate_step_name(ctx, hap_prefix),
        ]
        canonical = _latest_tracked_output(ctx, pool, keys, hap_prefix)
        if canonical:
            return canonical

    def _search_dir(directory: Path, token: str) -> list[str]:
        return glob.glob(str(directory / f"{ctx.tol_id}.{token}.*.chromosome.list.csv"))

    def _search_rao(token: str) -> list[str]:
        rao_pattern = (
            ctx.workdir / "rename_and_orient*" / "*" / f"{ctx.tol_id}.{token}.*.chromosome.list.csv"
        )
        return _settled_matches(ctx, glob.glob(str(rao_pattern)))

    matches = _search_rao(hap_prefix)
    if not matches and hap_prefix in _PTA_ALIASES:
        matches = _search_rao(_PTA_ALIASES[hap_prefix])
    if matches:
        return Path(sorted(matches)[-1])

    pta_dir = find_latest_dir(ctx, "pretext_to_asm", settled_only=True)
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


def find_canonical_map(ctx: "CurationContext", hap_prefix: str) -> Path:
    """
    Find the canonical remapped Pretext map for *hap_prefix*.

    Resolution order:
      1. This haplotype's hic-remapping tracker output (``hic_remapping`` for
         hap1, ``hic_remapping_hap2`` for hap2), which skips untracked runs and
         re-globs the run dir when the outputs were recorded incompletely.
      2. Filesystem glob across that step's run dirs, newest mtime winning.

    Only ``*normal.pretext`` is considered: the ``hr.pretext`` map is the
    curation input and stays on the farm. A single-hap assembly has no hap2
    map, so asking for one raises rather than handing back hap1's.

    Raises FileNotFoundError if nothing is found.
    """
    _refuse_missing_hap2(ctx, hap_prefix, "Pretext map")
    is_hap2 = hap_prefix == ctx.hap2_prefix
    step = "hic_remapping_hap2" if is_hap2 else "hic_remapping"
    key = "hap2_normal_pretext" if is_hap2 else "hap1_normal_pretext"

    if ctx.tracker:
        canonical = _latest_tracked_output(ctx, [step], [key], hap_prefix)
        if canonical:
            return canonical

    pattern = ctx.workdir / step / "*" / "pretext_maps_processed" / f"{ctx.tol_id}*normal.pretext"
    excluded = _excluded_run_dirs(ctx, step, settled_only=True)
    stats = {
        m: _stat(Path(m))
        for m in glob.glob(str(pattern))
        if Path(m).parent.parent.name not in excluded
    }
    matches = [m for m, st in stats.items() if st is not None]
    if not matches:
        raise FileNotFoundError(
            f"No remapped Pretext map for {hap_prefix!r} found under "
            f"{ctx.workdir / step}. Run hic-remapping first."
        )
    return Path(max(matches, key=lambda f: stats[f].st_mtime))


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


def iter_agp_rows(agp_path: Path) -> list[tuple[str, str, set[str]]]:
    """List (object name, component id, lowercased tags from the 10th+ columns) per AGP row."""
    rows: list[tuple[str, str, set[str]]] = []
    path = Path(agp_path)
    if not path.is_file():
        return rows
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 9:
            continue
        tags = {f.strip().lower() for f in fields[9:] if f.strip()}
        rows.append((fields[0], fields[5], tags))
    return rows


def parse_agp_tags(agp_path: Path) -> dict[str, set[str]]:
    """Map each AGP object name to the lowercased PretextView tags of all its rows."""
    tags: dict[str, set[str]] = {}
    for name, _component, row_tags in iter_agp_rows(agp_path):
        tags.setdefault(name, set()).update(row_tags)
    return tags


def _excluded_run_dirs(ctx: "CurationContext", step: str, *, settled_only: bool) -> set[str]:
    """Names of *step*'s run dirs marked untracked (and, if *settled_only*, in flight)."""
    if not ctx.tracker:
        return set()
    excluded = {"untracked", "started"} if settled_only else {"untracked"}
    return {
        name for name, status in ctx.tracker.run_dir_statuses(step).items() if status in excluded
    }


def _settled_matches(ctx: "CurationContext", matches: list[str]) -> list[str]:
    """Drop globbed ``{workdir}/<step>/<run_dir>/<file>`` paths from untracked or in-flight runs."""
    excluded: dict[str, set[str]] = {}
    kept = []
    for m in matches:
        run_dir = Path(m).parent
        step = run_dir.parent.name
        if step not in excluded:
            excluded[step] = _excluded_run_dirs(ctx, step, settled_only=True)
        if run_dir.name not in excluded[step]:
            kept.append(m)
    return kept


def find_latest_dir(ctx: "CurationContext", step: str, *, settled_only: bool = False) -> Path:
    """
    Return the output directory for *step*, trying locations in priority order:
      1. Alphabetically-last subdir of workdir/step/ that exists on filesystem,
         compared with tracker.latest_run_dir(step) — whichever is newer wins.
         (Nextflow submits bsub internally so the epilogue may not fire; a newer
          run dir on disk may not yet be recorded as 'success' in the tracker.)
      2. tracker.latest_run_dir(step) alone if no filesystem subdirs exist.
      3. workdir / step / "untracked"    — run before tracking was introduced.
      4. workdir                          — last resort.

    Run dirs the tracker marks untracked are never returned; with
    ``settled_only=True`` neither are runs still in flight (latest record
    ``started``), whose files may be mid-write.

    In print-only mode the tracker path is accepted even if it does not exist yet
    (so printed commands show the expected real path rather than a fallback).
    """
    # Filesystem scan: pick the alphabetically-last (newest timestamp) subdir
    step_dir = ctx.workdir / step
    excluded = _excluded_run_dirs(ctx, step, settled_only=settled_only)
    fs_latest: Path | None = None
    if step_dir.is_dir():
        subdirs = sorted(d for d in step_dir.iterdir() if d.is_dir() and d.name not in excluded)
        if subdirs:
            fs_latest = subdirs[-1]

    tracked: Path | None = None
    if ctx.tracker:
        tracked = ctx.tracker.latest_run_dir(step, include_started=not settled_only)
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


# Join separator for a "multi" spec's output value — several matched files
# for one key are stored as a single string so the tracker's outputs dict
# stays dict[str, str] end to end; split on this to recover the file list.
MULTI_OUTPUT_SEP = "\n"


def collect_outputs(
    specs: list[tuple[str, str, list[str]] | tuple[str, str, list[str], bool]],
    run_dir: Path,
    tol_id: str,
    *,
    hap1: str = "hap1",
    hap2: str = "hap2",
) -> dict[str, str]:
    """
    Glob for step outputs once and return {key: path_str} dict.

    A 4-element spec `(key, pattern, excludes, multi=True)` keeps every match
    (not just the last one), joined with MULTI_OUTPUT_SEP — for a glob like
    "*.idx" that legitimately matches more than one meaningful file (e.g.
    fastga's separate ref/query dgenies indexes).
    """
    outputs: dict[str, str] = {}
    for spec in specs:
        key, pattern, excludes = spec[0], spec[1], spec[2]
        multi = spec[3] if len(spec) > 3 else False
        if key in outputs:  # already found via earlier spec (fallback skip)
            continue
        glob_pattern = pattern.format(tol_id=tol_id, hap1=hap1, hap2=hap2)
        matches = [f for f in run_dir.glob(glob_pattern) if not any(e in f.name for e in excludes)]
        if not matches:
            continue
        if multi:
            outputs[key] = MULTI_OUTPUT_SEP.join(str(f) for f in sorted(matches))
        else:
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
    """
    Write one placeholder file per _OUTPUT_SPECS entry for *step*, returning {key: path}.

    Any ``*``/``?`` wildcard in a spec's glob pattern is filled with the fixed
    placeholder token ``"1"`` to produce a concrete filename. A 4-element
    "multi" spec (see collect_outputs) writes two placeholder files instead
    of one, joined with MULTI_OUTPUT_SEP, so dry-run mirrors the real
    multi-file case.
    """
    outputs: dict[str, str] = {}
    for spec in _get_step_specs(step):
        key, pattern, _excludes = spec[0], spec[1], spec[2]
        multi = spec[3] if len(spec) > 3 else False
        if key in outputs:  # already written via earlier spec (fallback skip)
            continue
        data = content.get(key, b">fake\nACGT\n") if content else b">fake\nACGT\n"
        tokens = ["1", "2"] if multi else ["1"]
        file_paths = []
        for token in tokens:
            rel_path = (
                pattern.format(tol_id=tol_id, hap1=hap1, hap2=hap2)
                .replace("*", token)
                .replace("?", token)
            )
            file_path = run_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(data)
            file_paths.append(file_path)
        outputs[key] = MULTI_OUTPUT_SEP.join(str(p) for p in file_paths)
    return outputs


def _get_step_specs(step: str) -> list[tuple[str, str, list[str]]]:
    """Return _OUTPUT_SPECS for a step by lazy import. Returns [] for unknown steps."""
    from importlib import import_module

    _MAP = {
        "pretext_to_asm": ("grit.steps.post_curation.pretext_to_asm", "_OUTPUT_SPECS"),
        "blast_contaminants": ("grit.steps.optional.blast_contaminants", "_OUTPUT_SPECS"),
        "rename_and_orient": ("grit.steps.optional.rename_and_orient", "_OUTPUT_SPECS"),
        "rename_and_orient_hap2": ("grit.steps.optional.rename_and_orient", "_OUTPUT_SPECS_HAP2"),
        "hic_remapping": ("grit.steps.post_curation.hic_remapping", "_OUTPUT_SPECS"),
        "hic_remapping_hap2": ("grit.steps.post_curation.hic_remapping", "_OUTPUT_SPECS_HAP2"),
        "fastga": ("grit.steps.optional.fastga", "_OUTPUT_SPECS"),
        "fastga_stats": ("grit.steps.optional.fastga", "_OUTPUT_SPECS_STATS"),
        "busco_curated": ("grit.steps.optional.busco_curated", "_OUTPUT_SPECS"),
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
        "super_to_scaffold": (
            "grit.steps.optional.super_to_scaffold",
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


def finished_run_outputs(
    tracker, step: str, run_dir: Path, tol_id: str, *, hap1: str = "hap1", hap2: str = "hap2"
) -> tuple[bool, dict[str, str]]:
    """Return (complete, outputs) for a finished run, judged by STEP_MANIFESTS where one exists."""
    specs = _get_step_specs(step)
    outputs = collect_outputs(specs, run_dir, tol_id, hap1=hap1, hap2=hap2) if specs else {}
    if step == "sex_matcher":
        # its manifest names the workdir, but sex-matcher.sh writes into the run dir
        return run_dir.is_dir() and any(run_dir.glob("Best_match*")), outputs
    verdict = tracker.verify_outputs(step, tol_id, run_dir)
    if verdict == "not_tracked":
        return bool(outputs), outputs
    return verdict in ("ok", "no_files"), outputs


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
