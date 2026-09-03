# 03 — Testability & Test-Suite Quality

Read-only assessment of `grit` @ `test_and_fix_steps`. Phase 1: diagnosis only.

## Summary

**The suite tests behaviour far more than it tests strings.** 48 of 451 tests
(10.6%) assert on captured shell-command text or LSF option strings; the other
403 assert observable outcomes — files on disk, registry/tracker records,
resolved canonical paths, return values, CLI exit codes, rendered output. The
headline fear in the brief ("8,800 lines flip from asset to obstacle") is *not*
borne out: the string-asserting tests are concentrated in six files and total
roughly 700 lines.

The real refactor obstacle is not the assertions, it is the **patch targets**.
123 tests (27.3%) do `@patch("grit.steps.<x>._run")` or
`@patch("grit.steps.<x>._submit_bsub")` — patching a module-level import in each
of 17 distinct step modules. Introduce an `ExecutionBackend` port and those 123
decorators stop resolving (`AttributeError` at patch time), so 123 tests go red
*even though almost none of their assertions are about LSF*. That is mechanical,
not semantic: mostly a `sed` over patch targets plus ~20 assertions that genuinely
encode LSF syntax.

The genuinely serious problem is a different one: **the execution seam itself is
100% untested.** `_run`'s `subprocess` branch, `_submit_bsub`, `build_bsub_opts`
(57 LOC), `_state_update_epilogue`, and `_check_bjobs` have **zero** direct tests
between them — they are only ever mocked away. There is therefore nothing today
that could seed a backend conformance suite, and no test can distinguish a
correct `bsub` invocation from a malformed one. Combined with only 2 failure-path
`side_effect` tests in 451 and an unlocked read-modify-write registry with zero
concurrency tests, the suite's blind spots are precisely the places where an
HPC-wrapping CLI actually breaks.

## Suite status

```
$ uv run pytest tests/ -q
461 passed in 1.31s
```

Actual result: **461 passed, 0 failed, 1.31s** (461 = 451 test functions
expanded by `parametrize`). `pytest-cov` is **not installed**
(`ModuleNotFoundError: No module named 'pytest_cov'`), and per constraints
nothing was installed, so per-module coverage numbers are unavailable; §Coverage
shape reasons by inspection instead.

The 1.31s wall time is itself a datum: no test executes a subprocess, touches
`~/.grit`, or performs real I/O beyond `tmp_path`. Hermeticity is genuinely good.

## Behaviour vs implementation: the numbers

Counting method: per test function, (a) does it patch `_run`/`_submit_bsub` at a
module import site; (b) does any `assert` in it inspect `call_args`/a `cmd`
variable/`bsub_opts`/`mock_calls`.

| metric | count | share |
|---|---|---|
| test functions | 451 | — |
| collected tests (after parametrize) | 461 | — |
| `assert` statements | 839 | — |
| tests asserting on command/option **strings** | **48** | **10.6%** |
| tests asserting only observable outcomes | 403 | 89.4% |
| tests patching `_run`/`_submit_bsub` (strict, decorator) | **123** | **27.3%** |
| ...including fixture/inline patch styles | ~150 | ~33% |
| distinct `_run`/`_submit_bsub` patch targets | 17 modules | — |
| total exec-patch decorators | 147 | — |
| assertions touching LSF flags (`-M`/`-q`/`-n`/`bsub_opts`/`-Ep`) | 21 | 2.5% of asserts |
| assertions touching `module load`/`module_cmd`/`MODULE_VERSIONS` | 2 | 0.2% of asserts |
| tests with a failure `side_effect` (exception injection) | 2 | 0.4% |
| tests exercising `_run`'s real `subprocess` branch | **0** | **0%** |

Two of those rows deserve emphasis. **`module load` is asserted twice in the
whole suite** — the module→pixi/container half of the planned refactor is
essentially unopposed by tests. And **21 assertions total touch LSF flags** —
the LSF half is much less entrenched than the 8,800-line figure suggests.

### Per-file classification

`tests` = test functions; `exec-patch` = tests patching `_run`/`_submit_bsub`;
`cmd-str` = tests asserting on command/option text.

| file | tests | exec-patch | cmd-str | class |
|---|---:|---:|---:|---|
| test_bsub_ram_override.py | 10 | 9 | 10 | **string-oriented** (100%) |
| test_find_reference.py | 8 | 7 | 4 | **string-oriented** (50%) |
| test_fastga_synteny.py | 5 | 3 | 3 | **string-oriented** (60%) |
| test_rename_and_orient.py | 20 | 15 | 8 | mixed |
| test_microchromosome.py | 14 | 8 | 4 | mixed |
| test_post_curation.py | 61 | 41 | 12 | mixed |
| test_fastga.py | 18 | 7 | 3 | mixed |
| test_cleanup.py | 13 | 3 | 1 | mixed (mostly behaviour) |
| test_pre_curation.py | 30 | 10 | 1 | behaviour (mocks exec, asserts outcomes) |
| test_pretext_to_asm_recurate.py | 16 | 9 | 0 | behaviour |
| test_blast_contaminants.py | 9 | 7 | 0 | behaviour |
| test_sex_matcher.py | 4 | 3 | 0 | behaviour |
| test_post_curation_recurate.py | 4 | 1 | 0 | behaviour |
| test_status.py | 41 | 0 | 0 | behaviour |
| test_context.py | 31 | 0 | 0 | behaviour |
| test_helpers_canonical.py | 26 | 0 | 0 | **behaviour (exemplary)** |
| test_registry.py | 26 | 0 | 0 | behaviour |
| test_run_tracker.py | 23 | 0 | 0 | **behaviour (exemplary)** |
| test_result_parsers.py | 23 | 0 | 0 | behaviour |
| test_helpers.py | 17 | 0 | 0 | behaviour |
| test_super_to_scaffold.py | 12 | 0 | 0 | behaviour |
| test_base_command.py | 11 | 0 | 0 | behaviour |
| test_click_cli.py | 10 | 0 | 0 | behaviour |
| test_paf_top_targets_by_coverage.py | 7 | 0 | 0 | behaviour |
| test_remove_cmd.py | 6 | 0 | 0 | behaviour |
| test_smoke.py | 3 | 0 | 2 | behaviour (shallow) |
| test_output.py / test_validate_files.py | 3 | 0 | 0 | behaviour |
| **TOTAL** | **451** | **123** | **48** | **3 string, 5 mixed, 20 behaviour** |

### Representative examples

String-oriented, LSF-shaped (breaks on a resources abstraction):

- `tests/test_bsub_ram_override.py:22` — `bsub_opts = mock_bsub.call_args[0][1]; assert "-M 24000" in bsub_opts`. All 10 tests in the file are this shape (`:22`, `:37`, `:53`, `:70`, `:84`, `:95`, `:112`, and three more). The *intent* (a `bsub_ram` override reaches the scheduler) is real behaviour; the *expression* is LSF syntax.
- `tests/test_fastga_synteny.py:40` — `assert f"-min-len {DEFAULT_MIN_ALIGN_LEN}" in cmd`.

String-oriented because production offers no other seam:

- `tests/test_find_reference.py:24-30` — `assert "ln -s" not in cmd`, `assert "cp " not in cmd`, `assert "gunzip" not in cmd`, `assert f"reheader {local_ref}" in cmd`.
- `tests/test_find_reference.py:54-56` — `assert f"gunzip -c {local_ref} > {decompressed}" in cmd`, `assert f"rm {decompressed}" in cmd`.
  `find_closest_reference` composes a `&&`-chained shell pipeline and returns nothing; the string *is* the only observable. This is a production design defect surfaced by the tests, not a test defect.

Mixed — a shell-string assertion sitting next to real behaviour in the same file:

- `tests/test_post_curation.py:138-141` — `calls = [str(c) for c in mock_run.call_args_list]; assert any("pretext-to-asm" in c ...)`
- `tests/test_post_curation.py:474-476` — `assert "curationpretext.sh" in cmd`, `assert str(hap1_fa) in cmd`
- `tests/test_post_curation.py:497` — `assert "--teloseq TTAGG" in cmd`; `:519` — `assert "--email curator@sanger.ac.uk" in cmd`
- ...but the same file's `:146` and `:155` assert `pytest.raises(FileNotFoundError, match="AGP file")` / `match="original.fa"`, and `:810-860` assert tracker output records. Genuinely mixed.

Behaviour-oriented exemplars (these are the suite's real asset):

- `tests/test_helpers_canonical.py:24-38` — builds a real `RegistryManager` + `RunTracker` under `tmp_path`, writes real files into real run dirs, calls `tracker.finish(...)` with real output dicts, then asserts `find_canonical_fa(mock_ctx, "hap1") == pta_fa`. 26 tests of this shape covering the mtime-pool priority chain, per-hap independence, untrack fallback, and re-run-wins ordering. **Zero mocks.** Backend-agnostic by construction.
- `tests/test_run_tracker.py` — 23 tests, all against a real registry; covers `untracked` semantics (`:172`, `:178`, `:189`), `untrack`/`undo` (`:145`, `:200`), `verify_outputs` (`:115-137`).
- `tests/test_status.py:383-425` — a real end-to-end recovery test: seeds a `started` record with a `job_id`, mocks only `_check_bjobs` to report `DONE`, runs `show_ticket_history`, then asserts the *tracker history* ends `success` and the scp tip appears. This is the single best-designed test in the suite and the closest thing to a contract test.
- `tests/test_registry.py` — 26 tests on real JSON registry state.
- `tests/test_result_parsers.py` — 23 tests parsing real fixture files (`tests/fixtures/aEleIno2.qv`, `drLytPort2.log`, …).

**Verdict: this is a behaviour-oriented suite with a string-oriented fringe and a
badly-placed mocking boundary.** The `mock_ctx`-plus-real-tmp_path-plus-real-registry
pattern is the dominant idiom and it is the right one.

## Refactor-resistance estimate

Scenario: `_submit_bsub` / `_run` replaced by an `ExecutionBackend` port with
`submit(spec) -> JobHandle`, injected on `ctx`.

| bucket | tests | nature of breakage | cost |
|---|---:|---|---|
| Patch-target only (`@patch("...._run")` no longer resolves; assertions are about outcomes) | **~81** | purely cosmetic | mechanical: retarget to a fake backend fixture. ~1 day for the whole suite if a `FakeBackend` fixture is written first |
| Patch target **and** command-string assertion (`assert "x.sh" in cmd`) | **~38** | cosmetic-but-fiddly: the string moves into `spec.command` | each needs the assertion rewritten against the spec object. ~2–4 h |
| LSF-semantic assertions (`-M`, `-q`, `-n`, `-Ep`) | **~21 assertions across 10–12 tests** | **meaningful** — these encode "memory limit is expressed as an LSF `-M` flag". Under a port they must become `spec.memory_mb == 24000`, i.e. the *concept* survives and the *encoding* dies | genuine rewrite, but small and welcome: it converts LSF-specific tests into backend-neutral ones |
| Behaviour tests untouched | **328** | none | zero |
| `module load` swap (pixi/containers) | **2 assertions** | none worth naming | ~0 |

Worst-offending files, in order:

1. **`tests/test_bsub_ram_override.py`** (10/10 tests, 157 lines) — the only file that is *entirely* about LSF flag syntax. Every test dies; every test's intent survives. This file is the clearest candidate to become the seed of a backend contract test ("a memory override reaches the backend's resource spec").
2. **`tests/test_post_curation.py`** (41 exec-patched tests of 61, 1,693 lines) — largest absolute breakage. 12 tests carry command-string assertions; the other 29 break on the patch target alone.
3. **`tests/test_rename_and_orient.py`** (15 exec-patched of 20, 529 lines; also 17 `patch("...glob.glob")` and 20 `patch("...find_canonical_fa")`) — the most heavily mocked step file in the suite; three separate seams patched per test.
4. **`tests/test_find_reference.py`** (7/8) — the hardest to migrate, because these tests will still have nothing but a shell string to assert on until `find_closest_reference` grows a return value. Migration is blocked on a production change, not a test change.
5. **`tests/test_microchromosome.py`** (8/14) and **`tests/test_fastga_synteny.py`** (3/5) — small, same pattern.

**Bottom line: ~123 tests (27%) go red on the port; ~102 of those (23% of the
suite) are cosmetic retargeting; ~21 assertions represent real, and desirable,
semantic change. 73% of the suite is indifferent to the refactor.** The suite is
a mild speed bump, not a wall.

## Findings

---

**TEST-01** | severity: **critical** | confidence: **confirmed**
| `grit/utils/helpers.py:42-135` (0 covering tests anywhere in `tests/`)
| claim: The entire execution seam — `_run`'s `subprocess` branch, `_submit_bsub`, `build_bsub_opts` (57 LOC), `_state_update_epilogue`, `_check_bjobs` — has zero direct tests; all five are only ever mocked away.
| failure scenario: **Bug that slips through:** `_submit_bsub` builds `f'bsub{epilogue_part} {bsub_opts} "{inner_cmd}"'` — one outer quote pair with an `-Ep '...'` fragment interpolated inside. Any `inner_cmd` containing a double quote, or an epilogue path containing a single quote, silently produces a mis-tokenised `bsub` line that LSF rejects or, worse, truncates. Nothing in 461 tests can detect this: `grep -c` gives 0 tests for `_submit_bsub` itself, 0 for `build_bsub_opts`, 0 for `_state_update_epilogue`, 0 for `_check_bjobs`. `_run`'s `subprocess.run(..., check=True)` branch executes **zero times** across the whole suite (confirmed: no test patches `subprocess` in `helpers`, and every step test patches `_run` above it). This is also exactly the code a Phase-2 port must replace, so there is no baseline to refactor against.
| effort: **M** | blast radius: **cross-module**
| debt quadrant: **inadvertent-reckless** | open-source impact: **blocker**

---

**TEST-02** | severity: **critical** | confidence: **confirmed**
| `tests/*` — 123 tests across 14 files patch `_run`/`_submit_bsub` at 17 distinct module import sites; 147 patch decorators total (e.g. `tests/test_post_curation.py:123`, `tests/test_rename_and_orient.py:18`, `tests/test_bsub_ram_override.py:12`)
| claim: The mocking boundary is the *module-level import of a private helper in each step*, not an injected collaborator, so the port's seam and the tests' seam are the same line of code in 17 places.
| failure scenario: **Refactor obstructed:** replacing `_submit_bsub` with `ctx.executor.submit(spec)` deletes the name each of those 147 decorators targets. `mock.patch` raises `AttributeError: <module> does not have the attribute '_submit_bsub'` at *call* time, so all 123 tests fail simultaneously with an error that says nothing about behaviour. Cost: the refactor cannot be landed incrementally — there is no way to add a port for one step and keep the suite green, because `@patch` string targets give no compile-time coupling and no shared fixture to update once. Concretely, ~1 day of mechanical retargeting that must land in the same commit as the port, making the port commit unreviewable.
| effort: **L** | blast radius: **cross-module**
| debt quadrant: **inadvertent-prudent** (the idiom was the obvious one before a port was contemplated) | open-source impact: **friction**

---

**TEST-03** | severity: **critical** | confidence: **confirmed**
| `grit/core/registry.py:161-169` (`append_step`), `:299-312` (`_load`/`_save`); `tests/test_registry.py` (26 tests, none concurrent)
| claim: The registry does unlocked read-modify-write (`_load()` → mutate → `_save()`), and no test in the suite exercises concurrent access.
| failure scenario: **Bug that slips through:** `_state_update_epilogue` (`grit/utils/helpers.py:89-105`) makes every `bsub` job run `grit _state-update` on a compute node when it finishes. Six steps use it, and a hap1/hap2 ticket submits two jobs per step. When two epilogues fire within the same read-modify-write window, both `_load()` the same JSON, each appends its own step record, and the second `os.replace` wins — the first job's completion record is **silently lost forever**, leaving a run stranded as `started` with no recovery path but `grit untrack` (the exact failure mode CLAUDE.md warns about for synchronous steps). `_save` is atomic per-write, which makes this look safe and is why it has never been questioned. Zero tests can see it: there is no test that opens two `RegistryManager` instances on one path.
| effort: **M** | blast radius: **cross-module**
| debt quadrant: **inadvertent-reckless** | open-source impact: **friction**

---

**TEST-04** | severity: **major** | confidence: **confirmed**
| `grit/utils/helpers.py:108-135` (`_check_bjobs`); `grit/core/registry.py:242-297` (`_refresh_pending_jobs`, `_resolve_gone_job`) — no test references either registry function
| claim: The job-status recovery path is untested except through one mocked-`_check_bjobs` integration test, and `_check_bjobs`'s own `bjobs` output parsing is untested entirely.
| failure scenario: **Bug that slips through:** `_check_bjobs` initialises every job to `"gone"` and only overwrites it from `line.split()[2]` when a line has ≥3 fields, inside a bare `except Exception: pass`. If `bjobs` output format shifts, or LSF is transiently unreachable, every pending job silently reads `"gone"` → `_resolve_gone_job` → `collect_outputs` on a run dir the job has not finished writing → `tracker.finish(step, run_dir, "failed")`. A curator's *still-running* 12-hour BUSCO job is marked failed and, because canonical resolution walks tracked successes, the canonical FASTA silently rolls back to an older step. `grep` confirms `_refresh_pending_jobs` and `_resolve_gone_job` appear in zero test files; only `tests/test_status.py:410` touches this area, and it mocks `_check_bjobs` to return a hand-written `{"685359": "DONE"}` — the one branch (`DONE`) that `_refresh_pending_jobs` does not even handle.
| effort: **S** (both are pure functions over injectable strings) | blast radius: **module**
| debt quadrant: **inadvertent-reckless** | open-source impact: **friction**

---

**TEST-05** | severity: **major** | confidence: **confirmed**
| `grit/utils/helpers.py:42-59` (`_run` with `check=True`); only 2 failure-injecting tests in 451 (`tests/test_fastga.py:261`, `tests/test_cleanup.py:258`)
| claim: Mocking `_run` removes `subprocess.run(check=True)`, so every mock unconditionally signals success and no test can distinguish "command ran" from "command succeeded".
| failure scenario: **Bug that slips through:** `subprocess.CalledProcessError` is caught in exactly **one** place in all of `grit/` (`grit/steps/post_curation/post_processing.py:69`). Everywhere else a failing external tool raises an uncaught `CalledProcessError`, so a curator sees a Python traceback and — critically — the step's `tracker.finish(..., "failed")` never runs, stranding the record. Of 123 exec-patched tests, exactly 1 (`test_fastga.py:261`) injects a failure. So a step that forgets its try/except around post-`start()` work (the failure mode CLAUDE.md explicitly documents for `fastga-stats`) ships green: the happy-path test passes, and no test asserts that a non-zero exit produces a `failed` record. 16 `finish(..., "failed")` call sites exist in production; 14 `"failed"` assertions exist in tests, and most of those are `RunTracker` unit tests, not step failure paths.
| effort: **M** | blast radius: **cross-module**
| debt quadrant: **inadvertent-reckless** | open-source impact: **friction**

---

**TEST-06** | severity: **major** | confidence: **confirmed**
| `grit/steps/optional/blast_contaminants.py:144-150`; no test in `tests/` mentions `target_phylum`, a lineage string, or `Unknown`
| claim: `print_only` is used as a de-facto test mode in a way that makes output-parsing logic structurally unreachable by tests.
| failure scenario: **Bug that slips through:** `our_lineage = _run(lineage_cmd, ctx.print_only).strip()` then `target_phylum = lineage_parts[3] if len(lineage_parts) > 3 else "Unknown"`. Under `print_only=True`, `_run` returns `""` → `lineage_parts == [""]` → `target_phylum == "Unknown"`, and the step happily proceeds to build a BLAST filter against phylum "Unknown". Under a mocked `_run`, the same. `grep -rn "Eukaryota\|target_phylum\|Unknown" tests/*.py` returns **nothing** — no test ever feeds a realistic `Eukaryota; Metazoa; ...; Chordata; ...` string. So an off-by-one in the index-3 phylum extraction, or a change in the lineage script's output format, makes every real decontamination run filter against the wrong (or no) phylum, silently, with 461 tests green. The same shape recurs at `grit/steps/post_curation/hic_remapping.py:119-123`, where the `re.search(r"Job <(\d+)>", output)` job-ID capture is only ever fed `""` (`mock_run.return_value = ""`, 28 occurrences) — so `record_job` is never actually reached in any hic_remapping test, and a regex regression there would silently disable bjobs recovery for that step.
| effort: **S** | blast radius: **module**
| debt quadrant: **inadvertent-reckless** | open-source impact: **friction**

---

**TEST-07** | severity: **major** | confidence: **confirmed**
| `grit/utils/helpers.py:477-562` (`find_canonical_haplotigs`, 86 LOC with 2 nested helpers); `tests/test_helpers_canonical.py` references it **0 times**
| claim: Of the three canonical-resolution entry points CLAUDE.md flags as requiring care, one has no direct tests at all and is only ever mocked out in its nine consumers.
| failure scenario: **Bug that slips through:** `find_canonical_fa` has 26 direct behaviour tests and `find_canonical_chr_list` has 6, all in `tests/test_helpers_canonical.py`. `find_canonical_haplotigs` has none — it appears in tests only as `@patch("grit.steps.post_curation.finalize_qc.find_canonical_haplotigs")` (9 times in `test_post_curation.py`, at `:932`, `:983`, `:1052`, `:1091`, `:1136`, `:1190`, `:1233`, `:1276`, `:1319`) and once in `test_pretext_to_asm_recurate.py:159`. So its `_hap_specific` nested-search branch and its mtime-pool ordering are unverified: a haplotigs file from a *stale* run being preferred over a fresh one would send the wrong haplotigs into `finalize-qc` and thence into the curated release directory — an irreversible, curator-visible data error — while every test passes, because every test that touches the code mocks its return value. `_step_output`'s re-globbing branch (`helpers.py:364-400`), which CLAUDE.md identifies as the guard against canonical moving backwards, is likewise never called directly; it is exercised only incidentally via `tests/test_helpers_canonical.py:460`.
| effort: **S** | blast radius: **module**
| debt quadrant: **inadvertent-prudent** | open-source impact: **friction**

---

**TEST-08** | severity: **major** | confidence: **confirmed**
| `grit/utils/helpers.py:89-105` (`_state_update_epilogue`); `grit/core/click_cli.py:210-255` (`_state-update` command) — `grep -rn "state_update\|_state-update" tests/` returns **zero hits**
| claim: The mechanism CLAUDE.md documents as the *only* way grit learns that a fire-and-forget `bsub` job truly completed has no test of any kind.
| failure scenario: **Bug that slips through:** the epilogue is a shell string embedded in a `bsub -Ep '...'` argument: `"{grit_bin} _state-update --workdir {workdir} --step {step} --run-dir {run_dir} --status $([ $LSB_JOBEXIT_STAT -eq 0 ] && echo success || echo failed){untracked_flag}"`. It carries a `$(...)` substitution and `&&`/`||` inside single quotes inside `_submit_bsub`'s double quotes. Nothing verifies that (a) the quoting survives, (b) `--untracked` is propagated when `ctx.untracked` is set — the precise bug CLAUDE.md says was already fixed once in `TODO/tiny.md`, where a missing `untracked=` let a finish record overwrite the untracked marker and make a run canonical on completion. That regression can recur today and the suite stays green. Additionally: 6 step modules pass `epilogue_cmd`, and no test asserts *any* of them do, so a new step that omits it (the documented convention) ships silently and its runs never complete in the tracker.
| effort: **S** (the function is pure string-building; the CLI command is invocable via `CliRunner`) | blast radius: **cross-module**
| debt quadrant: **inadvertent-reckless** | open-source impact: **friction**

---

**TEST-09** | severity: **major** | confidence: **confirmed**
| `tests/` — no shared execution fixture; 9 near-duplicate local tracker helpers; 45.7% of non-trivial test lines are exact duplicates of another line
| claim: There is no contract/conformance test and no shared harness that a Phase-2 backend adapter could be run against; the suite's structure actively resists one.
| failure scenario: **Refactor obstructed:** Phase 2 needs one suite that any `ExecutionBackend` (LSF, local, Slurm) must pass. Nothing today can seed it, because *no test ever calls an executor* — the executor is the thing that is always mocked (TEST-01). What exists instead is 17 independently-patched module-level seams and 9 copy-pasted local fixtures doing the same job under three different names: `_attach_tracker` (`tests/test_blast_contaminants.py:15`, `tests/test_fastga.py:21`, `tests/test_fastga_synteny.py:13`, `tests/test_rename_and_orient.py:264`, `tests/test_microchromosome.py:14`, `tests/test_super_to_scaffold.py:18`), `_make_tracker` (`tests/test_helpers_canonical.py:10`, `tests/test_result_parsers.py:134`), `_tracker` (`tests/test_pretext_to_asm_recurate.py:17`), plus duplicated `_write` (`test_helpers_canonical.py:18`, `test_pretext_to_asm_recurate.py:24`) and `_seed_ticket` (`test_click_cli.py:42`, `test_remove_cmd.py:26`). `tests/conftest.py` offers `mock_ctx`/`mock_ctx_primary`/`fake_workdir` but no tracker-attach and no fake executor. Measured duplication: 2,442 of 5,343 non-trivial test lines (45.7%) are exact repeats — `mock_ctx.workdir = tmp_path` ×83, `mock_ctx.tol_id = "sDipInt39"` ×76, `mock_ctx.hap1_prefix = "hap1"` ×58, `from grit.core.run_tracker import RunTracker` ×44 (a local import inside test bodies, not at module top). Cost: writing the conformance suite is greenfield work, and every one of the 123 exec-patched tests must be migrated to it by hand rather than by changing one fixture.
| effort: **L** | blast radius: **cross-module**
| debt quadrant: **inadvertent-prudent** | open-source impact: **blocker**

---

**TEST-10** | severity: **major** | confidence: **confirmed**
| `tests/test_post_curation.py` (1,693 lines, 61 tests, 5 unrelated step modules); `tests/test_status.py` (956 lines, 41 tests)
| claim: Test files are organised by source directory rather than by unit, so the two largest files are grab-bags whose size is driven by copy-paste setup rather than by behaviour count.
| failure scenario: **Refactor obstructed / maintenance cost:** `test_post_curation.py` covers `collect_outputs`, `pretext_to_asm`, `haplotig_files`, `hic_remapping`, `qv`, `validate_curated_files`, `finalize_qc`, and `post_processing` in one file. The `hic_remapping` block alone (`:454-780`) is 11 tests × ~22 lines of near-identical `mock_ctx.*` assignment, differing by one field each (`:481` teloseq, `:502` email, `:524` no-email, `:631` hic-dir, `:654` ont-dir, `:677` hifi-dir) — pure `parametrize` material written out longhand. The `finalize_qc` block (`:928-1400`) repeats a 6-decorator stack (`qv._run`, `finalize_qc._run`, `finalize_qc.glob.glob`, and all three `find_canonical_*`) nine times verbatim. Concretely: **adding a 22nd step today means copy-pasting ~300-400 lines**, and it means a change to any one of the six mocked seams requires editing nine identical decorator stacks in one file. This is also what makes the TEST-02 migration a full day rather than an afternoon.
| effort: **M** | blast radius: **file**
| debt quadrant: **inadvertent-prudent** | open-source impact: **friction**

---

**TEST-11** | severity: **minor** | confidence: **confirmed**
| `.github/workflows/ci.yml:1-30`; `pyproject.toml:9` (`requires-python = ">=3.10"`); local interpreter is 3.13.9
| claim: CI runs one unpinned Python against a declared `>=3.10` floor, has no coverage gate, and never runs `tests/local_smoke_test.sh`.
| failure scenario: **Bug that slips through:** `astral-sh/setup-uv` with no `python-version` resolves whatever `uv` prefers (3.13 today), so nothing verifies the 3.10 floor the package advertises. A reviewer scan found no 3.11+ syntax in `grit/` today (`match`, `except*`, `Self`, `datetime.UTC`, `tomllib`, `StrEnum` all absent), so this is latent rather than live — but the first `X | Y` in a runtime `isinstance`, or the first `tomllib` import, will ship a package that fails to import on the declared minimum with green CI. Separately, `tests/local_smoke_test.sh` (269 lines) is the *only* artifact that chains steps end-to-end and, per its own header, is "the main thing to run after touching `find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs`, any step's dry-run branch, or the flat mtime pool itself" — precisely because unit tests are "scoped to one function at a time" and miss canonical-FASTA collisions. Its `--dry-run` section is explicitly laptop-runnable and needs no farm access, yet CI does not run it, so the one check the project itself names as authoritative for canonical resolution runs only when a human remembers.
| effort: **S** | blast radius: **cross-module**
| debt quadrant: **deliberate-prudent** (single-version CI is a reasonable early choice) → drifting to **inadvertent-reckless** for the un-run smoke test | open-source impact: **friction**

---

**TEST-12** | severity: **minor** | confidence: **confirmed**
| `tests/test_smoke.py:36-49` (8 of ~38 registered CLI commands) vs `grit/core/click_cli.py` (30 `add_command` + 8 `@cli.command`)
| claim: The hermetic CLI smoke test covers 8 commands in `--print-only` mode; the remaining ~30 are covered only by per-step unit tests with the executor mocked.
| failure scenario: **Bug that slips through:** the docstring is candid that `add-gap-track`, `add-telo-track`, `fastga`, `blast-contaminants`, `hic-remapping`, `rename-and-orient`, `pretext-to-asm-recurate`, `post-curation-recurate` and `sex-matcher` are excluded because they check for real farm output even under `--print-only`, and are "covered by `tests/local_smoke_test.sh` run manually on the farm" — which CI does not run (TEST-11). So for ~9 commands the wiring from `GlobalState` → `build_context()` → step function is verified by *nothing automated*: a `KeyError` in an f-string or a renamed `ctx` field in any of them reaches a curator, which is exactly the class of regression `test_smoke.py`'s own docstring says it exists to catch. Two of the three remaining smoke tests are `--help` exit-code checks (`:74-78`).
| effort: **S** | blast radius: **module**
| debt quadrant: **deliberate-prudent** (honestly documented, real constraint) | open-source impact: **friction**

---

**TEST-13** | severity: **minor** | confidence: **plausible**
| `tests/` — 60 occurrences of `dry_run=True`/`dry_run = True` vs 21 of `print_only=True`; e.g. `tests/test_post_curation.py:178`, `:210`, `:244`, `:701`, `:727`, `:752`
| claim: `--dry-run` branches are becoming the primary tested path for several steps, which means the real command-construction path in those steps is covered less than the raw test count suggests.
| failure scenario: **Bug that slips through:** `dry_run` is now the most common mode in the suite (60 sites), and a dry-run branch returns *before* the real command is built — e.g. `test_run_pretext_to_asm_dry_run_writes_fake_fasta_with_scaffold_headers` (`:178`) and the three `hic_remapping` dry-run tests (`:701`, `:727`, `:752`) assert on `write_fake_outputs` placeholders, not on anything the real path produces. Where a step's *only* hap2 or single-hap coverage is a dry-run test, a divergence between the dry-run branch and the real branch (a hap2 output fabricated in dry-run but skipped for real, or vice versa — the `is_single_hap` gating CLAUDE.md flags) is invisible. Marked *plausible* rather than confirmed because several steps do have both branches tested side by side (`:210` dry-run single-hap alongside `:155` real-path single-hap), so the risk is per-step and would need a per-step audit to quantify.
| effort: **M** | blast radius: **cross-module**
| debt quadrant: **deliberate-prudent** (the dry-run harness is a genuine asset — see below) | open-source impact: **none**

---

### Findings by severity

| severity | count | IDs |
|---|---:|---|
| critical | 3 | TEST-01, TEST-02, TEST-03 |
| major | 7 | TEST-04 … TEST-10 |
| minor | 3 | TEST-11, TEST-12, TEST-13 |

## What is done well

Being honest in both directions, as asked: **this is a better-than-average test
suite for a CLI that wraps a scheduler it cannot run in CI**, and several
specific things are done properly.

1. **The suite is genuinely behaviour-oriented.** 89.4% of tests assert on
   observable outcomes. The brief's worst case — a suite of `assert "bsub" in
   cmd` — is not what is here. 21 LSF-flag assertions and 2 `module load`
   assertions in 839 total is a small, contained surface.

2. **`tests/test_helpers_canonical.py` is model work.** 26 tests, zero mocks,
   real `RegistryManager` + `RunTracker` + real files under `tmp_path`,
   asserting `find_canonical_fa(ctx, hap) == expected_path`. Canonical
   resolution is the highest-consequence logic in the codebase (a wrong answer
   silently ships the wrong assembly), it has the most branches, and it is
   tested at exactly the right altitude — against the *contract*, not the
   implementation. This file survives the ports refactor untouched. So do
   `tests/test_run_tracker.py`, `tests/test_registry.py` and
   `tests/test_result_parsers.py` (the last parsing real fixture files:
   `aEleIno2.qv`, `drLytPort2.log`, `bAraMil1.hap1.1.primary.curated.agp`).

3. **`tests/test_status.py:383-425` is a real integration test and the best
   available seed for contract testing.** It mocks exactly one thing
   (`_check_bjobs`, the LSF query), drives `show_ticket_history` end to end, and
   asserts on the resulting *tracker history*. That shape — mock only the
   scheduler boundary, assert on persisted state — is precisely the shape a
   backend conformance suite needs, and it already exists once. It is a
   demonstration that the team knows how to write these; it just was not
   generalised.

4. **Hermeticity and speed.** 461 tests in 1.31s, no network, no `~/.grit`, no
   subprocess, `tmp_path` throughout, `monkeypatch` on `registry._DEFAULT_DIR`
   where the real registry would otherwise be touched. A contributor with no
   farm access can run the whole suite. That is a real precondition for
   open-sourcing this, and it was clearly deliberate.

5. **The `--dry-run` harness is an unusual and valuable asset.** Isolating the
   registry, workdir and curated-release dir under `~/.grit/dry_run/` and having
   each step write `write_fake_outputs()` placeholders gives a way to exercise
   step *sequencing* and canonical resolution end to end with no HPC — the
   category of bug unit tests structurally cannot see. `write_fake_outputs` is
   itself round-trip tested against `collect_outputs` for five steps
   (`tests/test_helpers.py:104-235`), which keeps the fake outputs honest. The
   gap is not the design; it is that the thing which drives it end to end
   (`local_smoke_test.sh`) does not run in CI (TEST-11).

6. **Failure-mode documentation is unusually good.** `tests/test_smoke.py`'s and
   `tests/local_smoke_test.sh`'s headers say exactly what they do *not* cover
   and why. Several tests carry docstrings explaining the production subtlety
   they pin (`test_status.py:387-390` on why `hic_remapping` has no epilogue;
   `test_post_curation.py:1647` on `post_processing`'s `subprocess.run`). Debt
   that is written down is cheaper than debt that is not, and it is why several
   findings above are classed *prudent* rather than *reckless*.

**What the 1:1 ratio buys, plainly:** confidence in the pure-logic core — context
derivation, YAML→assembly-type detection, registry/tracker state machine,
canonical resolution, result parsing. That is roughly 200 of 451 tests and it is
where the irreversible curator-visible errors live. What it does not buy is any
confidence about the boundary: whether the command grit builds is a command LSF
will accept, whether a failing command is recorded as failed, or whether two
concurrent job epilogues can both be recorded. The suite's shape is
"well-tested core, unexamined edges" — which is the right way round, but the
edges are where Phase 2 lives.
