# Phase 1 — Architecture & Modularity Assessment

Scope: `grit/` at branch `test_and_fix_steps` (~9,500 LOC prod, ~8,800 LOC tests).
Method: full AST import graph, grep verification of every invariant CLAUDE.md
claims, per-step boilerplate census, targeted reads of the seven hotspots.
Read-only; no source touched.

## Summary

The intended architecture in CLAUDE.md is a real and mostly coherent design —
`CurationContext` as a single injected value object, one `_run()` chokepoint,
one `MODULE_VERSIONS` table, a tracker whose "success" means verified on-disk
outputs. Where the code follows it, it is genuinely good. But the layer names
(`core` / `steps` / `utils` / `config`) are nominal, not real: every one of the
four packages imports from at least one other, and the graph is only acyclic at
*runtime* because 28 step modules defer `from grit.core.click_cli import
build_context` into their command bodies and `utils/helpers.py` defers an import
of a step module into a function. `helpers.py` is a genuine god-module with at
least seven unrelated responsibilities (process/LSF execution, canonical-file
resolution, filesystem discovery, output-spec registry, dry-run fixture writing,
CLI tip string rendering, ctx predicates) and it sits at the centre of the
dependency knot. The step contract has drifted badly: of 21 steps, four are
allowlisted for `--dry-run` while containing no `dry_run` code at all, one is
unreachable from the CLI, tracked steps disagree about whether outputs go in
`run_dir` or `workdir`, and `_OUTPUT_SPECS` is described in *five* separate
places that must be kept in sync by hand. The single most expensive structural
problem is that "reconcile a finished LSF job with its outputs" is implemented
four independent times, with four different success criteria, so the same run
can be reported differently depending on which path fires. `core/status.py` is
not a display module: its 286-line `show_ticket_history` builds a
`CurationContext` (hitting Jira), polls `bjobs`, and *writes* to the registry —
a read command that mutates state. For the stated goal of running outside
Sanger, the blocker is not size but hardcoded infrastructure: absolute
`/software`, `/nfs`, `/lustre` paths (including two individuals' home
directories) as module constants in step files, LSF assumed in 22 of 46 files
including `core`, and `sys.path`-injected `GritJiraIssue` as the only way to get
a ticket.

## Import graph

Package level (edges = at least one import, deferred or not):

```
grit          -> core, utils
grit.config   -> (none)
grit.core     -> config, steps, utils
grit.steps    -> core, utils
grit.utils    -> core, steps
```

Every arrow that would make this a layered system is violated. There is no
package that only depends "downward". Notably `utils -> steps` and
`core -> steps` both exist.

Key module-level edges:

- `core/click_cli.py` imports 22 step modules at module scope (lines 129-165) to
  register Click commands. This is a deliberate, defensible plugin-registration
  edge.
- 28 call sites in 21 step modules import `build_context` **from
  `core/click_cli.py`** inside their command function bodies
  (e.g. `grit/steps/pre_curation/setup.py:410`,
  `grit/steps/optional/fastga.py:259,274`). This closes the cycle
  `click_cli -> step -> click_cli` for **every** step.
- `grit/utils/helpers.py:384` imports
  `grit.steps.post_curation.pretext_to_asm_recurate` inside `_step_output()`,
  and `helpers.py:872 _get_step_specs()` lazily imports 12 further step modules
  by hardcoded dotted-path string. Cycle:
  `helpers -> steps.* -> click_cli -> helpers`.
- `core/context.py:164` imports `core/registry.py` and `core/run_tracker.py`
  inside `from_yaml`; `core/registry.py:244` imports `helpers`; `helpers`
  imports `context` at module scope (line 14). Cycle:
  `context -> registry -> helpers -> context`.
- `core/registry.py:307 (run_tracker._registry)` <-> `core/run_tracker.py` —
  a mutual pair broken by a lazy property.
- `core/status.py:444` imports `print_curation_summary` from
  `grit/steps/pre_curation/setup.py` — core reaching into a step for a
  presentation helper.
- `grit/steps/__init__.py` eagerly imports **every** step module, so any
  `import grit.steps.x` style access through the package root drags in the
  whole tree (and with it click, rich_click, and the cycles above).

Distinct elementary cycles found: 3 structural families —
(a) `click_cli <-> steps.*` (21 instances), (b) `helpers <-> steps.*`,
(c) `context <-> registry <-> helpers` and `registry <-> run_tracker`.
Every one is survivable today only because the back-edge is a
function-local import. There is no import-cycle test guarding this.

## Findings

**ARCH-01** | severity: critical | confidence: confirmed
| `grit/core/click_cli.py:230-249`, `grit/core/registry.py:241-296`, `grit/core/status.py:518-541`, `grit/steps/pre_curation/sex_matcher.py:99-128`
| claim: "Reconcile a finished LSF job with its real outputs" is implemented four independent times with four different success criteria and no shared code.
| failure scenario: a `rename_and_orient` bsub job finishes but its `-Ep` epilogue never fires (node reboot, `grit` not on the compute node's `$PATH`). Path 2 (`registry._resolve_gone_job`) marks it `success` iff `collect_outputs` finds files; path 3 (`status.show_ticket_history`) marks it `success` only if `tracker.verify_outputs()` returns `ok`/`no_files`, and `rename_and_orient` has **no** `STEP_MANIFESTS` entry so `verify_outputs` returns `not_tracked` -> the row is stuck on `done (check)` forever. Same run, same disk state, two different reported statuses depending on whether `grit status -t` or `grit status` ran first.
| effort: L | blast radius: cross-module
| debt quadrant: inadvertent-reckless
| open-source impact: friction

**ARCH-02** | severity: critical | confidence: confirmed
| `grit/utils/helpers.py` (937 lines, 50 commits)
| claim: `helpers.py` is a god-module holding at least seven unrelated responsibilities, and it is simultaneously the most-changed file and the hub of the dependency knot.
| failure scenario: the seams are: (1) process + LSF execution — `_run:42`, `_submit_bsub:62`, `_state_update_epilogue:89`, `_check_bjobs:108`, `build_bsub_opts:137`; (2) CLI tip *rendering* — `build_scp_tip:194`, `build_less_tip:234`; (3) canonical-assembly resolution business logic — `find_curated_fa:301`, `_recurate_step_name:357`, `_step_output:364`, `_latest_tracked_output:401`, `find_canonical_fa:425`, `find_canonical_haplotigs:477`, `find_canonical_chr_list:563`, `inputs_newer_than_curated_fa:254`; (4) filesystem discovery — `find_hap_agp:639`, `find_latest_dir:678`, `find_reheadered_reference:721`, `_find_pretext_map_in_workdir:749`, `_sort_by_mtime:913`, `_pick_highest_version:918`; (5) the step output-spec registry — `_get_step_specs:872`, `collect_outputs:798`; (6) dry-run fixture writing — `write_fake_outputs:831`; (7) ctx predicates + process exit — `is_single_hap:20`, `require_workdir:25`. Maintenance cost: any change to LSF submission and any change to canonical resolution touch the same file, so the 50 commits collide; and because it is imported at module scope by nearly everything while itself importing `context` and (lazily) `steps`, it cannot be split without first breaking the cycles.
| effort: L | blast radius: cross-module
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**ARCH-03** | severity: major | confidence: confirmed
| `grit/core/manifests.py:13` + per-step `_OUTPUT_SPECS` + `grit/utils/helpers.py:872` + `grit/core/status.py:337` + `grit/core/cleanup.py:24` + `grit/core/base_command.py:11`
| claim: each step's identity is described by six hand-maintained parallel registries with no single source of truth and no consistency check.
| failure scenario: the registries are `STEP_MANIFESTS` (19 keys, for `verify_outputs`), `STEP_TO_STATUS` (17 keys, for Jira status), `_get_step_specs`'s dotted-path map (14 keys, for output recording), `_SCP_TIP_STEPS` (6), `_STEPS_KEEP_LATEST` (7, for cleanup), `_DRY_RUN_SUPPORTED_COMMANDS` (24 command names). They already disagree: `rename_and_orient`, `rename_and_orient_hap2`, `blast_contaminants`, `super_to_scaffold`, `busco_curated`, `post_processing` have `_OUTPUT_SPECS` and/or tracking but **no** `STEP_MANIFESTS` entry, so `verify_outputs` returns `not_tracked` and the recovery path in ARCH-01 silently gives up. `STEP_TO_STATUS` contains `agp_copied`, which is not a step at all. Adding a 22nd step means editing six lists in five files and no test fails if you miss one.
| effort: M | blast radius: cross-module
| debt quadrant: inadvertent-reckless
| open-source impact: friction

**ARCH-04** | severity: major | confidence: confirmed
| `grit/core/status.py:395-680` (`show_ticket_history`, 286 lines)
| claim: the top hotspot is not a display module — one function performs Jira I/O, LSF polling, registry *writes*, record merging, and table rendering.
| failure scenario: concretely, `status.py:425` constructs a `CurationContext` via `from_ticket` (network call to Jira), `:459` polls `bjobs`, and `:541` calls `tracker.finish(...)` — so `grit status -t RC-1234`, a command a curator reads as read-only, mutates the shared registry. A curator running `grit status` while offline from Jira gets a degraded table via a broad `except Exception` at `:435`; a curator running it on a machine with no `bjobs` silently gets different statuses than a colleague on the farm. And no part of the canonical-column logic (`_canonical_mark:227`, `_canonical_type_index:214`) or the reconciliation logic can be unit-tested without going through table rendering.
| effort: L | blast radius: module
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**ARCH-05** | severity: major | confidence: confirmed
| `grit/steps/pre_curation/setup.py:410` and 27 further sites (all `from grit.core.click_cli import build_context`)
| claim: every step depends on the CLI module for context construction, inverting the intended dependency direction and making the CLI unremovable.
| failure scenario: `build_context` (`click_cli.py:111`) does config-file loading + YAML override + `CurationContext.from_ticket`. Because it lives in the CLI module, using grit as a library (the documented "plain function usable from Python/notebooks" contract) still drags in `rich_click`, the full command tree, and — transitively — every step module. Any second frontend (API server, nextflow wrapper, test harness) must import `click_cli`. The lazy imports also mean an import error inside `click_cli` surfaces only when a specific command is *invoked*, not at import time.
| effort: M | blast radius: cross-module
| debt quadrant: inadvertent-reckless
| open-source impact: friction

**ARCH-06** | severity: major | confidence: confirmed
| `grit/steps/optional/busco_curated.py:28-29`, `grit/steps/pre_curation/add_pretext_view_tracks.py:24`, `grit/steps/post_curation/microchromosome_combine.py:27`, `grit/steps/pre_curation/microchromosome_second_shot.py:29`, `grit/steps/post_curation/post_processing.py:17`, `grit/steps/optional/blast_contaminants.py:32`, `grit/steps/pre_curation/find_reference.py:25`, `grit/steps/pre_curation/sex_matcher.py:64`, `grit/scripts/*.sh`
| claim: site-specific absolute paths — including two individuals' NFS home directories — are module-level constants inside step code rather than configuration.
| failure scenario: `_HAP_BEDGRAPH_SCRIPT = "/nfs/users/nfs_d/dz11/hap_bedgraph.py"` and `"/nfs/users/nfs_d/dz11/gitlab/vgp_curation_scripts/birds_microchromosomes/"` mean those two steps break permanently the day that account is closed, with no config knob to repoint them; `busco-synteny.sh:9` sources `/nfs/users/nfs_m/mh6/sing.bash`, i.e. a *different* colleague's file. `UserConfig` (`context.py:22`) has exactly six fields and none of them cover tool or script locations, so there is no seam to move these into.
| effort: M | blast radius: cross-module
| debt quadrant: deliberate-reckless
| open-source impact: blocker

**ARCH-07** | severity: major | confidence: confirmed
| `grit/core/base_command.py:11-37` vs `grit/steps/post_curation/haplotig_files.py`, `grit/steps/post_curation/validate_files.py`, `grit/steps/post_curation/post_curation.py`, `grit/steps/post_curation/post_curation_recurate.py`
| claim: four commands are allowlisted in `_DRY_RUN_SUPPORTED_COMMANDS` although their modules contain no occurrence of `dry_run` at all, so the guard that is supposed to stop `--dry-run` from doing real work does the opposite for them.
| failure scenario: `grep -n dry_run` returns nothing for all four files. `grit --dry-run haplotig-files -t RC-1234` therefore runs `run_haplotig_files` for real: it calls `find_latest_dir(ctx, "pretext_to_asm")` and then `haplotig_path.touch()` — real filesystem writes on a code path advertised as "no real command". `haplotig_files` additionally never calls `tracker.start/finish`, so its `STEP_MANIFESTS` entry (`manifests.py:41`) is dead and it never appears in `grit status`. `validate-files` is worse: it is allowlisted, has a `_cmd`, and is commented out of the command tree (`click_cli.py:280`) — 151 LOC unreachable.
| effort: S | blast radius: module
| debt quadrant: inadvertent-reckless
| open-source impact: none

**ARCH-08** | severity: major | confidence: confirmed
| `grit/utils/helpers.py:42-60` (`_run`) and `grit/utils/helpers.py:76` (`_submit_bsub`)
| claim: the single execution chokepoint composes shell command *strings* with f-string interpolation and runs them under `shell=True`, which makes correct quoting the caller's unwritten obligation.
| failure scenario: `_submit_bsub` builds `f'bsub{epilogue_part} {bsub_opts} "{inner_cmd}"'` — one outer double-quote pair. Any step whose `inner_cmd` legitimately contains a double quote silently truncates the job's command at that character; the bsub still succeeds and the job runs the wrong thing. Likewise any ticket whose YAML paths contain a space breaks every `_run(f"cp {src} {dest}")` in `finalize_qc.py:105-273`. This is already institutional knowledge ("inner_cmd wrapped in one outer quote pair") rather than an enforced property.
| effort: L | blast radius: cross-module
| debt quadrant: deliberate-prudent
| open-source impact: friction

**ARCH-09** | severity: major | confidence: confirmed
| `grit/steps/*/*.py` — 40 `tracker.start`/`finish` call sites, 28 identical Click wrappers, 20 inline `if ctx.dry_run:` blocks
| claim: the "one step pattern" is copy-paste, not an abstraction: there is no step base class, decorator, or context manager, so every invariant must be re-satisfied by hand in every file.
| failure scenario: 28 command bodies are byte-for-byte `state = ctx.obj; curation_ctx = build_context(state); try: run_X(...) except Exception: log.exception(...); raise SystemExit(1)`. Every `start()` repeats `ctx.ticket_id, ctx.tol_id, untracked=ctx.untracked`; every `finish()` must remember `untracked=ctx.untracked` or it silently overwrites the untracked marker — CLAUDE.md documents this as a bug that already shipped once, and the only defence is 40 hand-written keyword arguments. Three of them already omit it (`hic_remapping.py:82`, `sex_matcher.py:109,129`), justified today only because those paths can only see `status=="started"` rows — an invariant maintained by prose, not code.
| effort: L | blast radius: cross-module
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**ARCH-10** | severity: major | confidence: confirmed
| `grit/core/click_cli.py:330-359` (`retrack_cmd`) vs `grit/core/run_tracker.py` (`untrack`)
| claim: core domain operations live in Click command bodies, asymmetrically with their counterparts on the model.
| failure scenario: `untrack` is a `RunTracker` method; `retrack` is 20 lines of registry-walking logic (find last `untracked` run, back-fill its `outputs` from an earlier `success` record for the same `run_dir`, promote) written inline in the CLI. `_state-update`'s re-glob-and-finish logic (`click_cli.py:230-249`) is likewise CLI-resident and duplicated by `status._auto_step_outputs:306` and `helpers._step_output:380`. Consequence: retrack cannot be invoked programmatically, cannot be reused by the recovery paths in ARCH-01, and can only be tested through `CliRunner`.
| effort: M | blast radius: cross-module
| debt quadrant: inadvertent-reckless
| open-source impact: friction

**ARCH-11** | severity: minor | confidence: confirmed
| `grit/core/context.py:43`, CLAUDE.md:13
| claim: `CurationContext` is documented as a frozen dataclass but is a plain mutable `@dataclass`.
| failure scenario: `hic_remapping.py:172` even carries the comment "Apply CLI overrides to a fresh context copy (frozen dataclass)" while calling `dataclasses.replace` — correct behaviour resting on a false premise. Nothing prevents a future step from doing `ctx.workdir = ...` mid-run, which would silently change the workdir for every subsequent step in a composite command (`run_post_curation` passes one `ctx` through three steps). The documented invariant "no global state — everything flows through ctx" is enforced by convention only.
| effort: S | blast radius: cross-module
| debt quadrant: inadvertent-prudent
| open-source impact: none

**ARCH-12** | severity: minor | confidence: confirmed
| `grit/core/base_command.py:113-152`, `grit/core/click_cli.py:31-53`
| claim: `GlobalState` is per-invocation mutable state that `GritCommand.invoke()` writes into before the callback runs, so flags reach steps via a side channel rather than through `ctx`.
| failure scenario: `--print-only`, `--dry-run`, `--untracked`, `--bsub-ram` and `--ticket` are popped from `ctx.params` and OR-ed into `ctx.obj`, and `--dry-run` precedence is then re-derived a second time in `CurationContext.from_yaml:127`. Two implementations of one rule; a change to the precedence rule in one place is invisible in the other. `cli()` also constructs `GlobalState` without `untracked`/`bsub_ram` (`click_cli.py:82`), relying on constructor defaults — so the flag's value is assembled across three files.
| effort: S | blast radius: module
| debt quadrant: inadvertent-prudent
| open-source impact: none

**ARCH-13** | severity: minor | confidence: confirmed
| `grit/utils/helpers.py:37` (`require_workdir` -> `SystemExit(1)`), 28 further `raise SystemExit(1)` in `grit/steps/`
| claim: library-level code terminates the process instead of raising domain errors.
| failure scenario: calling `run_setup(ctx)` from a notebook — the documented use case for the plain step functions — kills the kernel's process on a missing workdir rather than raising something catchable. Any future non-CLI frontend must wrap every step call in `except SystemExit`.
| effort: M | blast radius: cross-module
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**ARCH-14** | severity: minor | confidence: confirmed
| `grit/core/status.py:161` (`_canonical_haps`) vs `grit/utils/helpers.py:20` (`is_single_hap`)
| claim: the single-haplotype test — explicitly called out in CLAUDE.md as *the* shared check — is reimplemented in status.py.
| failure scenario: both spell `in ("primary", "paternal")` today. Adding a third single-hap assembly type to `is_single_hap` (the documented shared helper) leaves `grit status` resolving canonical files for a non-existent hap2 and printing a spurious "not found" row for every canonical type.
| effort: S | blast radius: file
| debt quadrant: inadvertent-reckless
| open-source impact: none

**ARCH-15** | severity: minor | confidence: confirmed
| `grit/utils/helpers.py:831` (`write_fake_outputs`) vs `grit/steps/post_curation/pretext_to_asm_recurate.py:88` (`_write_fake_recurate_outputs`)
| claim: the dry-run fixture writer exists twice because the shared version cannot express a step whose specs are computed per haplotype.
| failure scenario: `write_fake_outputs` supports a 4-element "multi" spec (two placeholder files); the recurate copy does not, and unpacks specs as a fixed 3-tuple (`for key, pattern, _excludes in ...`). Adding a multi spec to `_output_specs_for_hap` raises `ValueError` at dry-run time only. `helpers._step_output:383` needs the same `if step.startswith("pretext_to_asm_recurate")` special case for the same reason — one step's dynamic specs leaking a branch into two other modules.
| effort: S | blast radius: cross-module
| debt quadrant: inadvertent-prudent
| open-source impact: none

**ARCH-16** | severity: minor | confidence: confirmed
| `grit/core/cleanup.py:38-50`, `grit/steps/post_curation/post_processing.py:63`
| claim: two commands bypass the `_run()` chokepoint, so CLAUDE.md's "all shell commands go through `_run(cmd, print_only)`" is not true.
| failure scenario: `cleanup._size_bytes` shells `du -sb --apparent-size` directly — GNU-only flags, so on macOS/BSD the call fails and every size in the cleanup table silently renders `?`, making the command's "how much will this free" output useless off-farm. `post_processing.py:63` pipes a script into `subprocess.run(["bash"], input=...)` and hand-rolls its own `if not ctx.print_only` guard plus its own command echo, duplicating `_run`'s two responsibilities.
| effort: S | blast radius: file
| debt quadrant: inadvertent-prudent
| open-source impact: friction

**ARCH-17** | severity: minor | confidence: confirmed
| `grit/core/context.py:238`
| claim: `sys.path.insert(0, ...)` mutates process-global state to load the `GritJiraIssue` dependency, the one real violation of "no global state".
| failure scenario: `from_ticket` is called repeatedly in one process (`status.show_ticket_history:425`, then a step's `build_context`), prepending the same directory to `sys.path` each time. Beyond the leak, this is the hard coupling to an unpublished internal library: there is no interface, no fallback, and no way to obtain a ticket without it — `yaml_override` (the `--yaml` flag) is the only escape hatch and it is documented as a testing aid.
| effort: M | blast radius: module
| debt quadrant: deliberate-prudent
| open-source impact: blocker

**ARCH-18** | severity: minor | confidence: plausible
| `grit/steps/post_curation/finalize_qc.py:127-385` (258-line function), `grit/steps/pre_curation/setup.py`
| claim: the two largest step files mix step orchestration with unrelated concerns, which is why they are hotspots.
| failure scenario: `finalize_for_qc` takes 6 optional override paths and inlines: YAML/PTA consistency validation, dest-name construction, per-hap copying, haplotig naming rules, pretext map copying to NFS, a nested `run_qv` call, and a full dry-run mirror of all of it — one function that must be re-read in full for any change (37 commits). `setup.py` similarly hosts FASTA header validation (`_validate_scaffold_headers:85`), NFS pretext-map discovery (`_find_pretext_maps:173`), scp-tip rendering (`print_pretext_scp_commands:259`) and the summary panel (`print_curation_summary:285`) that `core/status.py` reaches back into.
| effort: M | blast radius: module
| debt quadrant: inadvertent-prudent
| open-source impact: none

**ARCH-19** | severity: minor | confidence: confirmed
| `grit/steps/pre_curation/sex_matcher.py:100-109` vs `grit/core/manifests.py:20`, `grit/core/registry.py:290-294`
| claim: steps disagree on whether tracked outputs live in `run_dir` or `workdir`, and `core` hardcodes one step's name to paper over it.
| failure scenario: `sex_matcher` starts a run (creating `workdir/sex_matcher/<ts>/`) but its outputs land in `workdir` (`STEP_MANIFESTS` says `"dir": "workdir"`, and the resubmit guard globs `ctx.workdir / "Best_match*"`). Because `collect_outputs` only ever globs `run_dir`, `_resolve_gone_job` needs an explicit `elif step == "sex_matcher":` branch in `registry.py:292` — i.e. `core` knows one step by name. Any further step that writes to `workdir` needs another such branch, and its absence is a silent `failed`.
| effort: M | blast radius: cross-module
| debt quadrant: inadvertent-reckless
| open-source impact: none

**ARCH-20** | severity: minor | confidence: confirmed
| `grit/__init__.py:1-32`, `grit/steps/__init__.py:1-39`
| claim: both package roots exist purely as "backward compatibility" re-export shims, including private names, and one of them force-imports the entire step tree.
| failure scenario: `grit/__init__.py` re-exports `_run`, `_submit_bsub`, `_clean_species_name`, `_find_pretext_map_in_workdir` — private helpers now part of the public surface, so any rename in `helpers.py` is a breaking change to importers nobody has enumerated. `grit/steps/__init__.py` imports all 21 step modules eagerly, so `import grit` costs the whole tree and any single step's import error breaks everything; it also makes the cycles in ARCH-05 unavoidable for anyone who imports through the package root.
| effort: S | blast radius: cross-module
| debt quadrant: deliberate-prudent
| open-source impact: friction

## What is done well

These are real strengths and Phase 2 should preserve them rather than rebuild
them.

- **`CurationContext` as an explicit value object is the right call and is used
  consistently.** All 21 steps take `ctx` as their first parameter; there is no
  hidden singleton, no module-level mutable state (`grep '^\s*global '` finds
  zero real uses, `os.environ` is never mutated). Field derivation is
  centralised in exactly one place (`from_yaml`, documented as "the canonical
  constructor" and actually honoured — `from_ticket` delegates to it). It is
  large (24 fields) but the fields are cohesive: they are all facts about one
  ticket. It is *not* a god-object in the sense of holding unrelated services;
  its only injected collaborator is `tracker`. The `gritjiraissue_module`
  parameter on `from_ticket` is a genuine, if undocumented, injection seam.
- **`_run()` as a chokepoint mostly works, and the `print_only` invariant
  genuinely holds.** All shell execution except the two cases in ARCH-16 goes
  through it. More importantly, `RunTracker.start/finish` handle `print_only`
  internally (`run_tracker.py:91,150,160`), so a step cannot accidentally
  pollute the registry in preview mode even if it forgets a guard — the
  invariant is enforced at the right layer, not by discipline. Spot-checking
  every step's real path found no unguarded filesystem mutation.
- **The `bsub -Ep` epilogue design is genuinely clever and correctly
  documented.** Making "success" mean "the epilogue re-globbed the run dir and
  found the outputs" rather than "the submission returned 0" is the right
  semantics for fire-and-forget HPC, the `$LSB_JOBEXIT_STAT` trick is neat, and
  CLAUDE.md is honest about exactly where it stops working (steps that shell out
  to a script that submits its own jobs). All six steps that call
  `_submit_bsub` do pass an epilogue. The problem is the *fallbacks* (ARCH-01),
  not the mechanism.
- **`MODULE_VERSIONS` / `module_cmd()`** is a clean, complete abstraction: one
  file, one line per tool, and it correctly encapsulates the non-obvious detail
  that bsub's non-login shell needs `/etc/profile.d/modules.sh` sourced
  explicitly. This is the model the rest of the site-specific configuration
  should follow.
- **`collect_outputs()` / spec tuples are a good idea**, and the "multi" 4-tuple
  extension was added without breaking the 3-tuple callers. The *mechanism* is
  sound; only its registration (ARCH-03) and its five call sites (ARCH-01) are
  the problem.
- **`utils/output.py` and `utils/result_parsers.py` are correctly separated** —
  rendering primitives in one place, file parsing in another, with
  `print_curation_results` as the only (lazy, one-directional) bridge. This is
  the display/logic split that `status.py` should have had.
- **Test coverage is substantial and structural** (~8,800 LOC, 30 test modules,
  roughly 1:1 with production; a `mock_ctx` fixture that builds a real
  `CurationContext` from fixture YAML with no Jira or filesystem access). This
  is what makes the refactors implied above feasible at all.
- **The `--dry-run` sandbox concept is well designed** where implemented: one
  `dry_run_root()`, isolation of registry *and* workdir *and* curated dir, and a
  clear precedence rule against `print_only`. The gaps (ARCH-07) are omissions
  in a good design, not a bad design.
- **CLAUDE.md itself is unusually candid** — it documents the epilogue's
  limitation, the `untracked=` footgun, and the `validate-files` registration
  gap rather than hiding them. Most of the drift found here is in areas it does
  *not* claim (step-name registries, the four reconciliation paths), not in
  areas it does.
