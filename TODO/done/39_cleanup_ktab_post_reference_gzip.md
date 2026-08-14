# TODO 39: cleanup — drop FastK index files, truncate spent reference, gzip curated fasta

## Problem

`grit/core/cleanup.py::plan_cleanup()` frees disk for done tickets by (1)
keeping only the latest run dir per step in `_STEPS_KEEP_LATEST` and (2)
deleting `original.fa` from the workdir root. It misses three large,
routinely-recoverable categories of disk usage that only show up *inside*
the kept (latest) run dir of a step — i.e. survive today's cleanup
untouched:

- **FastK index files.** The `reheader`/GRIT indexing toolchain leaves
  per-thread `.ktab`/`.post` files (e.g. `.aRanArv1.hap1.1.primary.curated.ktab.1`
  through `.8`, same for `.post.1`-`.8`) next to the fasta/AGP/`.1gdb`/`.bps`/
  `.gix` outputs in both `find_reference` and `pretext_to_asm` run dirs.
  These are multi-GB each, purely intermediate (nothing downstream reads
  them once the run has finished), and currently untouched because they
  live inside the *kept* run dir, which `plan_cleanup` only trims of its
  `work/` subdir.
- **The downloaded reference genome.** `find_reference`'s kept run dir keeps
  the multi-GB raw downloaded fasta (e.g. `GCF_905171775.1_aRanTem1.1_genomic.fna`)
  and the reheadered copy (`{prefix}_reheader.fna`, the one
  `find_reheadered_reference()` in `grit/utils/helpers.py` actually hands to
  `fastga`/`busco-synteny`) forever, plus `.1gdb`/`.bps`/`.gix` index files
  built from it — none of which are needed once the ticket is done, but
  losing all record of *which* reference was used would make the curation
  history harder to audit later.
- **Uncompressed curated fasta.** `pretext_to_asm`'s kept run dir holds the
  final curated `.fa` files (primary/alternate curated, haplotigs,
  falseduplicates) uncompressed — multi-GB each, compress losslessly with
  no functional loss.

Also confirm/document: removal of non-canonical (non-latest) `pretext_to_asm`
run dirs is already handled by the existing `_STEPS_KEEP_LATEST` loop — no
change needed there, just call it out explicitly in `cleanup_cmd`'s
docstring since the ticket that prompted this asked for it directly.

## Design

### 0. `plan_cleanup` returns actions, not bare paths

Today `plan_cleanup() -> list[Path]` and `run_cleanup()` deletes every
entry the same way (`rmtree` or `unlink`). Three different dispositions are
needed now, so change the return type to `list[tuple[str, Path]]` where the
first element is a `kind` of `"delete"`, `"truncate"`, or `"gzip"`:

```python
CleanupAction = tuple[str, Path]  # (kind, path); kind: "delete" | "truncate" | "gzip"
```

`run_cleanup()`'s table gains an `Action` column, and its execution loop
dispatches on `kind`:

- `"delete"` — exactly as today (`rmtree` for dirs, `unlink` for files).
- `"truncate"` — `path.write_bytes(b"")`, keeping the filename. Used only
  for the reference's `_reheader.fna` (see below) so the accession that was
  actually used to compare against stays visible in a directory listing
  even after the multi-GB content is gone.
- `"gzip"` — fire-and-forget `bsub` (matches every other bsub call in the
  codebase — non-blocking, no `-K`), submitted via the existing
  `_submit_bsub`/`build_bsub_opts` helpers from `grit/utils/helpers.py`.
  Under `dry_run=True` this only prints the command (same as `_run`'s
  existing `print_only` behavior) — nothing is actually submitted until
  `--yes`.

### 1. FastK index files — any kept run dir, not just two specific steps

Add a small helper:

```python
def _is_fastk_index_file(name: str) -> bool:
    """True for FastK per-thread index files (``*.ktab.N`` / ``*.post.N``)."""
    return ".ktab." in name or ".post." in name
```

Don't use `Path.glob("*.ktab.*")` for this — pathlib's glob dot-file
matching behavior isn't consistent across Python versions (verified: 3.13's
`Path.glob` matches leading-dot filenames against a non-dot pattern; the
`glob` module's `glob.glob` does not). Iterate `kept_dir.iterdir()` and
filter by `_is_fastk_index_file(f.name)` instead, so behavior doesn't
depend on which glob implementation happens to be in play.

Apply this inside **every** kept run dir from the existing
`_STEPS_KEEP_LATEST` loop (not hardcoded to `find_reference`/
`pretext_to_asm`) — the FastK toolchain isn't specific to those two steps,
and a future step producing the same file pattern should be covered for
free. Concretely: track the `keep` dir per step as the loop already
computes it, and after the existing per-step loop, do a second pass over
the collected `{step: keep_dir}` mapping adding `("delete", f)` for every
`_is_fastk_index_file` match in each kept dir.

### 2. Reference: truncate the used copy, delete everything else

For `find_reference`'s kept run dir specifically, iterate its files:

- Name ends with `_reheader.fna` (the file `find_reheadered_reference()`
  actually resolves via `glob.glob(str(ref_dir / "*_reheader.fna"))`) and is
  non-empty → `("truncate", f)`. An empty file is left with the original
  filename intact — enough to answer "what reference was this compared
  against" from a directory listing without re-running `find-reference`.
- Anything else in that dir (the raw downloaded `.fna`/`.fna.gz`, `.1gdb`,
  `.bps`, `.gix`) → `("delete", f)`. (FastK `.ktab`/`.post` files in this
  same dir are already covered by step 1's generic pass — don't double
  them up here.)

### 3. gzip curated fasta in `pretext_to_asm`'s kept run dir

For `pretext_to_asm`'s kept run dir, for every `*.fa` file with non-zero
size (some, like `*.all_haplotigs.curated.fa`, are legitimately empty when
a haplotype has no haplotigs — nothing to gzip, and an empty-input `pigz`
job is just wasted queue time):

```python
("gzip", fa_path)
```

executed as a single `bsub` job per kept `pretext_to_asm` dir (not one job
per file) — `pigz` is already on the compute nodes' `PATH` (no
`module_cmd` entry needed):

```python
inner_cmd = f"cd {ptoa_kept_dir} && pigz -p 8 *.fa"
bsub_opts = build_bsub_opts(
    memory_mb=4000,
    cores=8,
    queue="normal",
    output=str(ptoa_kept_dir / "gzip_fa.out"),
    error=str(ptoa_kept_dir / "gzip_fa.err"),
)
_submit_bsub(inner_cmd, bsub_opts, dry_run)
```

Since this needs `dry_run` (to decide `print_only`) rather than returning a
path to add to `all_targets`, this action fires directly from
`run_cleanup()`'s execution loop when it hits a `"gzip"` action — same
place the `"delete"`/`"truncate"` branches live — not from inside
`plan_cleanup()` itself (which stays a pure planner with no side effects,
consistent with its current contract and with dry-run needing to *display*
the action without executing it).

### 4. `cleanup_cmd` docstring

Update to mention all four behaviors (keep-latest run dirs — including
`pretext_to_asm` — Nextflow `work/` dirs, `original.fa`, FastK index files,
the reference truncate-not-delete, and the `pretext_to_asm` gzip) so the
docstring doesn't drift out of sync the way `plan_cleanup`'s inline comments
already have.

## Testing

- Add fixture-based unit tests for `plan_cleanup()` (via `tmp_path`,
  building a fake workdir tree) asserting: FastK index files inside a kept
  dir are flagged `"delete"`; the reference's `_reheader.fna` is flagged
  `"truncate"` (and only when non-empty); other reference-dir files are
  `"delete"`; non-zero `.fa` files in the kept `pretext_to_asm` dir are
  `"gzip"`; zero-byte `.fa` files are skipped entirely.
- Extend the existing `run_cleanup()` test (mocking `subprocess`/`_run` the
  way other bsub-calling steps are tested — via call inspection, not a real
  `bsub`) to assert a `"gzip"` action results in exactly one `_submit_bsub`
  call per kept `pretext_to_asm` dir, with `print_only` following
  `dry_run`.

## Net effect

- Kept (latest) run dirs shrink by their FastK intermediate files and, for
  `find_reference`, by the raw/indexed reference genome — multi-GB per
  ticket, freed without losing which reference/step ran.
- The reference actually used for comparison stays identifiable by
  filename (0 bytes) instead of disappearing entirely.
- Curated fasta output in `pretext_to_asm` is compressed in place via a
  fire-and-forget `bsub pigz` job, matching how every other long-running
  step in the codebase submits work.
- Non-canonical `pretext_to_asm` run dirs were already deleted by the
  existing `_STEPS_KEEP_LATEST` loop — confirmed, documented, no code
  change needed for that part.
</content>
