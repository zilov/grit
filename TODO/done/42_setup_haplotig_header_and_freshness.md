# 42 — setup_curation: haplotig glob fallback, header validation, original.fa freshness

## Problem

Three related issues surfaced from a real incident (RC ticket for `ilBrySene2`):

1. `.haplotigs.decontaminated.fa.gz` for that assembly had raw assembler-style
   headers (`>atg000001l`) instead of the expected `SCAFFOLD_N` /
   `HAPM_SCAFFOLD_N` convention that `pretext_to_asm` relies on to match AGP
   components against `original.fa`. Nothing in `setup_curation` catches this
   — the bad headers silently flow into `original.fa` and only manifest as a
   broken mapping downstream, in `pretext_to_asm`.

2. `setup_curation`'s hap2 file search (`grit/steps/pre_curation/setup.py:69-99`)
   builds `hap2_pattern` from `ctx.hap2_prefix` (e.g. `"alternate"`), but the
   real (non-print-only) code path has a fallback to the literal string
   `"haplotigs"` when the `hap2_prefix` glob finds nothing (setup.py:91-94).
   `--print-only` never reaches this fallback — the whole `if not
   ctx.print_only:` block is skipped — so it always prints the
   `hap2_prefix`-based pattern even when the real run would (and did) fall
   back to `"haplotigs"`. Dry-run output doesn't reflect what actually runs.

3. Re-running/regenerating `original.fa` (e.g. after fixing bad headers
   upstream) doesn't cause downstream steps to notice it changed.
   `pretext_to_asm`'s rerun decision (`agp_newer_than_curated_fa`,
   `grit/utils/helpers.py:242-252`) only compares AGP mtime against
   `.curated.fa` mtime — `original.fa`'s mtime is never part of that
   comparison, so a stale `.curated.fa` can survive even though its input
   changed.

## Design

### 1. Header validation in `setup_curation`

Add a helper that peeks at the first FASTA header of a (possibly gzipped)
file and validates it against the expected convention:

```python
_SCAFFOLD_HEADER_RE = re.compile(r"^>(HAPM_)?SCAFFOLD_\d+")


def _validate_scaffold_headers(fasta_path: Path) -> None:
    first_header = _peek_first_fasta_header(fasta_path)  # zcat -c | head -1
    if not _SCAFFOLD_HEADER_RE.match(first_header):
        raise ValueError(
            f"{fasta_path} has unexpected header {first_header!r} — "
            f"expected SCAFFOLD_N / HAPM_SCAFFOLD_N. Upstream decontamination "
            f"likely didn't rename contigs; fix upstream before re-running setup."
        )
```

Called on `decont_hap1` and (if present) `decont_hap2` after they're resolved,
before the `zcat` that builds `original.fa`. Only checks the first header —
cheap, and in practice a renaming failure affects the whole file uniformly.
Real-run only (mirrors the existing `if not ctx.print_only:` guard) — print-only
doesn't touch file contents today and this doesn't change that.

Fail loudly: raise, don't create `original.fa`. `run_setup` already wraps
`setup_curation` in try/except and marks the tracker `"failed"` on exception —
no changes needed there.

### 2. Unify hap1/hap2 glob resolution between print-only and real paths

Extract the search (primary pattern → generic `*decontaminated.fa*` fallback
for hap1 → literal `"haplotigs"` fallback for hap2) into one function used by
both branches:

```python
def _resolve_decontaminated_fasta(
    assembly_draft_dir: Path, tol_id: str, hap_prefix: str, extra_fallback_prefix: str | None = None
) -> Path | None:
    """Glob for the decontaminated FASTA, trying hap_prefix then extra_fallback_prefix."""
```

`--print-only` calls this (read-only `glob.glob`, no mutation) and prints
whichever path/pattern would actually be picked, including when the
`"haplotigs"` fallback is what matched — so dry-run output matches reality.

### 3. Track `original.fa` freshness in the rerun decision

Generalize `agp_newer_than_curated_fa` to accept extra input files:

```python
def inputs_newer_than_curated_fa(
    workdir: Path, tol_id: str, pta_dir: Path | None, extra_inputs: list[Path] = ()
) -> bool:
    """Return True if AGP or any extra_inputs are newer than the curated FASTA in pta_dir."""
    curated_fas = list(pta_dir.glob(f"{tol_id}*.curated.fa")) if pta_dir else []
    if not curated_fas:
        return False
    agp_files = list(workdir.glob(f"{tol_id}*.pretext.agp_1")) or list(
        workdir.glob(f"{tol_id}*.agp*")
    )
    input_files = agp_files + [p for p in extra_inputs if p.exists()]
    if not input_files:
        return False
    return max(f.stat().st_mtime for f in input_files) > min(f.stat().st_mtime for f in curated_fas)
```

Rename in place (single call site in
`_run_pretext_to_asm_core`, `grit/steps/post_curation/pretext_to_asm.py:62`),
passing `extra_inputs=[original_fa]` (already a local parameter there). No new
tracker state or `_OUTPUT_SPECS` entries — this only widens an existing mtime
comparison.

## Testing

- `_validate_scaffold_headers`: valid `SCAFFOLD_1`/`HAPM_SCAFFOLD_3` header
  passes; `atg000001l`-style header raises `ValueError` with the offending
  path/header in the message.
- `_resolve_decontaminated_fasta`: hap_prefix match found → returned as-is;
  no match + fallback match → fallback returned; print-only and real paths
  exercise the same function (assert via mocked `glob.glob` call count/args,
  matching existing `_run`/`bsub` mocking conventions in this repo).
- `inputs_newer_than_curated_fa`: AGP newer → True (existing case, regression
  guard); `original.fa` newer with AGP unchanged → True (new case); both
  older than curated fa → False.
