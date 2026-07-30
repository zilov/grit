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
</content>
