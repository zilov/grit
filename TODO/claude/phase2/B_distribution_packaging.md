# Phase 2B — Distribution and packaging shape of the open-core split

Design-only. Read-only pass over `grit` @ `test_and_fix_steps` (`9175121`). Inputs:
`TODO/49_architecture_assessment.md` (settled verdicts), `TODO/50_assessment_remediation.md`
(`## Scope decision — 2026-09-03`), `TODO/claude/assessment/04` (seam inventory) and `05`
(packaging/DX/security), `TODO/XX_pixi_portability_plan.md`, plus `pyproject.toml`,
`.github/workflows/ci.yml`, `grit/config/`, `grit/utils/modules.py`, `grit/core/context.py`,
`grit/core/click_cli.py`, `grit/core/base_command.py`.

This document owns **distribution shape only**. It does not write the port contracts (another
agent owns those), does not write the migration roadmap (the consolidation owns that), and does
not prescribe per-dependency substitution decisions (another agent owns those). Where a decision
of mine implies a shape a port must have, I say so and stop at the shape.

---

## Summary

Seven recommendations, one per question.

1. **Topology — one repository, two distributions.** `grit` (core, all 21 steps, all generic
   adapters, the profile machinery, the `local`/`generic-lsf`/`generic-slurm` built-in profiles)
   and `grit-sanger` (one small distribution: the `sanger` profile, the `GritJiraIssue` metadata
   adapter, the ToL release target, and the site's path/module/queue table), built from one
   monorepo as a uv workspace. One repo keeps a sole maintainer's CI, review and cross-cutting
   commits atomic; two distributions mean the Sanger part can be withheld or relocated by an
   organisational decision without touching the core, and an outsider's wheel contains no Sanger
   topology.
2. **Extension mechanism — Python entry points, group `grit.site_profiles`, value = a
   zero-argument factory returning a `SiteProfile`, enumerated from metadata at CLI time and
   `.load()`-ed only for the *selected* profile inside `build_context()`.** Never at import.
   This replaces `context.py:237-239`'s `sys.path.insert` + `import GritJiraIssue`: the hack
   moves inside `grit-sanger`'s own adapter, and `gritjiraissue_path` leaves core's required
   config.
3. **Site profiles — a two-layer, explicitly-named bundle.** A profile declares identity,
   five adapter factories, a settings mapping, and per-step capability declarations. Packaged
   profiles (via entry point) and pure-config user profiles (`~/.grit/profiles/<name>.yaml`,
   inheriting adapters from a named base) both exist. Selection: `--profile` > `GRIT_PROFILE` >
   `profile:` key in the existing config file > the single installed non-built-in profile >
   `local`. Nextflow's `-profile` is the model; auto-detection by sniffing the environment is
   rejected as the *primary* mechanism.
4. **Tool provisioning — a `ToolProvider` port with three shipped backends (Lmod, PATH, container),
   and `pixi.toml` in-repo as the reference environment declaration, with an Apptainer image built
   from it as the deployment artefact for sites that will not run conda envs on shared storage.**
   The `module_cmd()` arity flaw (`PORT-19`) is fixed by changing the return *type*: a structured
   `ToolInvocation` (`preamble`, `wrapper`, `executable`) plus one `compose()` helper, so a
   no-preamble backend returns an empty tuple rather than a `""` that produces a leading `&&`.
5. **Dependencies and release — `rename-and-orient` is not a Python dependency and must be
   removed from `[project.dependencies]` and `[tool.uv.sources]` entirely.** It is invoked only
   as a CLI binary via `shutil.which`; it belongs in the ToolProvider tool table. Drop `pymysql`,
   `biopython`, `requests` too (unused). Publish to **PyPI first, bioconda second** — PyPI because
   that is what `pip`/`uv tool install`/`pixi add --pypi` all reach, bioconda (`noarch: python`)
   because that is how grit becomes co-installable with the tools it drives. Keep the existing
   explicit `version =` + Keep-a-Changelog discipline and *gate* it in CI; add tag-triggered
   Trusted Publishing.
6. **CI shape — five jobs.** A pinned Python matrix; a build-and-install-the-wheel job that
   asserts `grit --help` works with no config and no profile installed and that packaged data
   files are readable from the wheel; a `local`-profile end-to-end scenario suite driving the real
   CLI under `--dry-run` with `HOME` redirected to a tmpdir; a **cross-profile `--print-only`
   golden-file gate**, which is the only honest way to test the Sanger profile from a runner that
   cannot see Sanger; and a ratcheted mypy baseline.
7. **Publication hygiene — publish the design record, withhold the topology map, gitignore the
   agent directories, and separate the one decision that is not the author's.** `.claude/` and
   `.superpowers/` go in `.gitignore` (nothing is tracked today, and only one machine's
   `.git/info/exclude` is preventing it). `CLAUDE.md`'s load-bearing design content moves to
   `docs/design/`. `TODO/`'s cited design records are promoted to `docs/design/` in English;
   `TODO/claude/assessment/*` and `TODO/50` stay internal until the disclosure decision lands,
   because they are the most complete map of Sanger internal topology in the repository. The
   history question is escalated, not solved: it is clean of credentials (verified, 359 commits)
   but not of internal paths and three usernames.

**The acceptance criterion for the whole design**, stated once so it can be checked: a Sanger
curator upgrades, changes nothing in `~/.grit/grit_curation_config.yaml`, types
`grit setup -t RC-1234`, and the commands grit emits are byte-identical to today's. The
`--print-only` golden files in §CI are how that is demonstrated rather than asserted.

---

## Recommended topology

**One repository (`sanger-tol/grit`), two distributions, one uv workspace.**

### Why two distributions rather than one with extras

An extra cannot be un-published. Two distributions buy three things an extra does not:

- An outsider's `pip install grit` wheel contains no `/nfs`, no `/lustre`, no `tol22-head2`, no
  `team135`, and no staff usernames. With extras, `grit/config/sanger_template.yaml` and its
  successors ship to everyone regardless.
- If Sanger's answer on topology disclosure is negative — and per `TODO/49` P3 that is an
  organisational decision, not the author's — one directory moves to an internal repository or an
  internal index and the public core is unaffected. Designing for an answer you do not control is
  the point.
- Independent cadence. NFS roots, module names and queue names change far more often than
  canonical-resolution logic. Today a farm path change forces a core version bump; six tags in
  and that is already the shape of the release history.

### Why one repository rather than two

The author is the sole maintainer (`git shortlog`: 354 + 6 commits, one person under two
identities). Two repositories mean two CI configurations, two issue trackers, a cross-repo
compatibility matrix, and — worst — a port change that must land as two coordinated PRs with a
window in which `main` of one is incompatible with `main` of the other. A monorepo makes a
cross-cutting change one commit, one review, one CI run, and lets the conformance suite in
§CI import both sides directly. nf-core's two-repo split (`nf-core/<pipeline>` +
`nf-core/configs`) is the counter-example worth naming, and it is justified there by *many*
institutions each maintaining their own config independently under a shared review process. Grit
has one institution and one maintainer; that shape is not yet earned.

### Layout

```
grit/                                     # repository root → sanger-tol/grit
├── LICENSE                               # ← organisational; gates publication (see §Publication hygiene)
├── CITATION.cff
├── README.md                             # rewritten: what genome curation is → install → profiles
├── CHANGELOG.md                          # core; Keep-a-Changelog, unchanged discipline
├── CONTRIBUTING.md  CODE_OF_CONDUCT.md  SECURITY.md  RELEASING.md
├── pyproject.toml                        # uv workspace root AND the `grit` core distribution
├── uv.lock                               # one lock for the whole workspace
├── pixi.toml  pixi.lock                  # the reference tool environment (§Tool provisioning)
├── .gitignore                            # + .claude/ .superpowers/ dist/ .venv/ *.egg-info/
├── .github/
│   └── workflows/  ci.yml  release.yml  farm-smoke.yml
│
├── src/grit/                             # distribution: grit  (all 21 steps)
│   ├── core/          context.py  registry.py  run_tracker.py  click_cli.py  base_command.py
│   ├── steps/         pre_curation/  post_curation/  optional/          ← unchanged, 21 steps
│   ├── ports/         executor.py  tools.py  metadata.py  layout.py  release.py
│   │                                     # contracts only; the ports agent owns their content
│   ├── adapters/
│   │   ├── executor/  local.py  lsf.py  slurm.py
│   │   ├── tools/     path.py  lmod.py  container.py
│   │   ├── metadata/  yaml_file.py
│   │   └── release/   local_dir.py
│   ├── profiles/
│   │   ├── base.py                       # SiteProfile + settings merge/resolution
│   │   ├── discovery.py                  # entry-point enumeration; lazy .load()
│   │   ├── local.py         local.yaml         # ← reference implementation, CI-exercised e2e
│   │   ├── generic_lsf.py   generic_lsf.yaml
│   │   └── generic_slurm.py generic_slurm.yaml
│   ├── testing/                          # importable conformance suite for profile authors
│   ├── config/        init.py            # `grit init` — now profile-aware, no Sanger template
│   └── scripts/                          # vendored scripts (post-substitution)
│
├── packages/grit-sanger/                 # distribution: grit-sanger
│   ├── pyproject.toml                    # dependency: grit>=0.4,<0.5 ; entry point below
│   ├── CHANGELOG.md
│   ├── src/grit_sanger/
│   │   ├── profile.py                    # def profile() -> SiteProfile   ← the entry point
│   │   ├── sanger.yaml                   # NFS/lustre roots, module table, LSF group+queue, farm_host
│   │   ├── metadata_gritjira.py          # the GritJiraIssue adapter; owns the sys.path insert
│   │   └── release_tol.py                # curated-release target + the filename contract
│   └── tests/
│
├── docs/
│   ├── design/                           # promoted from TODO/, English
│   │   ├── canonical-resolution.md       # ← recuration-canonical-priority.md, verbatim
│   │   ├── run-tracking.md  dry-run.md  profiles.md  ports.md
│   └── usage/  installation.md  examples.md  writing-a-site-profile.md
│
├── tests/
│   ├── golden/<profile>/<step>.txt       # --print-only goldens (cross-profile gate)
│   ├── scenarios/                        # local-profile e2e via subprocess + --dry-run
│   └── farm_smoke_test.sh                # ← renamed local_smoke_test.sh; farm-only, fixed
└── TODO/                                 # internal (see §Publication hygiene for disposition)
```

`packages/grit-sanger/pyproject.toml`, in full as far as it matters:

```toml
[project]
name = "grit-sanger"
version = "0.4.0"
dependencies = ["grit>=0.4,<0.5"]

[project.entry-points."grit.site_profiles"]
sanger = "grit_sanger.profile:profile"
```

Two notes on the layout.

**The `src/` move is a recommendation, not a requirement, and it is cheap.** The package name
stays `grit`, so no import in the codebase changes; only the build configuration does. Its value
is that it makes the wheel-install CI job in §CI meaningful — with a flat layout, `import grit`
from the repo root silently resolves to the source tree, so "does the wheel contain
`sanger_template.yaml`" (the bug CHANGELOG 0.3.4 already records shipping once) is not testable.
If the roadmap owner sequences this away, the rest of the design is unaffected.

**ToL naming conventions stay in core.** Port 4 is the largest seam category (34 rows) and it is
tempting to call it Sanger-specific, but `SUPER_`/`SCAFFOLD_` naming, the `hap1/hap2` ↔
`primary/alternate` alias table, the `{tol_id}.{hap}.{v}.curated.fa` output specs and the
chromosome-list grammar are *load-bearing in every step's `_OUTPUT_SPECS`*. Moving them to a site
package moves half the step code with them, which contradicts the settled scope decision that all
21 steps are public core. Grit is a ToL-convention curation tool; that is its domain, and none of
it is confidential. What is site-specific is the *roots* those conventions hang off
(`/nfs/treeoflife-01/…`, the `assembly/draft` → `working` rewrite), and those are settings.

---

## Extension mechanism

**Recommendation: `importlib.metadata` entry points, group `grit.site_profiles`, whose value is a
zero-argument factory returning a `SiteProfile`. Discovery reads metadata only; `.load()` happens
once, for the selected profile, inside `build_context()`.**

### What the entry point returns

```python
@dataclass(frozen=True)
class SiteProfile:
    name: str                                    # "sanger"
    description: str                             # required, nf-core's minimum, verbatim
    contact: str
    url: str
    settings: Mapping[str, Any]                  # resolved: defaults ← user file ← env ← flags
    executor:  Callable[[], ExecutionBackend]    # factories, not instances
    tools:     Callable[[], ToolProvider]
    metadata:  Callable[[], MetadataSource]
    layout:    Callable[[], StorageLayout]
    release:   Callable[[], ReleaseTarget]
    capabilities: Mapping[str, Capability]       # tool/db availability + how to obtain
```

The five adapter slots are **callables, not constructed objects**, for one concrete reason:
`grit profiles` and `grit --help` must never construct an LSF client, open a Jira session, or
stat NFS. The factory is invoked at the moment a step actually needs that port. The port
contracts themselves belong to the ports agent; the shape above is only the envelope the
distribution mechanism requires — five named slots, lazily constructed, plus a settings mapping
and a capability declaration.

`capabilities` is the distribution-side answer to the new design element `TODO/50` identifies:
"a step has to be able to state *I require tool X and database Y; they are absent; here is how to
obtain them* and be checked before launch." A `Capability` is declarative data in the profile —
not code in a step — so `grit doctor -p sanger` and `grit doctor -p local` can both answer
"which of the 21 steps can this installation actually run" without a farm.

### When it is loaded

Three distinct moments, and keeping them distinct is the whole design:

| Moment | What happens | Cost |
|---|---|---|
| `grit --help`, `grit profiles` | `entry_points(group="grit.site_profiles")` — names, groups, values. **No import of any profile.** | metadata read only |
| profile selection (§Site profiles) | one `EntryPoint.load()` for the chosen name; settings merged | one module import |
| a step needs a port | `profile.executor()` etc. | one adapter construction |

This is substantiated by the `importlib.metadata` docs: `entry_points()` yields `EntryPoint`
objects carrying `.name`/`.group`/`.value` with no import, and `.load()` is what resolves the
value and performs the import. The lazy half is not an assumption; it is the documented contract.

**pytest is the anti-pattern to avoid, and it is worth naming explicitly** because it is the
entry-point plugin system this audience knows. pytest imports *every* installed `pytest11` entry
point at startup as a fixed step in its initialisation sequence — which is exactly why
`--disable-plugin-autoload` / `PYTEST_DISABLE_PLUGIN_AUTOLOAD` and `-p no:NAME` had to be
invented, and why the docs have to warn that "some hooks cannot be implemented in `conftest.py`
files which are not initial due to how pytest discovers plugins during startup." Grit must not
copy that. JupyterHub's `jupyterhub.spawners` entry point (registered since JupyterHub 1.0) is
the model to copy: an entry point exists so that a *config-named* class can be found without the
user writing an import path, and only the named one is imported.

Phase 1 found the CLI already imports 22 step modules at module scope and `grit/steps/__init__.py`
eagerly imports all 21 (`ARCH-05`, `ARCH-09`). Entry points do not make that worse — but they must
not be entangled with it. Two hard constraints follow, and they are the design's load-bearing
invariants:

- **No step module may touch `ctx.site` at import time.** Import-time access would make a
  third-party profile's import errors break `grit --help`, and `grit --help` working with no
  config at all is on Phase 1's preserve list.
- **`discovery.load(name)` wraps `.load()` in try/except and converts any exception into a
  `click.UsageError` naming the profile and the failing distribution.** A broken third-party
  profile must degrade to "profile 'x' failed to load: …", not to a traceback out of a group
  callback. (nf-core's institutional-config docs make the same disclaimer socially — "community
  members cannot be held responsible for the use of config on your infrastructure"; grit should
  make it structurally.)

### How this replaces `sys.path.insert`

Today `context.py:237-239` does, inside core, on the Jira path:

```
sys.path.insert(0, os.path.expanduser(cfg.gritjiraissue_path))
import GritJiraIssue
```

Under this design, core does none of that. `grit_sanger.metadata_gritjira` performs the
`sys.path` insert and the import **inside its own module, at adapter construction time**, reading
`gritjiraissue_path` from the *profile's* settings. Four things fall out:

1. `gritjiraissue_path` leaves `UserConfig`'s required keys (`context.py:38` is a `d["…"]`
   lookup today), which removes the dummy value a YAML-only user currently has to invent — the
   exact thing `tests/fixtures/test_config.yaml:7` does with `/tmp/dummy_gritjiraissue`. That
   closes `PORT3-03` as a side effect of the distribution change.
2. The failure mode becomes legible: a missing `GritJiraIssue` is the `sanger` profile reporting
   an unsatisfied capability, not core raising `ModuleNotFoundError` from a path-surgery site.
3. If `GritJiraIssue` is ever packaged, the hack deletes: it becomes a normal dependency of
   `grit-sanger` and the `sys.path` line disappears with no core change.
4. Core's only remaining metadata source is `adapters/metadata/yaml_file.py` — the `--yaml` path,
   which report 04 already assesses as "genuinely close to complete." That makes the Jira-free
   path the default and the Jira path the plugin, which is the right way round for an open core.

`CurationContext` gains exactly one field: `site: SiteProfile`. It remains the single injected
value object — Phase 1's preserve list is satisfied — and it acquires the thing report 04 says it
lacks: "`CurationContext` is a frozen-ish dataclass of *values*, not a container of *behaviours*
… so there is no seam through which to swap an executor or a tool provider." One field is that
seam.

---

## Site profiles

**Recommendation: a named bundle with packaged and user-file forms, explicit selection with one
narrow auto-selection rule, layered onto the existing `UserConfig` rather than replacing it.**

### What a profile declares

Four blocks, in the `SiteProfile` above:

- **Identity** — `name`, `description`, `contact`, `url`. Take nf-core's required minimum
  verbatim (`config_profile_description`, `config_profile_contact`, `config_profile_url`): it is
  the field set this audience already writes, and it exists because an unattributed institutional
  config is unmaintainable.
- **Adapters** — the five factories. A profile that supplies none is not legal; a profile that
  supplies *some* inherits the rest from a named `base` (below).
- **Settings** — the superset of today's `UserConfig` plus everything currently hardcoded:
  `pretext_maps_nfs`, `curated_pretext_maps_nfs`, `farm_host`, `username`, `email`, the LSF
  `group`/`queue` (`team135`, `normal` — three and one hardcoded sites respectively), the module
  name table now in `MODULE_VERSIONS`, the ~14 absolute tool/script paths that `modules.py` never
  sees, the BUSCO lineage root and SIF path, and the `assembly/draft` → `working` layout rewrite
  rule. This is the destination for `ARCH-06`/`PORT-03`: "`UserConfig` has six fields and none
  covers tool or script locations, so there is no seam to move them into." The profile is that
  seam.
- **Capabilities** — per-tool and per-database availability with a human-readable "how to obtain"
  string, keyed by the same logical tool keys the ToolProvider uses.

### Where a profile lives — both, with precedence

Two forms, deliberately:

- **Packaged profile** (entry point, Python). Can supply adapters. `local`, `generic-lsf`,
  `generic-slurm` ship in core; `sanger` ships in `grit-sanger`.
- **Pure-config user profile** — `~/.grit/profiles/<name>.yaml`, with a mandatory
  `base: generic-lsf` key naming a packaged profile whose adapters it inherits, and a `settings:`
  block that overlays that base's defaults. No code, no packaging, no PR to anyone.

The second form matters more than it looks. It is how the *second* institution on LSF gets
running — the nf-core/configs value proposition without the configs repository. nf-core's answer
to "a new institution needs settings" is a PR to a central repo reviewed by `@nf-core/maintainers`,
with a remote HTTP fetch of
`https://raw.githubusercontent.com/nf-core/configs/${params.custom_config_version}/nfcore_custom.config`
at run time, and `NXF_OFFLINE` as the escape hatch. That machinery is correct for dozens of
institutions and one maintainer cannot review it. A local YAML overlay gets 90% of the benefit at
0% of the governance cost, and the day a third and fourth site appear, a `grit-configs`
repository can be added *behind the same profile abstraction* without changing the core. Design
now for one site; leave the door where nf-core put theirs.

### How a profile is selected

Precedence, highest first:

1. `--profile <name>` (group-level flag, along`--yaml`/`--print-only`/`--dry-run`)
2. `GRIT_PROFILE` environment variable
3. `profile: <name>` key in `~/.grit/grit_curation_config.yaml`
4. **the single installed non-built-in profile, if there is exactly one**
5. `local`

Rule 4 is the one piece of magic and it earns its place: it is what makes
`pip install grit grit-sanger` produce a `grit setup -t RC-1234` that behaves exactly as today,
for every existing curator, with no edit to any existing `~/.grit/grit_curation_config.yaml`.
Without it, "the Sanger-specific part must keep working exactly as today" requires touching every
curator's config file. The trade-off is that installing a *second* site package silently changes
the rule-4 outcome to "ambiguous" — so rule 4 must fail loudly with a message listing the
candidates and telling the user to set `profile:`, never pick arbitrarily. `grit profiles` prints
the discovered set, which one is active, and **which rule selected it**.

**Auto-detection is rejected as a selection mechanism.** The pixi draft proposes
`shutil.which("pixi") → "pixi"`, else Lmod, else conda. That conflates "a tool is installed" with
"this is how this site provisions software": a curator's laptop with pixi installed is not thereby
a pixi-provisioned site, and an LSF submit host with pixi on `PATH` would be misidentified. A
profile is a declaration about a site, and sites are named. Nextflow reached the same conclusion:
`-profile` is explicit, and the only implicit thing is *which config files are read*, never which
profile is active.

### Settings resolution, and the fate of `UserConfig`

```
profile packaged defaults
  ← ~/.grit/profiles/<name>.yaml    (if a user profile / overlay exists)
  ← ~/.grit/grit_curation_config.yaml   (the existing file, read as an overlay)
  ← GRIT_<KEY> environment variables
  ← CLI flags (--bsub-ram, --curated-dir, …)
```

`UserConfig` **keeps its name and its six fields** and becomes a typed façade over the resolved
settings mapping, constructed by the profile rather than by `UserConfig.from_dict`. Every existing
key in every curator's existing config file keeps its exact meaning; `gritjiraissue_path` stops
being required by core and becomes a `sanger`-profile setting. `grit init` becomes profile-aware:
`grit init -p sanger` writes the six keys it writes today, `grit init` with no profile writes a
short annotated `local` config, and `grit/config/sanger_template.yaml` moves into
`packages/grit-sanger/src/grit_sanger/sanger.yaml`. That last move is, by itself, most of the
internal-topology disclosure fix in the working tree.

Nextflow's documented precedence order (`$NXF_HOME/config` < project `nextflow.config` <
launch-dir `nextflow.config` < `-c` files, with `-C` meaning "only this file") is the same shape,
and its known pitfall is worth avoiding by construction: until the 25.04 strict parser, profiles
in `-profile a,b` were applied *in config declaration order regardless of CLI order*, which is
precisely the sort of surprise a single-profile-selection model does not have. Grit should not
support comma-composed profiles. One profile, one overlay chain, one answer.

---

## Tool provisioning

**Recommendation: a `ToolProvider` port with three backends shipped in core — `lmod`, `path`,
`container` — and `pixi.toml`/`pixi.lock` committed in-repo as the reference environment
declaration, with an Apptainer/Docker image built from that lockfile as the artefact for sites
that will not put a conda env on shared storage.**

Pixi is the *source of truth for what the environment contains*; the container is a build product
of it, not a parallel declaration. That ordering is what stops the two drifting.

### Why this rather than picking one

- **Lmod stays** because the Sanger distribution must not change, and because `MODULE_VERSIONS` /
  `module_cmd()` is on Phase 1's preserve list as "a clean, complete abstraction, and the model
  the rest of the site-specific configuration should follow."
- **Pixi as the declaration** because the tool layer genuinely is largely on bioconda, and a
  lockfile is a strict improvement on `module load grit` — an unversioned, mutable module that
  pins nothing (`modules.py:24-32`). Verified bioconda coverage: `pretextmap`, `pretextgraph`,
  `pretext-suite`, `gfastats`, `fastga`, `merqury`, `yahs` are all present. Not present:
  `PretextView` (a GUI, GitHub releases only), `rapid-curation` and `curationpretext` (pipeline
  repos, not packages), `agp-tpf-utils` — which sanger-tol's *own* pixi setup installs as
  `pixi add --pypi "tola-agp-tpf-utils@git+https://github.com/sanger-tol/agp-tpf-utils"`. That
  mixed picture is exactly why the reference environment must be a pixi manifest that can carry
  both conda and PyPI/git sources, rather than a bioconda recipe list.
- **Containers as the deployment artefact** because the code already provisions BUSCO only via
  `singularity exec -B /lustre <sif>` sourced from a personal `sing.bash`, so a container backend
  is not speculative — it is the third mode already in use, which the pixi draft's two-row table
  omits. And a per-tool container is the only backend that works on an HPC that forbids conda on
  shared storage, which is common.
- **Not Lmod-only**: no outsider can reproduce `module load grit`. **Not pixi-only**: see the
  draft assessment below. **Not container-only**: an image cannot supply the unnamed BLAST
  `nt`-class database or the `~da16` BUSCO ID lists, so a container backend still needs the
  capability declaration to say what is missing.

### The `module_cmd()` arity flaw, fixed by changing the return type

`PORT-19`, stated in `TODO/50`: `module_cmd()` returns a shell fragment that 12 call sites splice
as `f"{module_cmd('X')} && …"`, so a backend needing no preamble cannot return `""` — it would
produce a leading `&&`. The fix is not a return-value swap; it is a type change.

```python
@dataclass(frozen=True)
class ToolInvocation:
    preamble:   tuple[str, ...] = ()   # ("... && module purge && module load grit",) or ()
    wrapper:    tuple[str, ...] = ()   # ("singularity","exec","-B","/lustre", sif) or ()
    executable: str = ""               # "pretext-to-asm" | "/software/.../get_lineage.rb"
```

and exactly one composition helper, used by all 12 sites:

```python
def compose(inv: ToolInvocation, *args: str) -> str: ...
    # " && ".join(p for p in inv.preamble if p)  +  shlex.join(inv.wrapper + (inv.executable,) + args)
```

Three properties follow, and the third is a bonus worth naming:

1. An empty preamble contributes nothing — no leading `&&`, no sentinel `"true"`, no caller-side
   `if`. The `path` backend returns `preamble=()`.
2. The three provisioning modes stop being three shapes: Lmod fills `preamble`, container fills
   `wrapper`, PATH/pixi fills neither, and the call site is identical in all three.
3. **`compose()` is the natural home for `shlex.quote`.** `SEC-01` — zero uses of `shlex` in
   9,483 LOC of `shell=True` — is a publication blocker in `TODO/50` Batch 7, and it is currently
   hard to fix because commands are assembled by f-string concatenation at 12+ sites. Once
   composition is a function taking an argv-ish tuple, quoting is enforced in one place instead of
   remembered in twelve. I am not claiming this design fixes SEC-01; I am saying it removes the
   reason SEC-01 is expensive, and the ports agent should be told that the tool port's return type
   is the lever.

The `ToolProvider` contract itself — how a backend maps a logical key to a `ToolInvocation`,
what happens on an unsatisfiable key — is the ports agent's. The requirement I am placing on it
is only this: **the return value must be structured, not a spliceable string.**

### One interaction the draft misses and this design must answer

`_state_update_epilogue` embeds `sys.argv[0]` as the compute-node path to `grit`
(`helpers.py:100`), which works only because the install is on a shared mount — and `~/.grit/` is
confirmed compute-visible (`TODO/50` Batch 0). Under a pixi or container backend, `sys.argv[0]`
points inside a pixi env directory or is meaningless. The profile must therefore carry an explicit
`grit_command` setting (default: `sys.argv[0]`, i.e. today's behaviour verbatim) that the epilogue
uses instead. That is a one-setting fix, it belongs in the profile rather than in `helpers.py`,
and completion detection's real redesign (`PORT-02`) stays with the ports agent.

---

## Dependencies and release

### Fixing `rename-and-orient`

`PKG-01` has three symptoms — uv-only `[tool.uv.sources]`, an unpinned mutable git ref on a
personal account, and `uv.lock` pinning `1.2.0` against a `>=1.2.2` constraint — and one cause:
**it is declared as a Python dependency and it is not one.** Report 05 establishes it is used
solely as a CLI binary resolved by `shutil.which("rename-and-orient")`
(`rename_and_orient.py:69-77`) and is never imported.

Recommendation, in order:

1. **Remove it from `[project.dependencies]` and delete the `[tool.uv.sources]` table.** It
   becomes a logical tool key (`RENAME_AND_ORIENT`) in the ToolProvider table, provisioned per
   profile: Lmod at Sanger, pixi/PyPI elsewhere. This is not a workaround — a runtime CLI
   dependency is exactly what the ToolProvider port exists for, and treating it as one makes
   `grit` PyPI-publishable, makes `pip install -e .` work, and makes the lock mismatch moot, in a
   single change.
2. Publish `rename-and-orient` itself to PyPI. It is on the author's own account
   (`github.com/zilov/rename-and-orient`), so this is actionable rather than a request to a third
   party, and it is a prerequisite for the pixi manifest to declare it cleanly.
3. Add `grit[rename-and-orient]` as an optional extra for users who want pip to install it
   alongside grit. An extra is the correct mechanism here precisely because this dependency is
   *not* disclosure-sensitive — the opposite of the site profile.
4. Drop `pymysql`, `biopython` and `requests` from `[project.dependencies]` (`PKG-05`: unused;
   the two PEP-723 scripts declare their own inline dependency blocks). The real import surface
   is `pyyaml` + `rich-click`. Declaring an unused MySQL driver also invites the reader to assume
   a database coupling that does not exist — which matters more once the repo is public.
5. Declare the two currently-undeclared runtime dependencies in documentation and in the profile's
   capability table: `uv` on compute nodes (`fastga_synteny.py:94`, `busco-synteny.sh:101`) and
   `ruby` for the `.rb` comparators.

### Publication channels

**Both, in this order: PyPI as the source of truth, bioconda as a `noarch: python` recipe
downstream of it.**

The evidence on what this audience installs from is genuinely two-tiered, and grit sits in the
second tier:

- Standalone bioinformatics *tools* are on bioconda — `pretextmap`, `pretextgraph`,
  `pretext-suite`, `gfastats`, `fastga`, `merqury`, `yahs` all confirmed present.
- The *orchestration and utility* layer of this exact ecosystem is not. `PretextView` ships as
  GitHub releases; `rapid-curation` and `curationpretext` are Nextflow pipeline repos, not
  packages; `agp-tpf-utils` — sanger-tol's own AGP/TPF tool, the closest structural analogue to
  grit there is — is installed from a git URL via pip/pixi even inside sanger-tol's own tooling.

So PyPI first, because it is the one channel that simultaneously serves `pip install grit`,
`uv tool install grit` (the README's current recommended path, which keeps working),
`pixi add --pypi grit`, and bioconda's own recommended recipe pipeline. Bioconda second, because
the payoff is specific and real: a `noarch: python` grit in a conda env *alongside* the tools it
drives is how the reference environment of §Tool provisioning actually gets built by a stranger.
Bioconda's contributor guidelines are explicit that this is the intended route — "if a Python
package is available on PyPI, use grayskull to create a recipe", an sdist is required (wheel-only
projects do not work), and pure-Python packages should carry `noarch: python`. Their autobump bot
then tracks PyPI releases and opens the version-bump PRs, so the ongoing cost is near zero. Note
also that bioconda does *not* require PyPI-first — its hosters include `GithubRelease` and
`GithubTag` — so this ordering is a choice for reach, not a constraint.

`grit-sanger` goes to **PyPI only, never bioconda**: it is site configuration of no interest to a
public bioinformatics channel. Whether it is published to PyPI at all or installed from an
internal git URL / internal index is a deployment decision that this design deliberately leaves
open — it is a normal distribution either way, which is the insurance the two-distribution
topology was chosen for.

### Versioning and release automation

The existing discipline is good and should be *gated*, not replaced. Six tags matching
`version = "0.3.5"`, an accurate maintained Keep-a-Changelog with a live `[Unreleased]` section,
and `click.version_option(package_name="grit")` already single-sourcing the runtime version.

- **Keep the explicit `version =` in each `pyproject.toml`.** Rejected: `hatch-vcs`. It removes a
  two-line chore and adds a requirement for `.git` at build time plus a version invisible in the
  tree — a bad trade against a discipline that is demonstrably already being kept. What is
  missing is not automation but *verification*.
- **Add a release gate job** that fails if the pushed tag does not equal the corresponding
  distribution's `project.version`, or if `CHANGELOG.md` has no section for it. This is where
  two-distribution drift would otherwise appear, and it costs ten lines.
- **Tag scheme:** `v0.4.0` for core, `sanger-v0.4.0` for the site package. `grit-sanger` pins
  `grit>=0.4,<0.5`, so a core minor bump is a deliberate, visible compatibility event.
- **Publish via `pypa/gh-action-pypi-publish` with PyPI Trusted Publishing** — OIDC, no
  long-lived token in CI, a short-lived scoped token minted per upload. PEP 740 digital
  attestations are produced by default for packages using Trusted Publishing with that action, so
  provenance is free rather than a project. PyPI's mandatory 2FA for uploading accounts (enforced
  since 2024-01-01) is a prerequisite on the maintainer account, not a workflow concern.
- **Citability**, which report 05 correctly calls an adoption blocker rather than a nicety: add
  `CITATION.cff` (GitHub links it from the repository landing page and renders a copyable BibTeX
  snippet) and enable the GitHub–Zenodo release hook, which archives each GitHub release and mints
  a **version DOI** plus a **concept DOI** that always resolves to the latest. `sanger-tol/curationpretext`
  already does this (Zenodo `10.5281/zenodo.12773958`), so it is the local norm. JOSS is the
  natural venue and its reviewer checklist requires archival DOIs for cited software; I could not
  verify that any journal mandates `CITATION.cff` *specifically* as opposed to "have a citable
  DOI", so the CFF is recommended on GitHub-rendering and tooling grounds rather than on a
  requirement.

**Every item in this subsection is gated on the licence.** Zenodo, JOSS and bioconda all need
one; PyPI does not require it but publishing without one is the same "no legal right to use"
problem `PKG-03` already names.

---

## CI shape

Five jobs. What matters is job 4, which is the answer to "how does the Sanger part get tested when
CI cannot see Sanger."

**1. Test matrix — pin the Pythons.** `3.10, 3.11, 3.12, 3.13` × `ubuntu-latest`, explicit
`python-version` to setup-uv, plus one `macos-latest` on the newest (curators run `--print-only`
and `--dry-run` from laptops, and `cleanup.py`'s GNU-only `du -sb --apparent-size` is exactly the
class of bug that surfaces there). Today `requires-python = ">=3.10"` is an untested assertion
against one unpinned interpreter. Add `UP` to the ruff `select` list — pyupgrade is what actually
polices a version floor — and `S` (bandit), which is what would have flagged the unquoted
`shell=True` interpolations. Add `uv lock --check`, `pip-audit`, and a Dependabot config.

**2. Build and install verification** — the job that does not exist today and should. `uv build`
both distributions, install each wheel into a clean venv (`pip install dist/*.whl`, deliberately
`pip` and not `uv sync`, so the `[tool.uv.sources]` class of bug cannot return), then assert:

- `grit --help` exits 0 with `HOME` pointing at an empty tmpdir, **no config file, and no site
  profile installed**. This is a Phase 1 preserve-list item; make it a CI assertion rather than a
  property someone has to remember.
- `grit profiles` lists exactly the built-in profiles; after `pip install grit-sanger`, it also
  lists `sanger` and reports rule 4 selecting it.
- every packaged data file is readable through `importlib.resources` from the installed wheel —
  which turns the `sanger_template.yaml`-not-in-the-wheel bug (already shipped once, CHANGELOG
  0.3.4) into a test. `.gitignore` needs `dist/` for this job to leave a clean tree.

**3. The `local` profile end-to-end, in CI, with no HPC.** Phase 1 recommends the `local` profile
as the reference implementation; the mechanism already exists and is under-used. Convert the
dry-run section of `tests/local_smoke_test.sh` into a pytest scenario suite that invokes the
**real CLI via `subprocess`** with `HOME` redirected to a tmpdir and `--dry-run` set, chaining
`setup → pretext-to-asm → haplotig-files → hic-remapping → qv → finalize-qc`, and asserts on
*registry state and canonical resolution outcomes* — not on shell strings. `--dry-run` already
isolates the registry, every workdir and the curated-release directory under `~/.grit/dry_run/`
and writes placeholder outputs from the same `_OUTPUT_SPECS` the real path uses, which is
precisely what makes this runnable on a GitHub runner. This is also the regression check CLAUDE.md
already mandates for canonical-FASTA logic and which nothing currently runs.

The shell script itself is renamed `tests/farm_smoke_test.sh`, fixed (it dies at line 66 under
`set -euo pipefail` on three commands commented out of `click_cli.py`), and kept as the farm-only
check, wired to a `workflow_dispatch` job that only a self-hosted runner could ever execute. Two
prerequisites for the port work, noted because they are cheap and they gate job 3: `--dry-run` is
allowlisted for four commands that contain no `dry_run` code at all (`ARCH-07`), and
`validate-files` is allowlisted but commented out of the command tree — a scenario suite will
surface both immediately, which is a feature.

**4. Cross-profile `--print-only` golden files — the Sanger test that needs no Sanger.** For every
(profile, step) pair, run the step with `--print-only` against a fixture ticket YAML and diff the
emitted command text against `tests/golden/<profile>/<step>.txt`. This works from any runner
because `--print-only` executes nothing: no LSF, no NFS, no Jira (the `--yaml` fixtures cover
metadata), no tools on `PATH`. It is byte-exact, so a changed module name, NFS root or LSF flag
appears as a reviewable diff in the PR that causes it. Report 04 independently identifies this as
the right instrument — "the printed command is exactly what would run … an excellent verification
tool for any port work (diff the printed commands before/after a refactor)".

**Say plainly what it does not do.** It proves the command grit *would* emit is unchanged. It
never proves the command works, that the module exists, that the NFS path is mounted, or that the
BLAST database is there. That residual is irreducible from a runner outside Sanger, and the honest
design covers it three ways rather than pretending: the golden files catch *regressions* in what
is emitted; the capability declarations in the profile let `grit doctor` catch *absences* on the
real host in one second before a run; and `RELEASING.md` carries a short manual farm checklist the
author executes once per release. That is the whole answer, and it is stronger than what exists
today, which is nothing.

**5. Types, ratcheted.** mypy, non-strict, `disallow_untyped_defs` off initially, with a committed
error baseline and a gate on *no new* errors. Phase 1 calls this "the highest value-per-effort CI
gate available" precisely because ~75%/77% annotation coverage already exists and nothing enforces
it — today the annotations are decoration and can drift silently. Ratchet per package so
`grit-sanger` (small, new) can be strict from day one while core catches up.

**Plus one thing that is CI-shaped but belongs to the ports agent's content:** the adapter
conformance suite (`TEST-09`). Its *location* is a distribution decision and mine: it lives in
core as `src/grit/testing/`, plain importable classes, run parametrically over every installed
profile in job 1, and importable by a third-party profile author's own CI. Snakemake's
`snakemake-interface-executor-plugins` is the precedent for shipping the contract as a package
that plugin authors build against. **Do not ship it as a `pytest11` entry point** — that is the
eager-import trap from §Extension mechanism, and it would make installing grit slow down every
unrelated pytest run on the machine.

---

## Publication hygiene

Four categories, separated by who decides.

### The author decides, and it is trivial

`.claude/` and `.superpowers/` — **nothing is tracked today** (`git ls-files` is 77 `.py`, 40
`.md`, 4 `.yaml`, 4 `.sh`, 1 `.yml`, 1 `.toml`, `uv.lock`, 8 small fixtures; no notebooks, no
binaries). But the two-line `.gitignore` does not cover them; they are protected only by 11
`**/.claude/*` patterns in one machine's `.git/info/exclude`, which does not travel with a clone.
The first contributor's `git add -A` commits them. Add `.claude/`, `.superpowers/`, `dist/`,
`.venv/`, `.pytest_cache/`, `.ruff_cache/`, `*.egg-info/` to `.gitignore`. No history action
needed.

### The author decides, and it needs judgement

**`CLAUDE.md` keeps its filename and loses its second job.** It is currently the project's
architecture documentation: the canonical-priority model, the `CurationContext` pattern, the
`bsub -Ep` completion contract with its subtle caveat, the exact `--untracked` finish-record
semantics, the synchronous-tracked-step protocol and the full `--dry-run` allowlist exist *only*
there. That content moves to `docs/design/` in the layout above. What stays in `CLAUDE.md` is what
belongs there: style rules, conventions, where things live. Publish it — its candour is a
strength, and report 05 is right that it is accurate — but it must not be the only place a human
can learn how the tracker works.

**`TODO/` splits three ways.** It is simultaneously the only written design-decision record —
`TODO/done/44_canonical_fa_flat_mtime_priority.md`, `45_dry_run_mode.md`, `46_dry_run_remaining_steps.md`
are cited *by name* from CLAUDE.md and from the smoke test's comments — and internal planning
notes, 9 of 35 files containing Cyrillic.

- **Promote and publish**: the cited design records, translated to English, into `docs/design/`.
  `recuration-canonical-priority.md` is already at the root and already human-facing; it moves to
  `docs/design/canonical-resolution.md` unchanged. Deleting this material destroys the only
  recorded "why" for canonical resolution and dry-run, and it is the material an external
  contributor most needs.
- **Keep internal for now**: `TODO/claude/assessment/*`, `TODO/49`, `TODO/50`, and this file.
  Not because they are embarrassing — they are the best artefacts in the repository — but because
  they are, collectively, **the most complete map of Sanger internal topology anywhere in it**:
  personal home paths, the farm head hostname, the LSF group, the named individuals, the
  identities of the unpublishable scripts and the hidden data dependencies. Publishing the
  assessment is a decision that must follow the disclosure decision, not precede it. Once
  disclosure is settled, publishing them is a net positive and I would recommend it.
- **Retire**: `TODO/XX_pixi_portability_plan.md` is superseded by this document and by report 04's
  assessment of it; move it to `TODO/done/`. `TODO/tiny.md` and `wasted_21_*` filenames read as
  scratch — internal only. Do not publish untranslated Russian planning notes; they are
  unreadable to the audience and they signal an unfinished repository.

**Repo location.** The repository is currently `github.com/zilov/grit` — a personal account, which
is also where README's `git+ssh://git@github.com/zilov/grit.git` install line points, and where
`rename-and-orient` lives. `sanger-tol` is where `PretextView`, `curationpretext`, `agp-tpf-utils`
and `yahs` live. Moving there before publication changes three things that matter: the citation
and DOI are institutional rather than personal, the trust signal for a genome centre evaluating
the tool, and the bus factor — a personal-account repository with one maintainer has no succession
path. This is organisational in that it needs someone at Sanger to agree, but it is not an IP
question and it should be raised early because it changes the URLs in `CITATION.cff`, the PyPI
`[project.urls]`, and the Trusted Publishing configuration.

### Must be escalated

- **`LICENSE`.** Sanger IP policy. Gates PyPI metadata, bioconda, Zenodo, JOSS, and any external
  contribution. See below for what each outcome changes.
- **Whether the internal topology may be disclosed** — `/nfs/users/nfs_?/{dz11,da16,mh6}`,
  `tol22-head2`, `team135`, `/software/grit/projects/…`. In the working tree this design already
  solves it: those values move into `grit-sanger`'s `sanger.yaml`, which can be withheld. **In the
  history it is not solvable by a file edit** — report 05 counted 7× `dz11`, 7× `da16`, 2× `mh6`
  under `/nfs/users/nfs_?/` across history. If the answer is negative, there are exactly two
  routes: a `git filter-repo` pass replacing those strings across 359 commits, or a fresh public
  repository seeded from a squashed initial commit, accepting the loss of history. Recommend the
  latter if it comes to that — a filter-repo pass over string patterns in a codebase this
  path-dense is easy to get incompletely right, and the history's value to an outside reader is
  low. State clearly when escalating: **the history is verified clean of credentials** (359
  commits scanned for password/secret/api_key/PRIVATE_KEY/credential; no `.pem`/`.key`/`.env`/
  `.netrc`/`id_rsa` at any path, ever), so no rewrite is required for secrets. This is a topology
  question only, and the decision should not be allowed to inherit the urgency of a leak.
- **Consent from `mh6` and `da16`**, whose home directory paths are load-bearing production paths
  today. Note that the substitution work in `TODO/50`'s scope decision removes most of these from
  the *code*; consent is still needed for the history, and provenance is still needed for the
  `~da16` sex-BUSCO ID lists, which only `da16` can supply.
- **Licence and provenance of anything vendored.** Two of the five
  `/software/grit/projects/vgp_curation_scripts/*` scripts look like copies of public GPL-ish
  projects (`ragtag_paf2delta.py` carries a RagTag header; `dgenies_index.py` looks D-GENIES-derived),
  and vendoring them into `src/grit/scripts/` inherits their obligations. Each vendored file needs
  a provenance header naming upstream, version and licence.

### What each licence outcome changes

- **Permissive (MIT / Apache-2.0)** — the sanger-tol norm; `curationpretext` is MIT. Everything in
  this document works as designed. Vendored GPL-derived scripts remain the one friction: they
  cannot be relicensed, so either they stay out-of-tree behind the ToolProvider or the affected
  files carry their own licence and the README says so.
- **Copyleft (GPL-3.0)** — fine for a CLI, and it makes the vendored GPL-ish scripts unambiguously
  compatible, which is a small point in its favour given two of them probably are. The cost is
  that anyone embedding grit as a *library* — and README documents a Python API — inherits GPL.
  Bioconda, PyPI, Zenodo and JOSS are all indifferent.
- **No licence, or internal-only** — publication does not happen, and none of §Dependencies'
  channel work is reachable. **The rest of this design still pays for itself**: the
  two-distribution split is a real internal modularisation, the `local` profile is what makes the
  step machinery testable in CI at all, and the profile abstraction is what lets a second
  institution be supported later without a fork. Nothing here should be sequenced *behind* the
  licence decision except publication itself.

---

## Assessment of the author's pixi draft

`TODO/XX_pixi_portability_plan.md` (90 lines, Russian). Report 04 already assesses it as a
portability plan and finds it covers "roughly one of five ports, partially." I assess it here as a
*distribution* proposal and say what survives into this design.

**What is right and is adopted.**

- Pixi/conda as the environment declaration, with `pixi.lock` for reproducibility. This is a
  genuine improvement on `module load grit`, which pins nothing, and it is adopted as the
  reference environment in §Tool provisioning.
- Keeping the Lmod path working so the Sanger distribution is unchanged. This is exactly the right
  instinct for an open-core split and it is the acceptance criterion of this whole document.
- `tool_cmd(tool_key)` as the single point of indirection, refactored out of `modules.py`. The
  shape is right; only the return type changes.
- `GRIT_ENV_BACKEND` as an explicit override. Adopted in spirit as `GRIT_PROFILE`, at the profile
  level rather than the backend level.
- The `README` "Installation on a new server" section it proposes is the right deliverable, and
  `docs/usage/installation.md` in the layout above is where it goes.

**What does not survive, and why.**

1. **Step 2 asks to "fill in" `grit/config/environments.py` and `settings.py`. Neither file
   exists.** `grit/config/` contains `__init__.py` (empty), `init.py` (24 lines) and
   `sanger_template.yaml` (23 lines). Both named files were *deleted* in history. The draft
   therefore reads as though a config layer is half-built when nothing of it exists — which
   changes Step 2 from an afternoon to designing the settings layer that §Site profiles specifies.
2. **`MODULE_VERSIONS` is treated as the tool inventory. It is not.** Five keys collapsing to two
   real modules, against ~20 externally-provided tools, ~14 of them hardcoded absolute paths that
   `modules.py` never sees, four inside individuals' home directories. The draft's own open
   question — "which tools from `MODULE_VERSIONS` are in bioconda?" — uses a denominator wrong by
   roughly 4×. This is the single most consequential error, because it is what makes the plan look
   S-sized.
3. **Auto-detection is the wrong selection mechanism.** `shutil.which("pixi") → "pixi"` conflates
   "a tool is installed" with "this is how this site provisions software". A laptop with pixi is
   not a pixi-provisioned site; an LSF submit host with pixi on `PATH` would be misidentified and
   would then fail at `bsub` — which is symptom (4). Replaced by an explicitly named profile, with
   one narrow single-installed-profile rule.
4. **No mention of the scheduler at all.** 117 `bsub`-touching lines, `-Ep`,
   `$LSB_JOBEXIT_STAT`, `bjobs` polling in `registry.py` and `status.py`, `TERM_MEMLIMIT` surfaced
   in the UX. Pixi provisions tools; it does not submit jobs. A pixi-only port produces a `grit`
   that can find `FastGA` and then dies at `bsub`.
5. **No mention of the metadata source or the release target.** `GritJiraIssue` via `sys.path` is
   simultaneously the largest coupling and a distribution problem; `post_process_rc` is a shell
   alias with no substitution point at all, and it gates a ticket's `done` state.
6. **Data dependencies cannot be pixi-installed.** The BUSCO lineage tree behind a mutable
   `latest` symlink, the `~da16` sex-BUSCO ID lists, and the unnamed BLAST `nt`-class database
   inside `~mh6/…/decon_fasta`. This is the category most likely to become a late blocker, and it
   is why §Site profiles requires capability declarations rather than assuming an environment
   manifest is sufficient.
7. **Singularity is a third provisioning mode, not a footnote.** BUSCO runs *only* via
   `singularity exec -B /lustre <sif>`, sourced from a personal `sing.bash`. The draft's two-row
   lmod/pixi table has no place for it. Handled here by `ToolInvocation.wrapper`.
8. **`FastGA_dot_dgenies_stats.sh:36` already escapes the registry** with its own
   `module load fastga/1.1-c1`, so "change one line in `modules.py` to update a version" is
   already false today. Any provisioning design must assume shell scripts are also consumers of
   the tool table, not only Python call sites.
9. **The return-arity problem is named nowhere.** Step 3's "return either `module load …` or just
   the binary name" changes the string's arity at 12 `f"{module_cmd('X')} && …"` sites and
   produces a leading `&&`. Fixed by the `ToolInvocation` type change, not a return-value swap.
10. **`pixi run grit` breaks the epilogue.** `_state_update_epilogue` embeds `sys.argv[0]` as the
    compute-node path to `grit`; under pixi that is inside an env directory. Addressed by the
    profile's `grit_command` setting.
11. **No verification strategy**, despite `--print-only` and `--dry-run` being tailor-made for
    exactly this — diffing emitted commands across backends is the cheapest possible correctness
    check for a provisioning refactor, and it is §CI job 4.
12. **It is in Russian**, so it cannot be published as a design record and cannot be reviewed by
    an external contributor. Retire it to `TODO/done/`.

**Verdict: a sound Step-1 note about one backend of one port, mis-scoped as a portability plan.**
Its two durable contributions — pixi as the environment declaration, and preserving the Lmod path
— are both adopted here.

---

## Prior art

Verified live during this pass unless flagged.

**nf-core institutional configs** — https://github.com/nf-core/configs ,
https://nf-co.re/docs/developing/institutional-profiles/overview ,
https://nf-co.re/docs/tutorials/external_usage/nf-core_configs_outside_nf-core .
A separate repository from every pipeline. Selection is `-profile <institution>` and composes with
others: "Users can combine institutional profiles with other profiles using comma-separated values:
`nextflow run nf-core/rnaseq -profile <institution>,docker`". Discovery at run time is a **remote
HTTP fetch**, not a package — every pipeline's `nextflow.config` carries
`includeConfig !System.getenv('NXF_OFFLINE') && params.custom_config_base ? "${params.custom_config_base}/nfcore_custom.config" : "/dev/null"`
with `custom_config_base` defaulting to
`https://raw.githubusercontent.com/nf-core/configs/${params.custom_config_version}`, so the configs
repo ref is pinned by a **parameter independent of the pipeline version**, and `NXF_OFFLINE`
disables the fetch for air-gapped HPC. A new institution submits a `conf/` file, a `docs/` page and
a registration entry in `nfcore_custom.config`, by PR reviewed by `@nf-core/maintainers`; the
documented minimum content is `params.config_profile_description`, `params.config_profile_contact`
and `params.config_profile_url`. *Adopted*: the required identity triple, and the settings-overlay
concept. *Rejected*: the separate repository and central review, as unearned at one institution and
one maintainer; and the remote runtime fetch, which trades a supply-chain surface for a problem
grit does not have. (Exact review-process wording is a paraphrase of the fetched page; the
`includeConfig` snippet is verbatim from real pipeline configs.)

**Nextflow `-profile` and config precedence** — https://docs.seqera.io/nextflow/config (the current
canonical home; `nextflow.io/docs/latest/config.html` redirects there). Documented precedence,
lowest to highest: `$NXF_HOME/config` → project `nextflow.config` → launch-dir `nextflow.config` →
`-c <file>`; `-C <file>` means *only* that file. The pitfall worth avoiding by construction:
"Nextflow applies config profiles in the order in which they were defined in the config,
regardless of the order you specify them on the command line" — changed only in the 25.04 strict
parser, where "Nextflow applies profiles in the order you specify them on the command line." Two
behaviours for the same command line, separated by a parser version. *Adopted*: an explicit named
profile and a documented overlay chain. *Rejected*: comma-composed profiles, for exactly this
reason.

**Snakemake executor plugins** — https://snakemake.github.io/snakemake-plugin-catalog/ ,
https://snakemake.github.io/snakemake-plugin-catalog/plugins/executor/lsf.html ,
https://snakemake.readthedocs.io/en/latest/executing/executors.html ,
https://pypi.org/project/snakemake-executor-plugin-lsf/ . 27 executor plugins, PyPI-distributed,
named `snakemake-executor-plugin-<name>` and selected as `--executor <name>`; the catalog
auto-discovers from PyPI ("New plugins will be automatically found on PyPI (which implies that they
have to be released to PyPI first)"), and plugins build against a stable
`snakemake-interface-executor-plugins` contract with a per-plugin "Minimum Snakemake Version". The
LSF plugin's own catalog page carries, verbatim: **"This plugin is not maintained and reviewed by
the official Snakemake organization."** Same banner appears on `lsf-jobstep`, `deeporigin`,
`cannon`, `pcluster-slurm` — it is a catalog-wide marker for community plugins, not an LSF-specific
judgement. Phase 1 already weighed this in rejecting a Snakemake migration and the point stands
here in a narrower form: **the interface-as-a-package idea is worth copying; the
one-tiny-distribution-per-backend fan-out is not**, because it distributes the maintenance of the
scheduler that grit's only production site actually runs to whoever volunteers. Grit's LSF adapter
belongs in core, maintained by the project. *Adopted*: `src/grit/testing/` as the importable
contract, and versioning the profile interface against core's minor version. (The semver policy of
`snakemake-interface-executor-plugins` itself: **not verified**.)

**JupyterHub spawners** — https://github.com/jupyterhub/batchspawner ,
https://pypi.org/project/jupyterhub-kubespawner/ . One core, site-specific execution backends as
separate PyPI distributions (`jupyterhub-kubespawner`, `batchspawner`, `sshspawner`,
`yarnspawner`); "As of JupyterHub 1.0, custom Spawners can register themselves via the
`jupyterhub.spawners` entry point", while selection is config-driven —
`c.JupyterHub.spawner_class = 'batchspawner.TorqueSpawner'`. **This is the closest structural
match to what I am recommending** and it is instructive that both mechanisms coexist: the entry
point exists so a config file can name a backend without spelling an import path, and the config
key remains the selector. Note also that `batchspawner` itself is *one* package covering
Torque/Moab/SLURM/SGE/HTCondor/LSF — the same "generic scheduler adapters live together in core"
choice made in §Recommended topology.

**Galaxy job destinations** — https://docs.galaxyproject.org/en/master/admin/jobs.html . One core
codebase; site and backend selection lives entirely in an XML admin config mapping job
"destinations" to runner plugins (local, PBS, DRMAA, Slurm, plus dynamic rules in
`tool_destinations.yml`). No second repository, no second package. Precedent for "site config is
config, not code" — which is why §Site profiles supports a pure-config user profile at all.

**dask-jobqueue, as the counter-model** — https://jobqueue.dask.org/ . Deliberately ships
`LSFCluster`, `SLURMCluster`, `PBSCluster` and the rest as classes in one distribution, one
namespace. Named here because it is the honest alternative to any split: if grit's site-specific
part were only scheduler flags, this would be the right answer and §Recommended topology would be
wrong. It is not the right answer here for one reason — grit's site part contains
disclosure-sensitive content and references to unpublishable dependencies, and you cannot
un-publish a class in a shipped package.

**pytest entry-point discovery, as the anti-pattern** —
https://docs.pytest.org/en/stable/how-to/writing_plugins.html ,
https://docs.pytest.org/en/stable/how-to/plugins.html . Group `pytest11`; "pytest looks up the
`pytest11` entrypoint to discover its plugins". Loading is **eager and at startup**, a fixed
sequence: block `-p no:name` → builtins → `-p name` plugins → third-party entry points → env-var
plugins → `conftest.py`. Consequences the docs themselves document: "Some hooks cannot be
implemented in `conftest.py` files which are not initial due to how pytest discovers plugins during
startup", and the existence of `-p no:NAME` and `--disable-plugin-autoload` /
`PYTEST_DISABLE_PLUGIN_AUTOLOAD` as escape hatches. (A quantified performance cost of many
installed plugins: **not verified** — the docs do not state one.) *Rejected as a model*: this is
what §Extension mechanism's metadata-only enumeration exists to avoid.

**Entry-point laziness** — https://docs.python.org/3/library/importlib.metadata.html ,
https://packaging.python.org/en/latest/specifications/entry-points/ . The `importlib.metadata` docs
confirm the load pattern this design depends on: `entry_points()` yields `EntryPoint` objects with
`.name`/`.group`/`.value` and no import, and `.load()` "resolves the value" — i.e. performs the
import and returns the object. The PyPA spec defines the static `entry_points.txt` format and the
group-naming rule `^\w+(\.\w+)*$` with namespacing by project name to avoid collisions, which is
why the group here is `grit.site_profiles`. Worth flagging precisely: **the laziness guarantee is
in the `importlib.metadata` runtime docs, not in the PyPA spec** — the spec is only about the
static metadata format.

**Bioconda** — https://bioconda.github.io/ , https://bioconda.github.io/contributor/guidelines.html ,
https://bioconda.github.io/developer/updating.html , https://github.com/bioconda/bioconda-utils/issues/354 .
"thousands of software packages related to biomedical research"; Linux and macOS only. Guidelines
state: use `grayskull` for a package already on PyPI; `conda skeleton pypi`/`grayskull pypi` need
an sdist and "packages on PyPI which only have a wheel will not work"; pure-Python packages should
carry `noarch: python`. The autobump `Scanner` tracks upstream across hosters including
`GithubRelease`, `GithubTag`, `GithubReleaseAttachment`, `GithubRepoStore` as well as `PyPi`, so a
GitHub tag is an accepted and auto-tracked source — bioconda does **not** require PyPI first. Tool
coverage confirmed for this ecosystem: `pretextmap`, `pretextgraph`, `pretext-suite`, `gfastats`,
`fastga`, `merqury`, `yahs` present; `PretextView` (GUI, GitHub releases only, sanger-tol),
`rapid-curation`, `curationpretext` (Nextflow pipeline repos) and `agp-tpf-utils` absent — the last
installed in sanger-tol's own tooling as
`pixi add --feature tol-curation-utils --pypi "tola-agp-tpf-utils@git+https://github.com/sanger-tol/agp-tpf-utils"`.
*Not verified*: the Grüning et al. 2018 Nat Methods paper's exact wording (auth wall), and
BioContainers' claim of fully automatic Docker/Singularity builds for every recipe
(biocontainers.pro redirects to the GitHub org; not re-fetched). The container claim is not
load-bearing for any recommendation here.

**Release mechanics** — https://docs.pypi.org/trusted-publishers/ ,
https://github.com/pypa/gh-action-pypi-publish , https://peps.python.org/pep-0740/ ,
https://blog.pypi.org/posts/2024-11-14-pypi-now-supports-digital-attestations/ ,
https://blog.pypi.org/posts/2023-12-13-2fa-enforcement/ , https://github.com/ofek/hatch-vcs .
Trusted Publishing is OIDC-based and tokenless: CI presents an OIDC token, PyPI matches it against
a pre-registered publisher (repo + workflow) and mints a short-lived (~15 min) upload token.
`pypa/gh-action-pypi-publish` is "the blessed GitHub Action … the tokenless way", with current
guidance not to invoke trusted publishing from inside a reusable workflow. PEP 740 attestations
have been live since Nov 2024 and are "enabled by default for packages that use Trusted Publishing
with the canonical PyPA pypi-publish action". 2FA has been mandatory for upload/management actions
since 2024-01-01. `hatch-vcs` derives the version from git tags at build time (same approach as
`setuptools_scm`), against the manual `version =` bump this project already performs correctly.

**Citation** — https://citation-file-format.github.io/ , https://joss.readthedocs.io/en/latest/review_checklist.html .
CITATION.cff is "a plain text file with human- and machine-readable citation information for
software"; GitHub links it from the repository landing page and renders a copyable BibTeX snippet.
The GitHub–Zenodo hook archives each release and mints a per-version DOI plus a concept DOI that
resolves to the latest. JOSS's reviewer checklist requires archival DOIs for cited software.
*Not verified*: that any journal mandates CITATION.cff specifically rather than "have a citable
DOI".

---

## Rejected alternatives

**Two repositories (`grit` + `grit-sanger`), nf-core style.** The cleanest separation available
and the one the audience would recognise, and it is what I would recommend at three institutions.
Rejected at one: it doubles CI, issue tracking and release ceremony for a sole maintainer, and it
makes every cross-cutting port change a pair of coordinated PRs with a window where the two
`main`s are incompatible — which is exactly the period when the ports work will be at its most
volatile. The monorepo preserves the two-distribution benefit (independent publication,
withholdability) while keeping the cost at one CI run. Revisit if a second institution starts
maintaining its own profile.

**One repository, one package, Sanger behind optional extras
(`pip install grit[sanger]`).** The lowest-ceremony option, one version number, one changelog, and
the dask-jobqueue precedent supports it. Rejected because an extra ships to everyone: the wheel
contains the Sanger topology whether or not the extra is selected, and if the disclosure answer is
negative there is no move that does not touch the core. Extras are the right mechanism for
non-sensitive optional dependencies, which is why §Dependencies uses one for
`grit[rename-and-orient]`.

**Namespace packages (`grit_sites.sanger` as a PEP 420 namespace).** Would let site packages drop
into a shared namespace with no registration at all. Rejected: discovery then requires either
scanning the namespace's `__path__` (which imports submodules to find out what they are — the
pytest problem, reintroduced) or a naming convention, and namespace packages are a persistent
source of confusing failures when one distribution accidentally ships an `__init__.py`. Entry
points give the same "drop in a package and it is found" property with metadata-only discovery and
a documented spec.

**A plugin base class with a subclass registry (`class SangerProfile(SiteProfile)` +
`__init_subclass__`).** Attractive because it needs no packaging metadata and gives the type
checker something to hold. Rejected because a subclass registry only populates when the module is
imported, so it needs an import trigger — which is either a config-named import path (the next
alternative) or a scan (the previous one). The registry is the wrong half of the problem;
`SiteProfile` remains a dataclass because a profile is data plus five factories, not a behaviour to
override.

**Config-driven explicit import path, JupyterHub's `spawner_class` without the entry point
(`profile_class: grit_sanger.profile:SangerProfile` in the config file).** Simple, zero packaging
work, completely explicit, and JupyterHub demonstrably ships it as the *selector*. Rejected as the
*only* mechanism because it pushes a dotted import path into every curator's config file, which
makes renaming an internal module a breaking change for users and makes `grit profiles` impossible
— nothing can be listed that has not already been named. Note that this design keeps the good half:
the config's `profile: sanger` key is a selector by *name*, and the entry point is what maps a name
to a path.

**Auto-detecting the site from the environment (`shutil.which("pixi")`, presence of `bsub`,
presence of `/nfs/treeoflife-01`).** The pixi draft's mechanism. Rejected: it conflates tool
availability with site policy, it fails identically on a laptop with pixi and on an LSF host with
pixi, and it makes "why did grit do that" unanswerable without reading detection code. A single
narrow rule survives — one installed non-built-in profile is selected automatically — and even that
must print which rule fired.

**Lmod only (status quo).** Zero work, and the Sanger distribution is already correct. Rejected
because it is the publication blocker: four of five `MODULE_VERSIONS` keys resolve to an
unversioned internal module named `grit` that is documented nowhere, so an outsider who solves
install still cannot execute one real step.

**Pixi only (the draft's implied end state).** Rejected in detail in §Assessment above; the
one-line version is that pixi provisions tools and does not submit jobs, does not fetch metadata,
cannot install a 400 GB BLAST database or a third party's curated BUSCO ID lists, and its proposed
auto-detection would misidentify Sanger itself.

**Containers only (an Apptainer image as the sole provisioning story).** Genuinely attractive for
reproducibility and it is what the code already does for BUSCO. Rejected as the *only* backend
because Lmod must keep working unchanged at Sanger, because a container is a build artefact that
needs a declaration behind it (hence pixi as the source of truth), and because container-only makes
laptop development awkward for the one workflow — `--print-only` / `--dry-run` — that most needs to
stay frictionless.

**Bioconda only.** Rejected: it would not serve `uv tool install`, `pip install`, or
`pixi add --pypi`, and bioconda's own recommended recipe path for a Python package starts at PyPI
with an sdist. **PyPI only** was also rejected, more narrowly: it works for installing grit, but it
leaves a stranger with no single command that installs grit *and* the tools it drives, which is the
actual onboarding problem.

**`hatch-vcs` / tag-derived versions.** Removes the manual bump. Rejected because the manual
discipline is demonstrably being kept (six tags, all matching, an accurate changelog), and because
tag-derived versioning requires `.git` at build time and makes the version invisible in the tree.
What is missing is verification, not automation — so the recommendation is a CI gate on
tag-equals-version-equals-changelog-section instead.

**Deleting `TODO/` before publication.** Tempting: 9 of 35 files contain Russian, some filenames
read as scratch, and `TODO/claude/` is process artefact. Rejected because `TODO/done/44`, `45` and
`46` are cited by name from CLAUDE.md and from the smoke test as the place where the rationale for
canonical resolution and dry-run lives, and deleting them destroys the only written "why" for the
two most subtle mechanisms in the codebase. The disposition is a split, not a deletion.

---

## Open questions for the author

Ordered by how much of this design they gate.

1. **The licence.** Nothing in §Dependencies' channel work, the DOI, or JOSS is reachable without
   it. Everything else in this document proceeds regardless — say so when escalating, so the
   engineering does not queue behind the decision.
2. **May `grit-sanger` be published at all, and where does the repository live?** Public PyPI, an
   internal index, or an internal git URL. And: does the repository move from `github.com/zilov/grit`
   to `sanger-tol`? The second question changes `CITATION.cff`, `[project.urls]` and the Trusted
   Publishing configuration, so it should be settled before the first release, not after.
3. **Is the internal topology in *history* publishable?** `/nfs/users/nfs_?/{dz11,da16,mh6}`,
   `tol22-head2`, `team135`. If not, the choice is a `filter-repo` string pass over 359 commits or
   a fresh repository from a squashed initial commit — and I would recommend the latter. Please
   carry the verified fact into that conversation: the history is clean of credentials, so this is
   not an incident.
4. **Will `rename-and-orient` be published to PyPI?** It is on your own account, so this is a
   decision rather than a request. §Dependencies works either way — the tool moves to the
   ToolProvider table regardless — but a PyPI release is what lets the pixi manifest and the
   optional extra declare it cleanly.
5. **Can a Sanger-visible CI runner ever exist** (a self-hosted GitHub Actions runner on a login
   node, or a scheduled internal job)? §CI's answer without one is honest but incomplete — golden
   `--print-only` files plus `grit doctor` plus a manual release checklist. One runner would turn
   the farm smoke test from a manual step into a gate, and it is the single largest available
   improvement to confidence in the Sanger profile.
6. **Can `GritJiraIssue` itself be packaged** (even to an internal index)? If yes, the last
   `sys.path` manipulation in the project deletes and `grit-sanger` becomes a distribution with no
   unusual mechanics at all. If no, the hack is confined to one adapter module in one distribution,
   which is already a strict improvement.
7. **Confirm ToL naming conventions stay in core.** I have asserted this (§Recommended topology) on
   the grounds that Port 4 is load-bearing in every step's `_OUTPUT_SPECS` and that none of it is
   confidential. If you disagree — if ToL filename conventions are themselves considered
   site-specific — the split boundary moves substantially and half of `helpers.py` moves with it.
   This is the assumption of mine most worth challenging.
8. **Naming: is `generic-lsf` a useful built-in given Sanger is also LSF?** My view is yes, and
   that `sanger` should be `base: generic-lsf` plus settings plus the two Sanger adapters — which
   would make the Sanger profile *provably* a thin overlay rather than a parallel implementation,
   and would make the second LSF institution nearly free. It also means a bug in LSF handling is
   fixed in core for everyone. Confirm you want that coupling.
9. **The one I am least sure about, flagged as such**: whether the two-distribution split is worth
   its cost *if* the disclosure answer comes back permissive. If Sanger says the paths and
   usernames may be published, then the main argument for two distributions collapses to
   "independent release cadence" and "a clean outsider wheel", and one package with a `[sanger]`
   extra becomes defensible on simplicity grounds for a sole maintainer. I still recommend two,
   because the profile boundary is worth enforcing structurally rather than by discipline and
   because an extra cannot be withdrawn later — but this is the recommendation in this document
   that I would most readily revise given the disclosure answer, and it is cheap to revise *before*
   the ports land and expensive after.
