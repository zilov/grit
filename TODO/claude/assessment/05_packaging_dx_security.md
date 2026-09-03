# 05 — Packaging, Developer Experience & Security Posture

Assessment of `grit` @ `test_and_fix_steps` (9,483 LOC in `grit/`, 451 tests, 359 commits, 6 tags).
Phase 1: diagnosis only. Read-only; nothing was edited, no `~/.grit/` write, no venv change,
`tests/local_smoke_test.sh` was **not** run, `uv build` was **not** run (see CI/CD section).

## Summary

**No credentials, tokens, keys or DSNs were found in the working tree or in the full git
history.** The history scan is clean. The security story is therefore not "a secret leaked"
but two lesser things: (a) the repo hardcodes Sanger-internal filesystem topology and three
named staff usernames in ~15 places, which publishing discloses; (b) there is *zero* shell
quoting anywhere in the codebase, so Jira- and YAML-sourced strings reach `shell=True`
unquoted — harmless while the only writers are the curation team, a real injection primitive
the moment outsiders can hand a curator a `--yaml` file.

The genuine hard blockers to publication are, in order: **no LICENSE** (organisational),
**`rename-and-orient` pulled from a personal GitHub account via `[tool.uv.sources]`** (makes
the package unpublishable to PyPI as written), and **`module load grit`** — four of five
entries in `modules.py` point at an opaque Sanger environment module that is described nowhere,
so an outsider who solves install still cannot run a single real step. The author's own
`TODO/XX_pixi_portability_plan.md` already diagnoses that third one correctly.

What is genuinely good, and should be said plainly: 451 tests; a hand-written, accurate,
Keep-a-Changelog `CHANGELOG.md` with 6 matching git tags (release discipline exists);
`--print-only` and `--dry-run` are unusually strong onboarding affordances for a pipeline
CLI — `--dry-run` alone lets a stranger exercise the whole step/tracking/canonical machinery
on a laptop with no HPC, which most bioinformatics pipelines cannot offer; and
`recuration-canonical-priority.md` is a real design document written for a human reader.
Annotation coverage is ~75% arg / ~77% return with no type checker enforcing it, which is
better than most unchecked codebases.

The most consequential documentation finding: **the project's architecture knowledge lives in
`CLAUDE.md`, a file addressed to an AI assistant.** It is 250-odd lines of accurate, load-bearing
design rationale (canonical resolution, tracker/epilogue contract, `--untracked` semantics, the
dry-run allowlist) that exists nowhere else in human-facing form. A new human contributor's best
available architecture document is the AI's instruction file. That is a real, and fixable, problem.

## Security posture

Nothing critical. Ordered worst-first.

### Git history scan

- 359 commits across all refs.
- `git log -p --all -S <term>` for `password`, `passwd`, `secret`, `api_key`, `apikey`,
  `PRIVATE_KEY`, `credential`: **no hits** except `token`, whose ~10 hits are all the
  domain word "token" (haplotype prefix token in `find_canonical_*`), not auth material.
- No `.pem` / `.key` / `.p12` / `.env` / `.netrc` / `id_rsa` file has ever existed at any path
  in history (`git log --all --name-only` over all paths).
- 7 files were deleted in history: `test.yaml`, `description.md`, `grit/config/settings.py`,
  `grit/config/environments.py`, `grit/scripts/paf_top_targets_add_top_longest.py`,
  `grit/steps/pre_curation/microchromosome.py`, `docs/superpowers/plans/…`. I read the deleted
  `test.yaml` and `description.md` blobs: synthetic test paths and an early Russian-language
  design note respectively. Nothing sensitive.
- No `.ipynb` has ever been committed, despite `description.md` referencing a
  `notebooks/curatrion_script.ipynb` prototype — that notebook stayed out of the repo. Good.
- History does carry the internal-path/username disclosure below (7× `dz11`, 7× `da16`,
  2× `mh6` under `/nfs/users/nfs_?/`), so removing them from the tip commit would not remove
  them from a published repo.

**Conclusion: the repo is safe to publish from a secrets standpoint.** This is the rare case
where the usual answer is "history rewrite required" and here it genuinely is not.

### Internal infrastructure disclosure

`grit/config/sanger_template.yaml`, `grit/utils/modules.py`, `grit/scripts/*.sh` and six step
modules hardcode Sanger NFS/Lustre paths, the farm head node hostname (`tol22-head2`), the LSF
group name (`team135`), and three staff usernames — including two people's *personal home
directories* being depended on as production code paths
(`/nfs/users/nfs_d/dz11/gitlab/vgp_curation_scripts/…`,
`/nfs/users/nfs_d/dz11/hap_bedgraph.py`, `/nfs/users/nfs_m/mh6/sing.bash`,
`/nfs/users/nfs_d/da16/vgp_curation_scripts/…`). Not a credential; it is an internal-topology
and personnel map, and whether disclosing it is acceptable is Sanger's call, not the author's.

### Command-injection surface as a publication risk

`_run()` (`grit/utils/helpers.py:56,58`) and `_submit_bsub()` both execute
`subprocess.run(cmd, shell=True)`. `grep -rn 'shlex\|quote('` over `grit/` returns **zero
hits** — no value is ever quoted. Concretely:
`blast_contaminants.py:143` interpolates the Jira `species` field into
`f"{LINEAGE_SCRIPT} {cleaned_species}"` with no quoting at all;
`find_reference.py:192` puts it inside weak double quotes, which stops word-splitting but not
`$(…)` or backticks. Today the only writers of those fields are curators, so this is latent.
Published, the trust model inverts: "here, run `grit --yaml this.yaml setup`" becomes remote
code execution as the curator on a farm login node.

### `~/.grit/` and config handling

`grit/config/init.py:write_default_config` uses a bare `config_path.write_text()` — no
`chmod 0o600`, so the config and `grit_registry.json` land at the process umask (typically
0644, world-readable on shared NFS). Contents are non-secret today (username, farm host, email,
NFS paths, plus per-ticket species/ToL-ID/workdir in the registry). The registry does list
pre-publication genome projects by species and ticket, which on a shared home directory is a
mild confidentiality issue rather than a credential one.

### YAML loading

`yaml.safe_load` is used at both load sites (`click_cli.py:100,113`). Correct; no
deserialisation issue.

## Distribution and dependencies

**`requires-python = ">=3.10"` appears to be honest.** I found no 3.11+ syntax or stdlib:
no `match` statements, no `datetime.UTC`, no `tomllib`, no `itertools.pairwise`/`batched`,
no `ExceptionGroup`/`except*`, no `StrEnum`, no `typing.Self`/`Never`/`LiteralString`,
no `hashlib.file_digest`. `X | None` annotations are used throughout but always with
`from __future__ import annotations` in the module. This is unverified against a real 3.10
interpreter, though — CI runs one unpinned `ubuntu-latest` Python, so `>=3.10` is a claim
nothing in the project actually tests.

**Half the declared dependency set is dead:**

| dep | declared | actually used? |
|---|---|---|
| `pyyaml>=6.0` | yes | yes — config + ticket YAML |
| `rich-click>=1.8.0` | yes | yes — whole CLI |
| `rename-and-orient>=1.2.2` | yes | yes, but as a **CLI binary** (`shutil.which("rename-and-orient")`), never imported |
| `biopython>=1.80` | yes | **no** — only `grit/scripts/busco_synteny_format_and_plot.py` imports `Bio`, and that file is a PEP-723 script run via `uv run --script` with its own inline dependency block |
| `requests>=2.28` | yes | **no** — appears only inside the PEP-723 inline blocks of two `grit/scripts/*.py` files |
| `pymysql>=1.0` | yes | **no hits anywhere** in `grit/`, `tests/`, `*.md` or the shell scripts |

So `grit`'s real import-time surface is `pyyaml` + `rich-click`. Three deps — including a MySQL
driver with a compiled/wheel footprint — are installed into every environment for nothing, and
a declared-but-unused DB driver invites the reasonable reader to assume grit talks to a database
it does not talk to.

Version bounds are all lower-only (`>=`), no upper caps and no `!=`. For a leaf application
that is defensible, but combined with a committed `uv.lock` that only `uv sync` honours (not
`pip install -e .`), a `pip` user gets an unbounded resolution.

**`rename-and-orient` is the distribution blocker.** `[tool.uv.sources]` points it at
`git+https://github.com/zilov/rename-and-orient` with **no `rev`/`tag`** — a mutable ref.
Three separate problems:

1. `[tool.uv.sources]` is uv-specific. `pip install grit` (which README offers) resolves
   `rename-and-orient>=1.2.2` against PyPI, where it does not appear to be published. So the
   pip path is broken and grit cannot be uploaded to PyPI as written — a PyPI release with an
   unresolvable requirement is a broken release.
2. `uv.lock:575-577` pins the git package at commit `d389cc5…` reporting **version `1.2.0`**,
   while `pyproject.toml` requires `>=1.2.2`. Either the lock is stale relative to the
   constraint or the upstream package's version metadata is behind its tags; in the first case a
   fresh `uv lock`/`uv sync` on a clean clone can fail to resolve. (Not verified — would need
   network.)
3. Single-maintainer personal account, licence unknown, no release cadence. Bus factor 1 on a
   hard runtime dependency of a Sanger production pipeline.

Two undeclared runtime dependencies also exist: **`uv` itself** must be on `PATH` on the
compute nodes (`fastga_synteny.py:94` and `busco-synteny.sh:101` invoke `uv run --script`
inside bsub jobs), and **`ruby`** for the two `.rb` comparator scripts. Neither is mentioned
in `pyproject.toml`, README or `examples.md`.

`pyproject.toml` metadata is minimal to the point of being unpublishable: no `license`,
no `authors`, no `readme`, no `classifiers`, no `[project.urls]`, no `keywords`. Packaging
of data files is fine — hatchling includes `grit/config/sanger_template.yaml` and
`grit/scripts/*` by default, and CHANGELOG 0.3.4 records that this was already fixed once.

## Install path for an outsider

Walking it as a stranger with no Sanger account:

1. **`git clone`** — README says `git+ssh://git@github.com/zilov/grit.git`, i.e. requires a
   GitHub SSH key and (if the repo is private) access. `examples.md` says
   `git clone https://…` + `uv tool install .`. Two documents, two different install
   commands. First friction, trivially fixable.
2. **`uv sync`** — this is the step most likely to *work*: `pyyaml`/`rich-click`/`biopython`/
   `requests`/`pymysql` all come from PyPI, and `rename-and-orient` comes from a public GitHub
   URL. Risk is the `1.2.0` vs `>=1.2.2` mismatch above. `pip install -e .` will fail, because
   pip does not read `[tool.uv.sources]`.
3. **`grit --help`** — **works with no config at all.** Verified (`./.venv/bin/grit --help`,
   exit 0, full rich-click command list). Config loading is lazy, only in `build_context()`.
   Genuine strength.
4. **`grit init`** — writes `~/.grit/grit_curation_config.yaml` from `sanger_template.yaml`,
   which is 100% Sanger paths including `gritjiraissue_path` pointing at *one named person's
   home directory*, with a comment saying it is "temporarily pinned … while the shared version
   is mid-refactor". There is no non-Sanger template and no documentation of which fields
   matter. An outsider gets a config file where every value is wrong and no guidance on what
   to replace them with.
5. **First real command** — `-t RC-1234` needs `GritJiraIssue`, injected by
   `sys.path.insert(0, cfg.gritjiraissue_path)` then `import GritJiraIssue`
   (`context.py:238-239`). That library is not in the repo, not on PyPI, not documented beyond
   "the module used to fetch ticket YAML from Jira", and lives on Sanger NFS. **Hard wall for
   any Jira-driven use.**
6. **The `--yaml` escape hatch** works around #5 — `--yaml ticket.yaml` skips Jira entirely,
   and `tests/fixtures/*.yaml` provide two real ticket shapes to copy. But `--yaml` is not
   documented anywhere as *the* non-Sanger entry point; it reads as a testing convenience.
7. **`--print-only`** then gets a stranger all the way to seeing the exact shell commands grit
   would run. This is the single best onboarding affordance in the project and neither README
   nor `examples.md` frames it that way.
8. **`--dry-run`** goes further: an isolated `~/.grit/dry_run/` sandbox, placeholder outputs,
   real tracker state, 20+ supported commands. A stranger can drive the entire post-curation
   chain on a laptop and watch canonical resolution behave. This is a real, unusual strength
   and it is documented **only in `CLAUDE.md`** and in a comment block inside
   `tests/local_smoke_test.sh`. Not in README. Not in `examples.md`.
9. **A real run** — blocked regardless, at `modules.py`: `GRIT`, `PRETEXT_TO_ASM`,
   `CURATIONPRETEXT` and `FASTGA` all resolve to `module load grit`, an internal Lmod module
   whose contents (pretext-to-asm, curationpretext, FastGA, …) are listed nowhere. Plus
   `bsub`/LSF, plus five absolute `/software/grit/…` and `/nfs/users/…` script paths, plus
   `singularity` and a specific `busco.sif` on NFS, plus `/lustre/…/busco/latest/lineages`.
   There is no conda/pixi/container environment definition in the repo. `TODO/XX_pixi_portability_plan.md`
   is an unstarted plan (in Russian) that names this correctly.

`tests/local_smoke_test.sh` (read, not run) is the closest thing to an integration harness and
it is **currently broken**: lines 66, 67 and 80 invoke `add-gap-track`, `add-telo-track` and
`validate-files`, all three of which are commented out of `click_cli.py` ("Not yet tested via
CLI / not current — disabled for initial release"). With `set -euo pipefail` at line 42, the
script dies at line 66 before reaching anything else, including the dry-run section that
CLAUDE.md names as the main regression check for canonical-FASTA logic. It also uses
`grit --config <path>`, a group flag documented in neither README nor `examples.md`.

**Net: an outsider gets as far as `--print-only`/`--dry-run` and stops there.** That is further
than most HPC pipelines allow, and it is entirely undocumented.

## Open-source readiness checklist

| item | present? | blocker? |
|---|---|---|
| LICENSE file | **no** | **blocker** — organisational (Sanger IP policy) |
| `license` field in `pyproject.toml` | no | blocker (follows LICENSE) |
| `authors` / `[project.urls]` / `classifiers` / `readme` in metadata | no | friction |
| README | yes, Sanger-internal in framing | friction |
| CONTRIBUTING.md | **no** | friction |
| CODE_OF_CONDUCT.md | **no** | friction |
| Issue / PR templates (`.github/ISSUE_TEMPLATE`, `PULL_REQUEST_TEMPLATE.md`) | **no** | friction |
| `SECURITY.md` / vulnerability contact | **no** | friction |
| CHANGELOG.md | **yes — good**, Keep-a-Changelog, accurate, maintained `[Unreleased]` | no |
| Git tags | **yes** — `v0.3.0`…`v0.3.5`, matching `version = "0.3.5"` | no |
| GitHub Releases / release automation | no (no publish workflow, tags appear hand-made) | friction |
| Version single-sourced | yes (`click.version_option(package_name="grit")`) | no |
| CITATION.cff | **no** | **blocker for adoption** — this is a research tool |
| Zenodo DOI / archived release | **no** | blocker for adoption |
| API stability statement | **no** — a documented Python API (`README` §"Python API") with 0.x version and no stability note | friction |
| Installable off-Sanger | **no** — `module load grit`, `GritJiraIssue`, absolute NFS script paths | **blocker** — code, and large |
| PyPI-publishable as written | **no** — `[tool.uv.sources]` git dep | **blocker** — code |
| Conceptual "what is genome curation" docs | **no** | friction, significant |
| Architecture doc for humans | **no** — it is `CLAUDE.md` | friction, significant |
| Dependency licence audit of the dep tree | no | organisational |

## Documentation assessment

**For the Sanger curator using it today: good.** `examples.md` (158 lines) is a well-judged
task-ordered walkthrough — standard workflow, optional steps, `grit status` output — that a new
team member could follow. `recuration-canonical-priority.md` (226 lines) is the standout: a
proper design document with a stated model ("one flat pool, freshest wins"), a curator decision
path, and a flowchart, written for a human. The `grit --help` output is clean and every command
carries a one-line description. `CHANGELOG.md` is genuinely informative.

**For an external scientist evaluating it: nothing.** There is no document anywhere that says
what genome curation *is*, what problem manual curation in PretextView solves, why a curated
assembly needs HiC remapping and QV, or what "canonical FASTA" means to a biologist. README
line 3 is `Genome curation pipeline CLI and library for the Tree of Life curation team.` and
every subsequent sentence presumes Jira ticket IDs, farm hosts, NFS layout and the internal step
vocabulary. An evaluator cannot tell from the repo whether grit does something they need. For a
research tool seeking citation and adoption, this is the gap that matters most after LICENSE.

**`CLAUDE.md` is doing architecture documentation's job.** Stated plainly, because the brief
asked: the canonical-priority model, the `CurationContext` pattern, the `_state_update_epilogue`
bsub-completion contract (including the subtle "this only works when grit's own bsub is what LSF
tracks" caveat), the exact `--untracked` finish-record semantics and the bug they fix, the
synchronous-tracked-step protocol, and the complete `--dry-run` allowlist all exist **only** in
`CLAUDE.md`. It is accurate and well-written. It is also addressed to an AI assistant, lives at
a filename that signals "tool config, not documentation", mixes normative style rules
("`log.*` not `print()`", "minimal docstrings") with load-bearing design invariants, and would
read to an external contributor as something they should not have to read. On publication the
project's design knowledge is either in a file humans skip, or it is nowhere.

**The mandated "minimal, one line" docstring convention has a visible cost.** It is not applied
uniformly — `helpers.py`'s `find_canonical_*` and `rename_and_orient.py`'s public functions carry
substantial multi-paragraph docstrings, `modules.py:module_cmd` has a full Args/Returns/Raises
docstring with a doctest, while most step internals get one line. The convention explicitly
forbids recording *why* ("no historical context about bugs/commits that motivated it"), which
pushes rationale into commit messages — invisible to anyone reading the code, and the very
rationale that `CLAUDE.md` then has to re-state centrally. The result is that the "why" for a
given invariant is in a commit message, `CLAUDE.md` and a `TODO/done/*.md` file, but never next
to the code it constrains.

Docstring/annotation discipline itself is respectable: ~75% of the 230 functions in `grit/`
have every argument annotated, ~77% annotate their return type. Nothing enforces it.

## CI/CD gaps

`.github/workflows/ci.yml` is 26 lines: checkout → setup-uv → `uv sync` → `ruff check` →
`ruff format --check` → `pytest tests/ -v`, on `pull_request` and `push: [main]`. What runs,
runs well; almost nothing runs.

- **One Python, and it is unpinned.** No `matrix`, no `python-version` input to setup-uv, no
  `.python-version` file. `ubuntu-latest`'s default Python is whatever GitHub ships this month.
  `requires-python = ">=3.10"` is therefore an untested assertion — and a silent 3.12+-only
  construct would pass CI and break a curator on an older farm Python.
- **No coverage measurement or gate.** 451 tests exist; nobody knows what fraction of 9,483
  lines they touch, so nobody can tell whether a PR reduced coverage.
- **No type checking, and no config for one.** No `mypy.ini`, no `[tool.mypy]`, no
  `[tool.pyright]`, no `pyrightconfig.json`. ~75% annotation coverage is therefore decoration:
  the annotations can drift out of truth with no signal. This is the highest-value-per-effort CI
  addition available, precisely *because* the annotations already exist.
- **No `[tool.pytest.ini_options]`** anywhere — no `testpaths`, no `--strict-markers`, no
  `filterwarnings`. Bare `pytest` from the repo root works by luck of layout.
- **`ruff` lint is `select = ["E", "F", "I"]`** — pycodestyle/pyflakes/isort only. No `B`
  (bugbear), no `UP` (pyupgrade, which is what would actually police the 3.10 floor), no `S`
  (bandit — which is what would flag the unquoted `shell=True` interpolations above), no `ANN`.
- **No dependency audit** — no `pip-audit`, no Dependabot config, no `uv lock --check` step, so
  `uv.lock` can drift from `pyproject.toml` unnoticed (and, per the Distribution section, may
  already have).
- **No build/packaging check.** CI never runs `uv build`, never installs the built wheel, and
  never verifies that `grit/config/sanger_template.yaml` and `grit/scripts/*` land inside it —
  which is exactly the class of bug CHANGELOG 0.3.4 records as having already shipped once
  ("Bundled script paths … resolve correctly when grit is installed as a package"). It can
  regress silently. **I did not run `uv build`**: it creates an untracked `dist/` directory
  which the repo's 2-line `.gitignore` does not cover, so it is not a pure read. Static reading
  of the hatchling config says the wheel should be correct; that is an inference, not a check.
- **No security scanning** — no CodeQL, no secret scanning workflow, no `gitleaks`.
- **No release automation** — 6 tags and a maintained CHANGELOG with no workflow tying a tag to
  a build, a GitHub Release, or an artifact. Every release is manual and undocumented (no
  RELEASING.md).
- **CI does not cover the smoke test**, which is fine (it needs the farm) — but nothing else
  covers the dry-run scenario chain either, so the broken-since-disable state of
  `local_smoke_test.sh` went unnoticed.

## Repository hygiene

**`.gitignore` is two lines** (`__pycache__`, `.worktrees/`). `.venv/`, `.pytest_cache/`,
`.ruff_cache/`, `.claude/` and `.superpowers/` are all present in the working tree and all
currently ignored — but *not by this repo*. `.venv/`, `.pytest_cache/` and `.ruff_cache/`
self-ignore via tool-generated inner `.gitignore` files; `.claude/worktrees/` and
`.claude/settings.local.json` are covered by the author's machine-local `.git/info/exclude`
(11 `**/.claude/*` patterns), which does **not** travel with a clone. There is no
`core.excludesFile` configured. So on a fresh clone by a contributor, `.claude/` and any
`.superpowers/` output become untracked-and-unignored — one `git add -A` from being committed.
`git status` is clean today only because of one machine's local exclude file.

**Nothing inappropriate is currently tracked.** `git ls-files` is 77 `.py`, 40 `.md`, 4 `.yaml`,
4 `.sh`, 1 `.yml`, 1 `.toml`, `uv.lock`, and 8 small test fixtures (2 `.agp`, `.csv`, `.qv`,
`.stats`, `.log`, and a BUSCO sex-call marker file). Largest tracked file is `uv.lock` at 128 KB.
No notebooks, no binaries, no data dumps. Clean.

**`TODO/` — 35 tracked files, and the tradeoff is real.** This is the project's actual
design-decision record: `TODO/done/44_canonical_fa_flat_mtime_priority.md`,
`45_dry_run_mode.md`, `46_dry_run_remaining_steps.md` and friends are referenced *by name* from
`CLAUDE.md` and from `tests/local_smoke_test.sh`'s comments as the place where rationale lives.
Deleting it would delete the only written "why" for the canonical-resolution and dry-run designs.
Publishing it as-is has three costs: **9 of the 35 files contain Cyrillic** (planning notes in
Russian — `XX_pixi_portability_plan.md`, `done/28_step_tracking.md`, `done/29_add_ticket_list.md`,
`done/32_control_plane.md`, `done/tasks.md`, three `done_2x_*` files,
`done/wasted_21_cli_parsing_plan.md`), which an external contributor cannot read; filenames like
`wasted_21_…` and `TODO/tiny.md` read as scratch; and `TODO/31_server_cli_testing_plan.md` plus
`TODO/claude/` are internal process artefacts. The right disposition is a decision, not a
deletion: promote the design records that `CLAUDE.md` cites into a human-facing `docs/design/`
in English, and let the rest be internal.

## Findings

**PKG-01** | severity: major | confidence: confirmed | `pyproject.toml:19-20`, `uv.lock:575-577`
| claim: `rename-and-orient` is declared as a PyPI requirement but sourced from an unpinned git
ref on a personal GitHub account via the uv-only `[tool.uv.sources]` table.
| failure scenario: `pip install -e .` (offered in README line 22) fails to resolve, and `grit`
can never be uploaded to PyPI as written because the requirement is unresolvable there; the
locked ref reports version `1.2.0` against a `>=1.2.2` constraint, so a fresh `uv lock` may also
fail; upstream is one person's account with unknown licence, so a force-push or deletion breaks
every grit install including production Sanger ones.
| effort: M | blast radius: cross-module | debt quadrant: deliberate-reckless
| open-source impact: blocker

**PKG-02** | severity: major | confidence: confirmed | `grit/utils/modules.py:23-33`, `grit/steps/**`
| claim: All real execution is gated on Sanger-only infrastructure — four of five `MODULE_VERSIONS`
entries resolve to the undocumented internal Lmod module `grit`, plus `bsub`, `singularity`, a
`busco.sif` on NFS, `/lustre/…/busco/latest/lineages`, and five absolute `/software/grit/…` and
`/nfs/users/…` script paths.
| failure scenario: An external bioinformatician who successfully installs grit cannot execute a
single real step and cannot even discover which tools to install, because the contents of
`module load grit` are listed nowhere in the repo; there is no conda/pixi/container environment
definition. `TODO/XX_pixi_portability_plan.md` states the problem and is unstarted.
| effort: L | blast radius: cross-module | debt quadrant: deliberate-prudent
| open-source impact: blocker

**PKG-03** | severity: major | confidence: confirmed | repo-wide (no `LICENSE`; `pyproject.toml`
has no `license` field)
| claim: There is no licence of any kind, in the repo root or in package metadata.
| failure scenario: Anyone who finds the GitHub URL has no legal right to use, modify or
redistribute grit; no downstream project or institution can depend on it; PyPI upload has no
licence classifier. Wellcome Sanger Institute IP policy makes the choice an organisational
decision, not something the author can settle in a commit.
| effort: S (once decided) | blast radius: organisational | debt quadrant: deliberate-prudent
| open-source impact: blocker

**SEC-01** | severity: major | confidence: confirmed | `grit/utils/helpers.py:56,58`;
`grit/steps/optional/blast_contaminants.py:143`; `grit/steps/pre_curation/find_reference.py:192`
| claim: Every command is executed via `subprocess.run(shell=True)` and `shlex.quote` is used
nowhere in the codebase, so Jira- and YAML-sourced values (notably `species`) are interpolated
into shell strings unquoted or in weak double quotes.
| failure scenario: Post-publication the trust boundary inverts: a stranger sends a curator a
`ticket.yaml` (an explicitly supported input, `--yaml`) with a shell metacharacter in `species`,
and `grit setup --yaml` executes arbitrary code as that curator on a Sanger farm login node with
their NFS credentials. Equally reachable by anyone able to edit a Jira ticket field.
| effort: M | blast radius: cross-module | debt quadrant: inadvertent-reckless
| open-source impact: blocker

**SEC-02** | severity: minor | confidence: confirmed | `grit/config/sanger_template.yaml:5,8,14,23`;
`grit/utils/modules.py:_MODULES_INIT`; `grit/scripts/sex-matcher.sh:3,12-14`;
`grit/scripts/busco-synteny.sh:9,11`; `grit/steps/post_curation/microchromosome_combine.py:27`;
`grit/steps/pre_curation/microchromosome_second_shot.py:29`;
`grit/steps/pre_curation/add_pretext_view_tracks.py:24,78`;
`grit/steps/optional/busco_curated.py:28`; and git history (7× `dz11`, 7× `da16`, 2× `mh6`)
| claim: Sanger-internal filesystem topology, the farm head hostname `tol22-head2`, the LSF group
`team135`, and three named staff usernames — including two colleagues' personal home directories
used as production code paths — are hardcoded in the tree and in history.
| failure scenario: Publishing discloses internal infrastructure layout and personnel identifiers;
because they are in history, scrubbing the tip commit does not remove them. Independently, the
production pipeline breaks the day `dz11`, `da16` or `mh6` leaves and their home directory is
reclaimed — `add_pretext_view_tracks.py` depends on a loose `hap_bedgraph.py` in one person's
`$HOME`.
| effort: M | blast radius: cross-module | debt quadrant: deliberate-reckless
| open-source impact: friction (disclosure acceptability is organisational)

**SEC-03** | severity: minor | confidence: confirmed | `grit/config/init.py:22-23`
| claim: `~/.grit/grit_curation_config.yaml` and `grit_registry.json` are written with a bare
`write_text()` at the process umask, with no `chmod 0o600`.
| failure scenario: On shared Sanger NFS home directories the ticket registry — which lists
pre-publication genome projects by species, ToL ID and workdir — is world-readable to every farm
user. No credential is exposed today, but the file is the natural place a future Jira token
would land.
| effort: S | blast radius: file | debt quadrant: inadvertent-prudent | open-source impact: none

**SEC-04** | severity: minor | confidence: confirmed | git history (359 commits, all refs)
| claim: The full history is free of credentials — no hits for password/passwd/secret/api_key/
apikey/PRIVATE_KEY/credential via `git log -p --all -S`, no `.pem`/`.key`/`.env`/`.netrc`/`id_rsa`
path ever committed, no notebook ever committed, and the 7 deleted files contain only synthetic
paths and an early design note.
| failure scenario: None — recorded as a positive finding so the publication decision does not
stall on an unfounded fear of history rewriting. No `git filter-repo` pass is needed.
| effort: S | blast radius: file | debt quadrant: deliberate-prudent | open-source impact: none

**PKG-04** | severity: major | confidence: confirmed | `grit/core/context.py:237-239`;
`grit/config/sanger_template.yaml:23`
| claim: Jira-driven operation depends on `GritJiraIssue`, a library that is not in the repo, not
on PyPI, and injected by `sys.path.insert` from a path that currently points at one named
person's home directory with a comment saying it is a temporary pin.
| failure scenario: The primary documented invocation (`grit setup -t RC-1234`) is unreachable for
anyone outside Sanger and undocumented as to what interface a replacement would need to satisfy;
the `--yaml` escape hatch exists but is presented as a testing convenience, not as the supported
non-Sanger entry point.
| effort: M | blast radius: cross-module | debt quadrant: deliberate-prudent
| open-source impact: blocker

**DOC-01** | severity: major | confidence: confirmed | `CLAUDE.md` (whole file)
| claim: The project's architecture documentation is a file addressed to an AI assistant; the
canonical-resolution model, the bsub-epilogue completion contract, `--untracked` finish semantics,
the synchronous-tracked-step protocol and the `--dry-run` allowlist exist in human-readable form
nowhere else.
| failure scenario: A new human contributor (or a returning maintainer in a year) has no
architecture document; the best available one is named `CLAUDE.md`, mixes normative style rules
with load-bearing invariants, and reads as tool configuration a contributor would reasonably skip.
Publishing the repo publishes the design knowledge in a form aimed at the wrong reader.
| effort: M | blast radius: cross-module | debt quadrant: inadvertent-prudent
| open-source impact: friction

**DOC-02** | severity: major | confidence: confirmed | `README.md:1-9`, `examples.md` (whole file)
| claim: No document explains what genome curation is, what problem the pipeline solves, or what
its outputs mean; all documentation presumes Sanger context (Jira tickets, farm hosts, NFS layout,
internal step vocabulary).
| failure scenario: An external scientist landing on the repo cannot determine whether grit does
something they need, so they do not evaluate it — the adoption funnel ends at README line 3.
Combined with the absence of CITATION.cff/DOI, a published grit is uncitable *and*
ununderstandable, which for a research tool is the same as unpublished.
| effort: M | blast radius: organisational | debt quadrant: inadvertent-prudent
| open-source impact: blocker (for adoption)

**DOC-03** | severity: minor | confidence: confirmed | `README.md:63-70`, `examples.md`, `CLAUDE.md`
| claim: `--dry-run` — the project's strongest onboarding affordance, a full isolated sandbox
covering 20+ commands — is documented only in `CLAUDE.md` and a comment block in
`tests/local_smoke_test.sh`, and never in README or `examples.md`; README also mislabels
`--print-only` as "Dry run".
| failure scenario: The one path by which an outsider could exercise grit's real logic on a laptop
without HPC access is invisible to them, and the terminology collision (`--print-only` captioned
"Dry run" next to an actual `--dry-run` flag) actively misleads.
| effort: S | blast radius: file | debt quadrant: inadvertent-prudent
| open-source impact: friction

**DX-01** | severity: major | confidence: confirmed | `tests/local_smoke_test.sh:42,66,67,80`
| claim: The end-to-end smoke test dies at line 66 under `set -euo pipefail`, because
`add-gap-track`, `add-telo-track` and `validate-files` are commented out of `click_cli.py:158-163`.
| failure scenario: Nobody can run the documented integration check, including its `--dry-run`
section that `CLAUDE.md` names as the required regression test after touching
`find_canonical_fa`/`find_canonical_chr_list`/`find_canonical_haplotigs` — so the highest-risk
logic in the codebase currently has no runnable end-to-end guard, and the breakage went unnoticed
because CI does not run this script.
| effort: S | blast radius: module | debt quadrant: inadvertent-reckless
| open-source impact: friction

**PKG-05** | severity: minor | confidence: confirmed | `pyproject.toml:10-17`
| claim: Three of six declared dependencies are unused by the installed package — `pymysql` has
zero occurrences anywhere in the repo, and `biopython`/`requests` appear only inside the PEP-723
inline dependency blocks of `grit/scripts/*.py` files that run under their own `uv run --script`
environments.
| failure scenario: Every install pays for a MySQL driver and Biopython it never imports (slower,
larger, more CVE surface for a dependency audit to flag), and a reader auditing grit for data
handling reasonably concludes it connects to a MySQL database, which it does not. grit's real
import surface is `pyyaml` + `rich-click`.
| effort: S | blast radius: file | debt quadrant: inadvertent-reckless
| open-source impact: friction

**PKG-06** | severity: minor | confidence: plausible | `pyproject.toml:9`, `.github/workflows/ci.yml:9-11`
| claim: `requires-python = ">=3.10"` is consistent with the source (no 3.11+ syntax or stdlib
found — no `match`, `datetime.UTC`, `tomllib`, `pairwise`/`batched`, `except*`, `StrEnum`,
`typing.Self`) but is tested by nothing: CI pins neither a Python version nor a matrix and rides
`ubuntu-latest`'s rolling default.
| failure scenario: The floor silently rots — a contributor adds a 3.12-only construct, CI passes,
and a curator on an older farm Python gets a `SyntaxError` at import; equally, the floor may
already be conservative and nobody can tell. `ruff`'s `UP` rules, which would police this, are
not enabled (`select = ["E","F","I"]`).
| effort: S | blast radius: file | debt quadrant: inadvertent-prudent
| open-source impact: friction

**CI-01** | severity: major | confidence: confirmed | `.github/workflows/ci.yml`, `pyproject.toml:34-38`
| claim: CI has no type checking despite ~75% argument / ~77% return annotation coverage across
230 functions, and no mypy/pyright configuration exists anywhere in the repo.
| failure scenario: The annotations are decorative — they can and will drift from reality with no
signal, so a contributor reading `find_canonical_fa(ctx, hap_prefix) -> Path | None` cannot trust
it. This is the highest value-per-effort gate available precisely because the annotations are
already written; every day without it is annotation quality being lost.
| effort: M | blast radius: cross-module | debt quadrant: inadvertent-prudent
| open-source impact: friction

**CI-02** | severity: minor | confidence: confirmed | `.github/workflows/ci.yml`
| claim: CI never builds or installs the package, so nothing verifies that `grit/config/sanger_template.yaml`
and `grit/scripts/*` are present in the wheel.
| failure scenario: This exact bug already shipped once — CHANGELOG 0.3.4 records "Bundled script
paths (fastga, sex-matcher, busco-synteny) resolve correctly when grit is installed as a package
rather than run from a clone" — and can regress undetected, breaking `uv tool install` users
(the README-recommended path) while passing all 451 tests, which run from the clone. I did not run
`uv build` to check: it writes an untracked `dist/` that the 2-line `.gitignore` does not cover,
so it is not a read-only operation.
| effort: S | blast radius: module | debt quadrant: inadvertent-reckless
| open-source impact: friction

**CI-03** | severity: minor | confidence: confirmed | `.github/workflows/ci.yml`
| claim: No coverage measurement, no dependency audit (`pip-audit`/Dependabot), no
`uv lock --check`, no secret scanning, no release automation, and no `[tool.pytest.ini_options]`.
| failure scenario: `uv.lock` can drift from `pyproject.toml` unnoticed — and per PKG-01 the
locked `rename-and-orient` version already appears to contradict the declared constraint, exactly
the drift a lock check would have caught; a reviewer cannot see whether a PR lowered coverage of
9,483 lines; and each of the 6 releases was a manual, undocumented act with no RELEASING.md.
| effort: M | blast radius: module | debt quadrant: inadvertent-prudent
| open-source impact: friction

**HYG-01** | severity: minor | confidence: confirmed | `.gitignore` (2 lines), `.git/info/exclude`
| claim: `.gitignore` covers only `__pycache__` and `.worktrees/`; `.claude/` and `.superpowers/`
are ignored solely via the author's machine-local `.git/info/exclude`, and `.venv/`/`.pytest_cache/`/
`.ruff_cache/` only via tool-generated inner `.gitignore` files — none of which travel with a clone.
| failure scenario: The first contributor to clone and run `uv sync` sees `.claude/` and any agent
scratch output as untracked-and-unignored, and one `git add -A` commits an AI assistant's local
settings and worktree state into a public repository. `git status` is clean today only because of
one machine's local exclude file.
| effort: S | blast radius: file | debt quadrant: inadvertent-reckless
| open-source impact: friction

**HYG-02** | severity: minor | confidence: confirmed | `TODO/` (35 tracked files, 9 containing Cyrillic)
| claim: `TODO/` is simultaneously the project's only written design-decision record — cited by
name from `CLAUDE.md` and `tests/local_smoke_test.sh` — and a folder of internal planning scratch,
9 files of which are in Russian, with filenames like `wasted_21_cli_parsing_plan.md` and
`XX_pixi_portability_plan.md`.
| failure scenario: Deleting it before publication destroys the only recorded rationale for the
canonical-resolution and dry-run designs (`done/44_…`, `done/45_…`, `done/46_…`), leaving the code
unexplainable; publishing it as-is hands external contributors a design record they cannot read
and internal process artefacts (`TODO/31_server_cli_testing_plan.md`, `TODO/claude/`) they should
not have. Either default is wrong; it needs a per-file decision.
| effort: M | blast radius: organisational | debt quadrant: inadvertent-prudent
| open-source impact: friction

**PKG-07** | severity: minor | confidence: confirmed | `README.md:13-23` vs `examples.md:3-9`;
`pyproject.toml:5-17`
| claim: README and `examples.md` give different, mutually inconsistent install instructions
(`uv tool install "grit @ git+ssh://…"` vs `git clone https://… && uv tool install .`), README
offers a `pip install -e .` path that cannot work (PKG-01), and `pyproject.toml` carries no
`authors`, `readme`, `classifiers` or `[project.urls]`.
| failure scenario: A newcomer's very first command is a coin flip — the SSH variant additionally
requires a configured GitHub SSH key and repo access — and a published PyPI page would show no
description, no homepage, no author and no licence.
| effort: S | blast radius: file | debt quadrant: inadvertent-prudent
| open-source impact: friction

**PKG-08** | severity: minor | confidence: confirmed | repo-wide (no `CITATION.cff`, no DOI)
| claim: No citation metadata of any kind: no `CITATION.cff`, no Zenodo archive, no DOI, no
"how to cite" section, and no API stability statement for the documented Python API on a 0.x version.
| failure scenario: A group that adopts grit for a published assembly cannot cite it, so grit
accrues no academic credit and the adoption incentive for other genome-curation teams is absent;
separately, `README` §"Python API" advertises importable functions with no statement about whether
`CurationContext`'s signature is stable, so any external Python user is building on sand.
| effort: S | blast radius: organisational | debt quadrant: inadvertent-prudent
| open-source impact: blocker (for adoption)

**PKG-09** | severity: minor | confidence: confirmed | `grit/steps/optional/fastga_synteny.py:94`;
`grit/scripts/busco-synteny.sh:101`; `grit/steps/optional/blast_contaminants.py:32`;
`grit/steps/pre_curation/find_reference.py:25`
| claim: Two runtime dependencies are undeclared anywhere: `uv` must be on `PATH` on compute nodes
(`uv run --script` is invoked from inside bsub jobs) and `ruby` is needed for the two `.rb`
comparator scripts.
| failure scenario: A site that installs grit with plain `pip` onto a cluster gets a runtime
failure deep inside a submitted LSF job — after the queue wait — with a `uv: command not found`
that no documentation predicts.
| effort: S | blast radius: module | debt quadrant: inadvertent-prudent
| open-source impact: friction

## Organisational decisions required

These cannot be solved in code. They need to go up the chain.

1. **Does Wellcome Sanger Institute permit publishing `grit` at all, and under which licence?**
   (PKG-03) Nothing else on this list matters until this is answered. It determines the LICENSE
   file, the `pyproject.toml` `license` field, the PyPI classifier, and whether the git history
   can be published as-is.
2. **Is disclosure of internal infrastructure acceptable?** (SEC-02) Publishing reveals NFS/Lustre
   layout, the farm head hostname, the LSF group, and three staff usernames — and because they are
   in history, a tip-commit cleanup does not remove them. If disclosure is *not* acceptable, the
   decision is "history rewrite before publication", which is a much larger piece of work than
   editing the current files. Get the answer before writing any code.
3. **Consent from the two named colleagues** (`mh6`, `da16`) whose personal home-directory paths
   and scripts are hardcoded into grit and would become public, independent of #2.
4. **Ownership and licence of `rename-and-orient`** (PKG-01). It is a hard runtime dependency on a
   personal GitHub account with no stated licence. Decide whether it moves into a Sanger/ToL org,
   gets published to PyPI, or gets vendored — a technical fix is impossible until someone decides
   who owns it.
5. **Who maintains the published project, and under what support commitment?** This drives
   CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.md and issue templates. Writing those files is trivial;
   committing an institution to answering the issues they invite is not.
6. **Citability**: does this get a Zenodo DOI, a paper, or both? (PKG-08) For a Tree of Life tool
   seeking external adoption, someone has to decide whether grit is citable software, and that is
   a group/institutional call.
7. **Scope of the split**: the stated goal is "portable core + Sanger-specific part". The line has
   to be drawn by someone who knows which of the ~15 hardcoded internal paths represent
   Sanger-specific *policy* versus merely un-parameterised *code* — that is a domain decision, and
   PKG-02's effort estimate depends entirely on where it lands.
8. **Dependency licence audit** of the transitive tree, if publication proceeds — a compliance
   task, not an engineering one.
9. **`TODO/` disposition** (HYG-02): a per-file publish/withhold/translate decision on the
   project's own design record. The author can execute it, but should not have to guess whether
   internal planning notes are publishable.
