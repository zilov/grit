# TODO 45: `--dry-run` mode for testing pipeline/tracking logic without HPC

## Problem

Testing anything about how steps sequence and how canonical-output resolution
behaves (`find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs`
in `grit/utils/helpers.py`, the flat mtime pool from
`TODO/done/44_canonical_fa_flat_mtime_priority.md`, `grit status -t`'s ★
marker, `grit untrack`) currently means either writing a unit test (good for
the logic itself, but not a real end-to-end CLI check) or actually running
the pipeline on the farm — which means waiting on real `bsub`/HPC jobs and
external tools (`decon_blastBTK`, `rename-and-orient`, BUSCO, etc.) to
finish, sometimes for a long time, just to see whether a sequence of CLI
commands produces the tracker state and canonical resolution you expect.

`--print-only` (`grit/core/base_command.py:52-59`) already exists and does
its own job well — print the constructed command, execute nothing, touch no
files — but that's the opposite of what's needed here: it can't be used to
drive `grit status -t`/`find_canonical_fa`/`grit untrack` through a real
sequence of completed steps, because nothing is ever tracked as done.
`--print-only` stays exactly as-is; this task adds a second, independent
mode: `--dry-run`, which makes a step **actually** create its final tracked
output file(s) and call `RunTracker.finish(..., "success", ...)` for real —
while never shelling out to any real external tool, never submitting a real
`bsub` job, and never touching real registry/workdir state.

## Global Constraints

(binding on every task below — from `CLAUDE.md`)

- `log.*` for internal logging, `console.print()` (via `grit/utils/output.py`)
  only for curator-facing structured output — never bare `print()`.
- Minimal docstrings: one line stating what the function does/returns. No
  historical context about the bug/task that motivated a change.
- No comments explaining *what* code does or referencing this task/ticket;
  only comments justifying a genuinely non-obvious *why*.
- `--print-only` must remain completely untouched in behavior — `--dry-run`
  is an independent, orthogonal flag. If both are somehow set on the same
  invocation, `--print-only` takes precedence (check it first).
- Tests use the `mock_ctx` fixture (`tests/conftest.py`) and fixture YAML
  under `tests/fixtures/`; no real filesystem/Jira access; `subprocess`/`bsub`
  calls are mocked and verified via call inspection. Any test touching
  `RegistryManager`/`RunTracker` must point them at a `tmp_path`, never the
  real `~/.grit`.
- After each task: `uv run pytest tests/ -v` (full suite, not just the
  touched file) and `uv run ruff check . && uv run ruff format .` must both
  be clean before committing.
- Do not touch files outside this task's listed scope.

---

## Task 1: Plumbing — thread `--dry-run` everywhere `--print-only` goes, and isolate it from real state

**Scope:** `grit/core/base_command.py`, `grit/core/click_cli.py`,
`grit/core/context.py`, `grit/core/registry.py`, `grit/core/run_tracker.py`
(read-only reference, no change expected there — confirm), plus
`tests/test_base_command.py`, `tests/test_context.py`,
`tests/test_registry.py` (all confirmed to exist). There is **no**
`tests/test_click_cli.py` today — `status_cmd`/`untrack_cmd` have zero
existing test coverage at the CLI level (only `RunTracker.untrack()` itself
is tested, in `tests/test_run_tracker.py`). Create
`tests/test_click_cli.py` for the new tests these two commands need,
following the exact pattern already established in
`tests/test_remove_cmd.py` (confirmed working): `from click.testing import
CliRunner`, `from grit.core.click_cli import cli`, and an autouse fixture
`monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", tmp_path)` to keep
the CLI-invoked commands' default `RegistryManager()` construction off the
real `~/.grit` for the whole test file (that fixture is for the *default*
registry, not `dry_run_root()` — see Task 1b below for the separate
`dry_run_root()` monkeypatch you'll also need).

### 1a. Flag plumbing (mirrors `--print-only` exactly)

- `base_command.py`: `GritCommand.__init__` inserts `--ticket`,
  `--print-only`, `--untracked`, (`--bsub-ram`) in that order (lines 33-68,
  each via `self.params.insert(0, ...)`, ending up in reverse declaration
  order). Add a fifth `click.Option(["--dry-run"], is_flag=True,
  default=False, help="Create placeholder outputs and mark steps done, "
  "without running any real command (for testing pipeline/tracking logic).")`
  the same way, and pop/OR it in `invoke()` (lines 70-96) alongside
  `print_only`/`untracked`/`bsub_ram`.
- `click_cli.py`: `GlobalState.__init__` (lines 31-52) gains
  `dry_run: bool = False`; the group-level `cli()` command (line 72) gets a
  matching `--dry-run` option next to the existing `--print-only` (mirrors
  line 62's `@click.option("--print-only", ...)`); `build_context()`
  (line 93) passes `dry_run=state.dry_run` through alongside
  `print_only=state.print_only` (line 107).
- `context.py`: `CurationContext` (class starting line 44) gains
  `dry_run: bool = False` next to `print_only` (line 87); `from_yaml`/
  `from_ticket` (lines 108, 191) gain a `dry_run: bool = False` parameter
  and thread it through to the constructed instance (lines 182, 231) the
  same way `print_only` already is.

### 1b. Isolation — dry-run must never touch the real registry or a real workdir

This is the part that has to be right before any step gets a dry-run
branch: as written, `RunTracker`/`RegistryManager` always point at the
**same** shared state a real curation uses.

- **Registry:** `RegistryManager()` defaults to `~/.grit/grit_registry.json`
  (`registry.py:34-43`) — the single file `grit status`, `grit summary`, and
  every real ticket's step history live in. `RunTracker.__init__` accepts an
  optional `registry` (`run_tracker.py:47-58`) but every constructor site
  currently omits it, so `RunTracker` lazily builds its own `RegistryManager()`
  — the real one — the first time it's needed (`run_tracker.py:301`).
- **Workdir:** `from_yaml`/`from_ticket` compute `workdir =
  _derive_workdir(assembly_draft_dir.parent, cfg.username, tol_id)`
  (`context.py:157`) — the same real farm path a real run would use.

**Implement:** add `dry_run_root() -> Path` returning `Path.home() /
".grit" / "dry_run"` next to `_DEFAULT_DIR` in `registry.py`. Use it in:

1. `context.py`'s `from_yaml`/`from_ticket`: when `dry_run=True`, override
   `workdir = dry_run_root() / tol_id` instead of calling
   `_derive_workdir(...)` — apply this right after `tol_id` is known, before
   constructing `RunTracker`.
2. Same two constructors: pass `RunTracker(workdir, print_only=print_only,
   registry=RegistryManager(registry_dir=dry_run_root()))` when
   `dry_run=True`, instead of relying on `RunTracker`'s default lazy
   (real-registry) construction.
3. `status_cmd` (`click_cli.py:167-183`, a plain `@cli.command("status")`,
   **not** a `GritCommand` — it has no per-command option injection at all)
   constructs `RegistryManager()` directly (line 176), bypassing
   `build_context()` entirely — it never sees a `CurationContext`. Read
   `ctx.obj.dry_run` (the same group-level `GlobalState` the `--dry-run`
   option from Task 1a sets — reachable here only as `grit --dry-run
   status -t <ticket>`, since `status`/`untrack` don't get their own
   per-command `--dry-run` option the way `GritCommand`-based step commands
   do) and swap in `RegistryManager(registry_dir=dry_run_root())` when set.
4. `untrack_cmd` (`click_cli.py:263-303`, same plain-`@cli.command` shape)
   does the same at line 274 (plus a second bare `RunTracker(workdir)` at
   line 280 that needs the matching `registry=` override). Branch on
   `ctx.obj.dry_run` the same way — again only reachable as `grit --dry-run
   untrack ...`, not a per-command flag.
5. `_state-update` (`click_cli.py:186-225`, the hidden bsub-epilogue
   command) needs **no** change — dry-run steps never call `_submit_bsub()`
   (Task 4+), so it is never invoked in dry-run mode. Leave it untouched;
   note this explicitly in your report so the reviewer doesn't flag it as
   missed scope.
6. Do **not** touch `cleanup.py:188`'s `RegistryManager()` construction —
   `grit cleanup` should keep operating on real tickets only by default;
   auditing/fixing it is explicitly out of scope for this plan.

Everything else `CurationContext` carries (`hic_dir`, `long_reads_dir`,
`assembly_curated_dir`, etc.) stays derived from the real YAML/ticket
untouched — harmless, since every dry-run step branch (Tasks 3-6) returns
before ever reading from those paths.

### Tests

- Flag threading: a test confirming `--dry-run` at the group level and at a
  per-command level both set `ctx.obj.dry_run = True`/`ctx.dry_run = True`
  through to a built `CurationContext`, mirroring whatever existing test
  covers `--print-only`'s threading.
- Isolation: a test that constructs two `CurationContext`s from the same
  YAML fixture — one with `dry_run=False`, one with `dry_run=True` — and
  asserts the `dry_run=True` one's `workdir` is under a `dry_run_root()`
  that was itself overridden (e.g. via monkeypatching `dry_run_root` to
  return a `tmp_path`) to a location distinct from the `dry_run=False`
  one's real-derived workdir, and that its `tracker`'s underlying registry
  points at that same `tmp_path`, not `~/.grit`.
- `status_cmd`/`untrack_cmd` (new `tests/test_click_cli.py`, per the Scope
  note above): using `CliRunner`/`cli` exactly like `tests/test_remove_cmd.py`
  does, seed a ticket via `RegistryManager(registry_dir=tmp_path).add_ticket(...)`
  where `tmp_path` is what `dry_run_root()` was monkeypatched to return,
  then invoke `["status", "-t", ticket_id, "--dry-run"]` (or however the
  flag reaches these commands per your Task 1a wiring) and assert it reads
  from that `tmp_path` registry, not the one the autouse
  `_DEFAULT_DIR`-patched fixture points at — i.e. the test must prove
  dry-run and non-dry-run invocations resolve to two *different*
  registries, not just that dry-run doesn't crash.

**Report file:** `.superpowers/sdd/45_dry_run_mode/task-1-report.md`

---

## Task 2: Shared placeholder-output writer (`write_fake_outputs`)

**Scope:** `grit/utils/helpers.py` only, plus its existing test file
(`tests/test_helpers_canonical.py` or a more general helpers test file —
check which file already covers `collect_outputs`/`_get_step_specs` and add
alongside it).

`grit/utils/helpers.py` already has the registry this needs: `_get_step_specs(step)`
(lines 768-800) maps a tracker step name to its `_OUTPUT_SPECS`/
`_OUTPUT_SPECS_HAP2` constant via lazy import, and `collect_outputs(specs,
run_dir, tol_id, ...)` (lines 748-765) globs `run_dir` against those specs
to build the `{key: path}` dict `tracker.finish()` wants. Add the inverse
next to it:

```python
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
    Write one placeholder file per _OUTPUT_SPECS entry for *step* into
    run_dir, using the first concrete glob match (wildcards filled with a
    fixed placeholder token) as the filename. Returns the same {key: path}
    shape collect_outputs() would have found, ready for tracker.finish().
    """
```

Each spec's `pattern.format(tol_id=tol_id, hap1=hap1, hap2=hap2)` (same
substitution `collect_outputs` already does, `helpers.py:761`) still has
`*`/`?` wildcards for the parts a real run fills in dynamically (release
version, run-specific suffixes) — fill every such wildcard with a fixed
placeholder token (e.g. `1`) to get one concrete filename per spec. Skip
specs whose `key` was already written by an earlier spec in the same list
(mirrors `collect_outputs`'s own `if key in outputs: continue` dedup at line
759, since some specs are fallback patterns for the same key). `run_dir`
must exist before writing (create it if the caller hasn't already — check
whether `ctx.tracker.start()` already creates it, per its
`create_dir: bool = True` default, and rely on that rather than duplicating
directory creation). Write `content.get(key, b">fake\nACGT\n")` if `content`
is given for that key, otherwise a trivial one-line stub.

`_get_step_specs` currently returns `[]` for unknown steps (line ~795) —
`write_fake_outputs` should return `{}` in that case too (nothing to write),
not raise, so a step without spec coverage yet degrades to "no outputs
tracked" rather than crashing.

### Tests

- For at least 2-3 real steps' `_OUTPUT_SPECS` (e.g. `pretext_to_asm`,
  `rename_and_orient`), assert `write_fake_outputs` produces files on disk
  matching each spec's glob pattern, and that `collect_outputs` (the real,
  existing function) run against the same `run_dir` finds exactly what
  `write_fake_outputs` returned — i.e. round-trip through the real glob
  logic, not just checking `write_fake_outputs`'s own return value in
  isolation.
- A case with a `content=` override for one key, asserting the written
  file's actual bytes match what was passed, and a case without `content=`
  asserting the trivial stub was written.
- A step name not in `_get_step_specs`'s map returns `{}` and writes
  nothing.

**Report file:** `.superpowers/sdd/45_dry_run_mode/task-2-report.md`

---

## Task 3: `setup_curation` dry-run branch — bootstrap the isolated ticket/workdir

**Scope:** `grit/steps/pre_curation/setup.py` and its existing test file
only. Depends on Task 1 (`ctx.dry_run`, `dry_run_root()`) landing first.

`RegistryManager.find_ticket()` (`registry.py:134-136`) — which
`status_cmd`/`untrack_cmd` depend on to resolve a ticket to a workdir — only
ever finds tickets registered via `add_ticket()` (`registry.py:49-93`), and
the *only* caller of `add_ticket()` today is `setup_curation`
(`setup.py:348`). Without a dry-run branch here, there is no way to make a
synthetic dry-run ticket visible to `grit status -t`/`grit untrack` at all.

Add an early `if ctx.dry_run:` branch in `run_setup_curation` (or whatever
the public function is named — read the file first) that skips every real
thing setup normally does (module loads, gap/telomere tracks, sex-matcher,
copying `original.fa`) and instead:

1. Ensures `ctx.workdir` exists (it's already `dry_run_root() / tol_id` per
   Task 1 — just `mkdir(parents=True, exist_ok=True)`).
2. Calls `RegistryManager(registry_dir=dry_run_root()).add_ticket(
   ctx.ticket_id, ctx.tol_id, ctx.species, ctx.workdir,
   hap1_prefix=ctx.hap1_prefix, hap2_prefix=ctx.hap2_prefix)` directly.
3. Writes a trivial placeholder `original.fa` into `ctx.workdir` (matching
   the real step's tracked output per `grit/core/manifests.py`'s
   `setup_curation` entry: `{"dir": "workdir", "files": ["original.fa"]}`)
   — reuse `write_fake_outputs` from Task 2 if its shape fits a
   `workdir`-rooted (non-run_dir) output, otherwise write it directly; check
   which is simpler once Task 2 is done and note your choice in the report.
4. Prints a `print_done(...)` confirming the dry-run ticket/workdir, and
   returns — no `ctx.tracker.start()`/`finish()` call needed here since
   `setup_curation` isn't itself a `RunTracker`-tracked step (confirm this
   against the real function before assuming).

### Tests

- After calling the dry-run branch with a fixture YAML, assert
  `RegistryManager(registry_dir=<tmp_path>).find_ticket(ticket_id)` (with
  `dry_run_root` monkeypatched to that `tmp_path`) returns a record whose
  `workdir` matches `ctx.workdir`.
- Assert no real `~/.grit` path was touched (e.g. by asserting the
  monkeypatched `dry_run_root` was actually called/used, or by pointing
  `RegistryManager()`'s default dir at a `tmp_path` for the whole test via
  the existing `mock_ctx`/registry test fixtures — check how other registry
  tests in this repo already avoid touching the real `~/.grit`).

**Report file:** `.superpowers/sdd/45_dry_run_mode/task-3-report.md`

---

## Task 4: `pretext_to_asm` dry-run branch

**Scope:** `grit/steps/post_curation/pretext_to_asm.py` and its existing
test file only. Depends on Tasks 1-2.

`pretext_to_asm` is the root of the canonical-FASTA flat mtime pool
(`TODO/done/44_canonical_fa_flat_mtime_priority.md`) — needed before any
other step's dry-run branch can be meaningfully tested end-to-end.

Add an early `if ctx.dry_run:` branch in the step's public run function,
before `_run_pretext_to_asm_core`/any real AGP-glob or subprocess logic:
call `ctx.tracker.start("pretext_to_asm", ctx.ticket_id, ctx.tol_id)`, then
`write_fake_outputs("pretext_to_asm", run_dir, ctx.tol_id, hap1=ctx.hap1_prefix,
hap2=ctx.hap2_prefix, content={...})`, then `ctx.tracker.finish(...,
"success", outputs=...)`, then `print_done(...)`, then return.

**Content realism matters here**: `blast_contaminants.py`'s scaffold-ID
extraction (`perl -nE 'say "true,$1" if /([HAP_\d]*SCAFFOLD_\d+)/i'`, line
109) needs real `>SCAFFOLD_1`/`>HAP_SCAFFOLD_1`-style headers in the fake
curated FASTA to exercise its actual matching logic in Task 5. Pass
`content={"hap1_fa": b">SCAFFOLD_1\nACGTACGTACGT\n>SCAFFOLD_2\nACGTACGTACGT\n",
"hap2_fa": b">HAP_SCAFFOLD_1\nACGTACGTACGT\n"}` (adjust keys to match this
step's actual `_OUTPUT_SPECS` key names — read the file to confirm) so the
fake FASTA a curator/developer produces here is realistic enough for every
downstream dry-run step in this plan.

### Tests

- After a dry-run call, assert `ctx.tracker.get_output("pretext_to_asm",
  "hap1_fa")` (or whatever the real key name is) resolves to a real,
  existing file, and that its content contains `SCAFFOLD_` headers.
- Assert `find_canonical_fa(ctx, ctx.hap1_prefix)` (the real function from
  `helpers.py`) resolves to that same fake file — i.e. the dry-run output
  actually participates in the real canonical-resolution pool, not just in
  the tracker's bookkeeping.

**Report file:** `.superpowers/sdd/45_dry_run_mode/task-4-report.md`

---

## Task 5: `blast_contaminants` and `rename_and_orient` dry-run branches

**Scope:** `grit/steps/optional/blast_contaminants.py`,
`grit/steps/optional/rename_and_orient.py`, and their existing test files.
Depends on Tasks 1-2 and 4 (needs a fake `pretext_to_asm` output to chain
onto for its own tests).

These are the two steps this whole feature was motivated by testing (the
SCAFFOLD-header warn-and-continue mitigation and the flat-pool
forward-chain from `TODO/done/44_canonical_fa_flat_mtime_priority.md`).

For each, add the early `if ctx.dry_run:` branch **before** any real
subprocess work — this matters especially for `blast_contaminants`, whose
`_blast_contaminants_for_hap` runs the lineage script, writes/reads
`blast.me`, and calls `decon_blastBTK` across 6 sequential `_run()` calls
with real intermediate files feeding each other in Python; short-circuit
the *whole* function early rather than trying to fake each intermediate
call — only the final tracked output (`{tol_id}.{hap}.{version}.decontaminated.fa`
for blast, `{tol_id}.{hap}.*.fa` for rename) matters to any downstream code.
For `rename_and_orient` (a bsub-based step, per
`TODO/done/44_canonical_fa_flat_mtime_priority.md`'s Task 3 fix which made
it write into its own tracked `run_dir`), the dry-run branch must **not**
call `_submit_bsub()` — write the placeholder output directly into the
`run_dir` from `ctx.tracker.start(...)` and call `ctx.tracker.finish(...)`
synchronously instead.

Content: plain stubs are fine for both — neither output is content-parsed
by anything downstream (only existence/mtime matters to `find_canonical_fa`
and to each other).

### Tests

- Each step: after a dry-run call, `ctx.tracker.get_output(step_name, ...)`
  resolves to a real file, and `find_canonical_fa` picks it up as canonical
  once it's the freshest in the pool.
- A chained scenario test: dry-run `pretext_to_asm` → dry-run
  `blast_contaminants` → assert `find_canonical_fa` now resolves to
  blast's output, not pretext_to_asm's → dry-run `rename_and_orient` →
  assert `find_canonical_fa` now resolves to rename's output. This is the
  core scenario this whole feature exists to make testable without HPC —
  make sure it's covered by an explicit test, not just implied by the two
  steps' individual tests.
- Confirm neither branch calls `_run()`/`_submit_bsub()` (assert the mock
  for those was never invoked when `dry_run=True`).

**Report file:** `.superpowers/sdd/45_dry_run_mode/task-5-report.md`

---

## Task 6: `microchromosome_combine` and `pretext_to_asm_recurate` dry-run branches

**Scope:** `grit/steps/post_curation/microchromosome_combine.py`,
`grit/steps/post_curation/pretext_to_asm_recurate.py`, and their existing
test files. Depends on Tasks 1-2 and 4.

Completes dry-run coverage of every step in the canonical-FASTA flat mtime
pool. Same shape as Task 5: early `if ctx.dry_run:` branch, short-circuit
before any real intermediate `_run()` calls or external scripts, write only
the final tracked output(s), plain stub content (neither is content-parsed
downstream).

For `pretext_to_asm_recurate`, note it takes a `hap_prefix`/`step_name`
argument pair (for hap1 vs hap2) — the dry-run branch must track under the
correct `step_name` (`pretext_to_asm_recurate` or `_hap2`) exactly like the
real path does, so it participates correctly in the flat mtime pool per
haplotype.

### Tests

- Same shape as Task 5: tracked output resolves to a real file;
  `find_canonical_fa`/`find_canonical_haplotigs` pick it up correctly;
  no real `_run()`/subprocess call happens.
- A scenario test chaining dry-run `pretext_to_asm` → dry-run
  `pretext_to_asm_recurate` → assert canonical_fa is now the recurate
  output → dry-run `blast_contaminants` again → assert canonical_fa moves
  to blast's output (the "chain forward from recurate" behavior from
  `TODO/done/44_canonical_fa_flat_mtime_priority.md`, now testable without
  HPC).

**Report file:** `.superpowers/sdd/45_dry_run_mode/task-6-report.md`

---

## Task 7: Verification — smoke-test scenario + `CLAUDE.md` doc

**Scope:** `tests/local_smoke_test.sh` and `CLAUDE.md` only. Depends on
Tasks 1-6 all being complete.

Add a `--dry-run` pass to `tests/local_smoke_test.sh` (the existing
farm-path smoke test) chaining a real sequence through the actual CLI:

```bash
grit setup -t <ticket> --dry-run              && ok "setup --dry-run"
grit pretext-to-asm -t <ticket> --dry-run      && ok "pretext-to-asm --dry-run"
grit blast-contaminants -t <ticket> --dry-run  && ok "blast-contaminants --dry-run"
grit rename-and-orient -t <ticket> --dry-run   && ok "rename-and-orient --dry-run"
# status/untrack aren't GritCommand-based, so --dry-run only works at the
# group level for them: `grit --dry-run status ...`, not `grit status ... --dry-run`
grit --dry-run status -t <ticket>
# assert (grep the output) that the ★ marker lands on rename_and_orient's row
grit --dry-run untrack -t <ticket> --step rename_and_orient
grit --dry-run status -t <ticket>
# assert the ★ now lands on blast_contaminants's row
rm -rf ~/.grit/dry_run   # leave no trace
```

Match whichever ticket-id/fixture convention `local_smoke_test.sh` already
uses for its other `--print-only` steps (read the file first). This is
exactly the scenario from `recuration-canonical-priority.md` that currently
requires real farm time to check by hand.

Update `CLAUDE.md`'s "Key conventions" section: add a `--dry-run` bullet
next to the existing `print_only` bullet, describing it as the way to
exercise step-sequencing/tracking/canonical-resolution logic through the
real CLI without HPC access, pointing at `~/.grit/dry_run/` as the isolated
sandbox and `rm -rf ~/.grit/dry_run` as the reset. Also note explicitly that
only `setup`/`pretext-to-asm`/`blast-contaminants`/`rename-and-orient`/
`microchromosome-combine`/`pretext-to-asm-recurate` support `--dry-run` as
of this task — everything else (`hic-remapping`, `fastga`, `qv`,
`finalize-qc`, `busco-*`, etc.) does not yet, and should raise a clear error
if `--dry-run` is passed to them (confirm this is actually the current
behavior — an unrecognized flag on a command without a dry-run branch
should just proceed as a real run today, which is a footgun; if so, flag
this in your report rather than silently fixing it, since deciding how
unsupported steps should behave under `--dry-run` is a controller-level
call, not yours to make unilaterally).

**Report file:** `.superpowers/sdd/45_dry_run_mode/task-7-report.md`
</content>

---

## Task 8: Fix `grit/core/status.py`'s dry-run blindness (discovered during Task 7)

**Scope:** `grit/core/status.py`, `grit/core/click_cli.py` (only the `status_cmd`
call site that passes arguments into `show_ticket_history`), plus a new or existing
test file covering `status.py` (check for `tests/test_status.py`; if none exists,
create one following this repo's established test conventions). Depends on Tasks 1
and 3 (needs `dry_run_root()`, `ctx.dry_run`, and a bootstrapped dry-run ticket to
test against).

### Problem

Discovered empirically while verifying Task 7's smoke-test scenario: `grit --dry-run
status -t <ticket>` cannot show any dry-run tracker state at all today, even though
`status_cmd` (`click_cli.py:176-186`) already correctly swaps in a dry-run-isolated
`RegistryManager(registry_dir=dry_run_root())` when `ctx.obj.dry_run` is set.

Two separate gaps in `grit/core/status.py`:

1. `show_global_status(registry)` (`status.py:14-39`) and `show_ticket_history(registry,
   ticket_id, user_config)` (`status.py:300-336`) each receive the already-correct
   `registry` object as their first argument, but independently construct
   `RunTracker(workdir)` (lines 39 and 336) WITHOUT passing that `registry` through.
   `RunTracker`'s `registry` constructor param defaults to `None`, and it lazily
   builds its own `RegistryManager()` — the REAL default one — the first time it's
   needed. So even though ticket *lookup* (`registry.all_tickets()`/`find_ticket()`)
   correctly uses the isolated registry, actual step-history/`get_output` reads via
   `RunTracker` silently fall back to the real `~/.grit/grit_registry.json`, which
   (for a dry-run ticket's isolated workdir) has no matching records at all — so
   `history`/`get_output`/the ★ marker all come back empty.
2. `show_ticket_history` additionally builds `ctx = CurationContext.from_ticket(
   ticket_id, user_config, print_only=True)` (`status.py:319`) with no `dry_run=True`
   — for a dry-run/synthetic ticket this either fails outright (attempting a real
   Jira lookup) or, if it somehow succeeds, resolves `ctx.workdir` via the real
   `_derive_workdir(...)` instead of `dry_run_root() / tol_id`, breaking the
   canonical-files table and the ★ marker's `_resolve_canonical_files` call entirely
   for a dry-run ticket.

This was never in any earlier task's declared scope — `status.py` wasn't listed in
Task 1 (which fixed `status_cmd`/`untrack_cmd` in `click_cli.py`, a different file)
or anywhere else. It's a genuine plan gap, not a review miss on an already-scoped
file, and it undermines the core promise of this whole feature (inspecting dry-run
tracker state via `grit status`).

### Fix

1. `show_global_status`: change `RunTracker(workdir)` (line 39) to
   `RunTracker(workdir, registry=registry)`, reusing the already-correct `registry`
   parameter this function already receives. No signature change needed.
2. `show_ticket_history`: add a `dry_run: bool = False` parameter to its signature;
   change `RunTracker(workdir)` (line 336) to `RunTracker(workdir, registry=registry)`
   (same fix as above); change `CurationContext.from_ticket(ticket_id, user_config,
   print_only=True)` (line 319) to also pass `dry_run=dry_run`.
3. `click_cli.py`'s `status_cmd`: pass `dry_run=getattr(ctx.obj, "dry_run", False)`
   into its `show_ticket_history(registry, ticket, user_config)` call (around line
   192) to thread the new parameter through.

Do not touch `show_global_status`'s signature beyond the internal `RunTracker` fix —
it has no `CurationContext`-building step, so it doesn't need a `dry_run` parameter.

### Tests

- `show_global_status`: a test seeding a ticket + a tracked step in an isolated
  `tmp_path` registry (via `RegistryManager(registry_dir=tmp_path)` and
  `RunTracker(workdir, registry=that_registry)`), calling `show_global_status(that_registry)`,
  and asserting the printed output shows the step — proving the fix reads from the
  passed-in registry, not a lazily-constructed default one. (Capture output via
  whatever pattern this repo's existing `status.py`/`console` tests already use —
  check for a `capsys`-based pattern in any existing test touching `console.print`.)
- `show_ticket_history`: a test with `dry_run=True`, a dry-run-bootstrapped ticket
  (reuse Task 3's `setup`/`run_setup` dry-run branch to create one, or construct the
  registry entry directly), asserting the printed step-history output includes a
  step that was tracked via the dry-run-isolated registry — proving both the
  `RunTracker` fix and the `CurationContext.from_ticket(..., dry_run=True)` fix work
  together. Also a negative case: with `dry_run=False`, the same ticket ID (if it
  happened to also exist in a real-registry fixture) does NOT pick up the dry-run
  ticket's data — proving the two stay isolated in both directions.
- `click_cli.py`'s `status_cmd`: extend `tests/test_click_cli.py` (from Task 1) with
  a case confirming `--dry-run status -t <ticket>` reaches `show_ticket_history` with
  `dry_run=True` (e.g. by asserting the printed output reflects dry-run-isolated data,
  reusing the fixture-seeding pattern already established there).

**Report file:** `.superpowers/sdd/45_dry_run_mode/task-8-report.md`
