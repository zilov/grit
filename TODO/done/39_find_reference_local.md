# TODO 39: `--local` option for `find-reference`

## Problem

`find-reference` always shells out to `get_nearest_comparator.rb` to search
NCBI and download a reference genome. When a curator already has the right
reference on disk (e.g. downloaded previously for another ticket, or shared
by a colleague), there's no way to feed it into `find-reference` — they have
to fall back to passing `--reference` directly to `fastga`/`busco-synteny`
individually, which means repeating the same local path on every downstream
command and skipping the tracked `find_reference` run entirely (so `grit
status` won't show a reference as prepared).

## Design

Add a `--local/-l PATH` option to `find-reference` that skips the download
and prepares a user-supplied FASTA the same way a downloaded one is
prepared — via `reheader_reference()` — landing it in the same tracked
`run_dir` that `fastga`/`busco-synteny` already look for via
`find_reheadered_reference()`. No changes needed downstream: once the
reheadered file is in the tracked `find_reference` run_dir, every consumer
picks it up automatically.

### CLI

`grit find-reference -l /path/to/reference.fa[.gz]`

- `-l/--local` and `-n/--number` are mutually exclusive in intent — if both
  are given, log a warning and ignore `-n` (only one local reference is
  supported per run, unlike `-n` which can fetch multiple from NCBI).
- Validate the path exists up front (`FileNotFoundError` if not, skipped
  under `--print-only` like the equivalent check in `fastga.py`).

### `find_closest_reference(ctx, number=1, local_path=None)`

When `local_path` is given:

1. Get the tracked `run_dir` exactly as today: `ctx.tracker.start(
   "find_reference", ...)`.
2. Symlink the local file into `run_dir` instead of copying it — the
   original file must never be moved, modified, or deleted:
   `ln -s {local_path} {run_dir}/{Path(local_path).name}`.
3. Call the existing `reheader_reference(ctx, symlink_path,
   remove_raw=True)` unchanged. This already does the right thing for both
   plain and gzipped input:
   - Plain FASTA: `reheader {symlink} > {run_dir}/{prefix}_reheader.fna`,
     then `rm {symlink}` — removes only the symlink, original untouched.
   - Gzipped FASTA: `gunzip {symlink}` reads through the symlink and writes
     the decompressed file into `run_dir`, consuming (removing) only the
     symlink itself as its "input file" — the real compressed file the
     symlink pointed to is never touched. `reheader` then runs on that
     decompressed copy, and `rm {unzipped}` cleans up the intermediate
     decompressed file, leaving only `run_dir/{prefix}_reheader.fna`.
4. `tracker.finish(..., "success"/"failed")` around the same try/except as
   today.
5. `print_done` message noting a local reference was used, instead of
   "Reference downloaded to ...".

When `local_path` is not given, behavior is unchanged (existing
`get_nearest_comparator.rb` download path).

### Testing

- New test file `tests/test_find_reference.py` (none exists today):
  - `local_path` given → asserts `ln -s` (not `cp`) is used, `_run` is
    called with the symlink command, `reheader_reference` is called with
    `remove_raw=True`, and `get_nearest_comparator.rb` is never invoked.
  - `local_path` + `number > 1` together → asserts a warning is logged and
    only the local path is used.
  - Missing local path (non-print-only) → asserts `FileNotFoundError`.
  - Existing download path (no `local_path`) stays covered/unaffected.

### Net effect

- `grit find-reference -l /path/to/ref.fa` prepares a local reference
  exactly like a downloaded one, tracked the same way, consumable by
  `fastga`/`busco-synteny` with no further flags needed.
- Original local file is never modified — only a symlink (and, for `.gz`
  input, one intermediate decompressed copy inside `run_dir`) is created and
  cleaned up.

### CLAUDE.md

This doesn't add a new architectural pattern (it reuses the existing
`reheader_reference()` / tracked `run_dir` / `find_reheadered_reference()`
flow that `fastga`/`busco-synteny` already established), so no CLAUDE.md
update is expected from this task specifically. As a general rule going
forward (now documented in CLAUDE.md's Planning section): if implementation
does end up introducing a new pattern or shared convention, update
CLAUDE.md in the same task, not later.

---

## Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `grit find-reference` prep a user-supplied local FASTA (symlink + reheader) instead of downloading from NCBI, landing it where `fastga`/`busco-synteny` already look for it.

**Architecture:** One `if local_path:` branch inside the existing `find_closest_reference()`, reusing `reheader_reference()` unchanged. One new CLI option (`-l/--local`) on `find_reference_cmd`. No other files touched — `find_reheadered_reference()`, `fastga.py`, `busco_synteny.py` need zero changes since they already read from the tracked `find_reference` run_dir.

**Tech Stack:** Python, Click (`rich_click`), pytest + `unittest.mock`, existing `_run()`/`reheader_reference()` helpers.

## Global Constraints

- Never modify, move, or delete the user's original local file — only a symlink (and, for `.gz` input, an intermediate decompressed file inside `run_dir`) is created/removed.
- `--local`/`local_path` supports exactly one file; if `number != 1` is also passed, log a warning and ignore `number` — don't error.
- Missing local path raises `FileNotFoundError`, except under `ctx.print_only` (matches the existing check in `fastga.py`'s `reference_path` handling).
- No changes to `reheader_reference()`, `find_reheadered_reference()`, `fastga.py`, or `busco_synteny.py`.

---

### Task 1: `--local` option end-to-end (function + CLI + tests)

**Files:**
- Modify: `grit/steps/pre_curation/find_reference.py:82-144` (`find_closest_reference` + `find_reference_cmd`)
- Test: `tests/test_find_reference.py` (new file)

**Interfaces:**
- Produces: `find_closest_reference(ctx: CurationContext, number: int = 1, local_path: str | None = None) -> None` — same public name, two new optional kwargs. Existing callers (`find_closest_reference(ctx)`) keep working unchanged.
- Consumes: `reheader_reference(ctx, raw: Path, *, remove_raw: bool = False) -> Path` (already defined earlier in the same file, line 33) — call unchanged, just with a symlink `Path` as `raw`.
- Consumes: `ctx.tracker.start(step, ticket_id, tol_id, untracked=...)` / `ctx.tracker.finish(step, run_dir, status)` — same calls already used in the download branch.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_find_reference.py`:

```python
"""Tests for find_reference step."""

from unittest.mock import patch

import pytest

from grit.steps.pre_curation.find_reference import find_closest_reference


@patch("grit.steps.pre_curation.find_reference.reheader_reference")
@patch("grit.steps.pre_curation.find_reference._run")
def test_local_symlinks_and_reheaders(mock_run, mock_reheader, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    local_ref = tmp_path / "my_reference.fa"
    local_ref.write_text(">chr1\nACGT\n")

    find_closest_reference(mock_ctx, local_path=str(local_ref))

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ln -s" in cmd
    assert str(local_ref) in cmd
    assert "cp " not in cmd

    mock_reheader.assert_called_once()
    reheader_args, reheader_kwargs = mock_reheader.call_args
    assert reheader_kwargs.get("remove_raw") is True
    link_path = reheader_args[1]
    assert link_path.name == "my_reference.fa"


@patch("grit.steps.pre_curation.find_reference._run")
def test_local_missing_file_raises(mock_run, mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    with pytest.raises(FileNotFoundError):
        find_closest_reference(mock_ctx, local_path=str(tmp_path / "does_not_exist.fa"))

    mock_run.assert_not_called()


@patch("grit.steps.pre_curation.find_reference.reheader_reference")
@patch("grit.steps.pre_curation.find_reference._run")
def test_local_ignores_number_with_warning(mock_run, mock_reheader, mock_ctx, tmp_path, caplog):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    local_ref = tmp_path / "ref.fa"
    local_ref.write_text(">chr1\nACGT\n")

    with caplog.at_level("WARNING"):
        find_closest_reference(mock_ctx, number=3, local_path=str(local_ref))

    assert "--number" in caplog.text
    mock_run.assert_called_once()  # only the ln -s call, no download loop


@patch("grit.steps.pre_curation.find_reference._reheader_downloaded_references")
@patch("grit.steps.pre_curation.find_reference._run")
def test_download_path_unaffected_when_no_local_path(
    mock_run, mock_reheader_downloaded, mock_ctx, tmp_path
):
    mock_ctx.workdir = tmp_path / "workdir"
    mock_ctx.print_only = False

    find_closest_reference(mock_ctx)

    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "get_nearest_comparator.rb" in cmd
    mock_reheader_downloaded.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_find_reference.py -v`
Expected: all four tests fail — `find_closest_reference()` doesn't accept `local_path` yet (`TypeError: unexpected keyword argument`).

- [ ] **Step 3: Implement `local_path` branch in `find_closest_reference`**

Replace the body of `find_closest_reference` in `grit/steps/pre_curation/find_reference.py` (currently lines 82-123) with:

```python
def find_closest_reference(
    ctx: CurationContext, number: int = 1, local_path: str | None = None
) -> None:
    """
    Finds (and downloads) the closest reference genome from NCBI for the
    species being curated, or preps a user-supplied local reference in its
    place when ``local_path`` is given.

    The reference FASTA lands in the tracked ``find_reference`` run_dir,
    the same as a downloaded one, so ``fastga``/``busco-synteny`` pick it up
    automatically via ``find_reheadered_reference()``.

    Command (download path)::

        mkdir -p {ctx.workdir}/reference && \\
        cd {ctx.workdir}/reference && \\
        /software/grit/projects/vgp_curation_scripts/get_nearest_comparator.rb \\
            -s "{ctx.species}" -d -n {number}

    Local path: symlinks ``local_path`` into the run_dir and reheaders it via
    ``reheader_reference(..., remove_raw=True)`` — the symlink is removed
    afterwards, the original file is never touched.

    Prints:
        Step header, command executed, path to reference directory.
    """
    log.info("find-reference | ticket=%s tol_id=%s", ctx.ticket_id, ctx.tol_id)
    print_step_header(ctx.ticket_id, ctx.tol_id, "Find closest reference")

    run_dir = (
        ctx.tracker.start("find_reference", ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked)
        if ctx.tracker
        else ctx.workdir / "find_reference" / "untracked"
    )
    log.info("Reference dir: %s", run_dir)

    if local_path:
        if number != 1:
            log.warning(
                "--local given together with --number=%s; ignoring --number "
                "(only one local reference is used).",
                number,
            )
        local = Path(local_path).expanduser()
        if not ctx.print_only and not local.exists():
            raise FileNotFoundError(f"Local reference not found: {local}")
        log.info("Using local reference: %s", local)

        try:
            link_path = run_dir / local.name
            _run(f"mkdir -p {run_dir} && ln -s {local.resolve()} {link_path}", ctx.print_only)
            reheader_reference(ctx, link_path, remove_raw=True)
            if ctx.tracker and run_dir:
                ctx.tracker.finish("find_reference", run_dir, "success")
        except Exception:
            if ctx.tracker and run_dir:
                ctx.tracker.finish("find_reference", run_dir, "failed")
            raise
        print_done(f"Local reference prepared in {run_dir}")
        return

    species_query = _clean_species_name(ctx.species)
    log.info("Species (raw): %s", ctx.species)
    log.info("Species (query): %s", species_query)

    cmd = (
        f"mkdir -p {run_dir} && "
        f"cd {run_dir} && "
        f'{_GET_NEAREST_COMPARATOR} -s "{species_query}" -d -n {number}'
    )
    try:
        _run(cmd, ctx.print_only)
        _reheader_downloaded_references(ctx, run_dir)
        if ctx.tracker and run_dir:
            ctx.tracker.finish("find_reference", run_dir, "success")
    except Exception:
        if ctx.tracker and run_dir:
            ctx.tracker.finish("find_reference", run_dir, "failed")
        raise
    print_done(f"Reference downloaded to {run_dir}")
```

Note: `reheader_reference` is defined earlier in this same file (line 33) — no new import needed. `Path` is already imported at the top of the file.

- [ ] **Step 4: Add the `--local` CLI option**

Replace the CLI block at the bottom of the same file:

```python
@click.command("find-reference", cls=GritCommand)
@click.option(
    "--local",
    "-l",
    "local_path",
    default=None,
    help="Path to a local reference FASTA (.fa/.fna, optionally .gz) — skips the NCBI download and preps this file instead.",
)
@click.pass_context
def find_reference_cmd(ctx, local_path):
    """Find and download closest reference genome."""
    from grit.core.click_cli import build_context

    state = ctx.obj
    curation_ctx = build_context(state)
    try:
        find_closest_reference(curation_ctx, local_path=local_path)
    except Exception:
        log.exception("find-reference failed")
        raise SystemExit(1)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_find_reference.py -v`
Expected: all four tests PASS.

- [ ] **Step 6: Run the full test suite to check for regressions**

Run: `pytest tests/ -v`
Expected: all tests pass (in particular `tests/test_fastga_synteny.py`, `tests/test_busco_synteny.py`, and any smoke test touching `find-reference`/`fastga`/`busco-synteny` CLI help output).

- [ ] **Step 7: Manual sanity check of the CLI wiring**

Run: `grit --yaml tests/fixtures/uoEpiScra1_hap1_hap2.yaml --print-only find-reference --local /tmp/whatever.fa`
Expected: prints the `mkdir -p ... && ln -s ...` command (not executed, since `--print-only`) and a `reheader` command from `reheader_reference`, then "Local reference prepared in ..." — no traceback, no NCBI script invoked.

- [ ] **Step 8: Commit**

```bash
git add grit/steps/pre_curation/find_reference.py tests/test_find_reference.py
git commit -m "feat(find-reference): add --local option to prep a local reference instead of downloading"
```
