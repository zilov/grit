# Phase 2 / C — Port contracts

Design of the ports-and-adapters seam for `grit`, given Phase 1's settled
verdicts (`TODO/49`), the remediation queue and scope decision (`TODO/50`), the
125-seam inventory (`TODO/claude/assessment/04`), the orchestration verdict
(`07`) and the canonical spec (`recuration-canonical-priority.md`).

Scope: interface shape, semantics, invariants, error model, reference adapter,
and the conformance suite per port. **Not** in scope here: the migration
roadmap (the consolidation owns it), packaging/entry points/site profiles
(another agent), and the per-dependency decision about *which* portable tool
replaces a Sanger one (another agent — this report designs only the shape of
the declaration those substitutions plug into).

Read-only exercise: no source file was modified.

## Summary

Six contracts, one of which turns out not to be a port:

| # | Contract | Verbs | Seams absorbed | Kind |
|---|---|---|---|---|
| 1 | `ExecutionBackend` | `submit`, `poll`, `kill`, `job_workdir`, `render` (+ `describe_failure`) | 24 (Port 1) + `result_parsers`' LSF regexes | port |
| 2 | `ToolProvider` | `resolve`, `check` | 27 (Port 2) incl. the 14 hardcoded tool paths | port |
| 3 | `MetadataSource` | `fetch` | 16 (Port 3) | port |
| 4 | `StorageLayout` | 7 pure functions (paths, names, haplotype roles, taxonomy) | ~20 of 34 (Port 4) | port |
| 5 | `ReleaseTarget` | `validate`, `publish`, `finalize` | 11 (Port 5) | port |
| 6 | `StepDecl` (capability declaration) | data, not behaviour | the six duplicated step registries + the pre-flight gap | **collapsed** — a declaration read by ports 1/2/4, not a swappable port |

Three structural results fall out of the shapes rather than being bolted on:

1. **One value object carries the ports.** `CurationContext` gains a single
   field, `env: Environment`, holding the five adapters. Steps reach the
   environment through `ctx`, never by module-level import. This is the fix
   report 04 asks for ("`CurationContext` is a container of *values*, not
   *behaviours*, so there is no seam through which to swap an executor"), it
   preserves `CurationContext` as the project's one injected value object, and
   it is simultaneously the answer to `TEST-02`: the tests' seam becomes
   `ctx.env.*` instead of 147 private module attributes.
2. **Reconcile-once is structural, not disciplinary.** Completion detection
   moves inside the ExecutionBackend contract; `RunTracker.finish()` acquires
   exactly one legal caller (`domain.reconcile`), enforced by a test. The four
   current reconcile implementations become four callers of one function, each
   supplying *evidence* rather than a verdict.
3. **Two hardcoded policies become data without changing.** The canonical
   mtime-pool rule is untouched; its three hardcoded pools become one asset
   table, and the winner is *recorded* as a supersession edge instead of being
   silently re-derived on every call.

One port collapsed (6 into the step declaration), one candidate port was
rejected outright (`RegistryStore`), and one was folded into another
(`JobRenderer` into `ExecutionBackend`). See `## Ports I decided against`.

## Target dependency direction

Today all four packages import from each other and the graph is acyclic at
runtime only because 28 step modules defer `from grit.core.click_cli import
build_context` into function bodies and `helpers.py` defers step imports.

Target, strictly one-way:

```
        grit/cli/            composition root: the ONLY module that
       (click_cli,           constructs adapters and knows they exist
      base_command)
            │
            ▼
        grit/steps/*         step functions + StepDecl; take ctx, call ctx.env.*
            │
            ▼
       grit/domain/          reconcile, canonical resolution, RunTracker,
   (+ grit/core/context)     step catalog, fingerprints, release planning
            │
            ▼
        grit/ports/          Protocols + frozen value objects. stdlib only.
            ▲
            │
      grit/adapters/         lsf/ local/ lmod/ path/ jira/ yamlfile/ tol/ flat/
                             sanger_release/ — each imports ports only
```

Rules that make it checkable (one import-linter/AST test, which nothing guards
today):

- `grit/ports/` imports nothing from `grit/`.
- `grit/adapters/*` imports `grit/ports/` only.
- `grit/domain/` imports `grit/ports/` only — never `grit/steps/`, never
  `grit/adapters/`, never `grit/cli/`.
- `grit/steps/*` imports `grit/ports/` and `grit/domain/` — never `grit/cli/`,
  never another step module (composites take the functions as parameters or the
  composition root wires them).
- `grit/cli/` may import everything. It is the only place where "which adapter"
  is decided.

### Which cycle each port breaks

| Cycle family | Broken by | How |
|---|---|---|
| `click_cli ↔ steps.*` (×21, via function-local `build_context`) | **Port 3 MetadataSource** | `build_context` exists today only because context construction needs the Jira fetch, which needs `UserConfig`, which the CLI loads. Once metadata is a port, `CurationContext.from_yaml(ticket, TicketMetadata, user_config, env)` is constructible without any CLI type, so `build_context` moves to `grit/cli/` and steps stop importing it. `ARCH-05` closes with it: the "usable from notebooks" contract stops dragging in `rich_click`. |
| `helpers ↔ steps.*` (`_get_step_specs`' 14 lazy imports, `_step_output`'s recurate import) | **Port 6 StepDecl** (+ Port 4) | The canonical resolver and the reconciler stop importing step modules to find `_OUTPUT_SPECS`; they read an injected `StepCatalog`. The catalog is assembled in `grit/steps/__init__.py` (or by the composition root) and passed *down*, so the arrow only ever points one way. |
| `context ↔ registry ↔ helpers` | **Ports 1 + 4** | `registry.py` imports `helpers._check_bjobs`/`_get_step_specs`/`collect_outputs` solely to reconcile jobs — that code leaves `registry` entirely for `domain.reconcile`, which takes an `ExecutionBackend` and a `StepCatalog`. `helpers.py` imports `context` for the canonical resolvers, which become `domain` functions over a `StorageLayout` + catalog. `context` imports `registry`/`run_tracker` inside `from_yaml` to build the tracker — the tracker becomes part of the injected `Environment`. |

Only after all three are broken can `ARCH-02` (split `helpers.py`, 937 LOC /
seven responsibilities) proceed; the ports fix the ordering, which is the point
`TODO/50` makes.

---

## Port 1 — `ExecutionBackend`

The critical port. 24 seams, and the one where completion detection has to move
*inside* the contract because a Slurm or local adapter has neither `bsub -Ep`
nor `bjobs`.

### Interface sketch

```python
# grit/ports/execution.py

class JobState(Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCEEDED = "succeeded"     # the scheduler says the process exited 0
    FAILED    = "failed"        # the scheduler says it exited non-zero / was killed
    KILLED    = "killed"
    FORGOTTEN = "forgotten"     # the scheduler has no record of this id (LSF "gone")
    UNKNOWN   = "unknown"       # the backend could not classify a record it *does* have

class FailureReason(Enum):
    OUT_OF_MEMORY = "out_of_memory"      # TERM_MEMLIMIT & friends
    WALLTIME      = "walltime"
    KILLED        = "killed"
    NONZERO_EXIT  = "nonzero_exit"
    UNKNOWN       = "unknown"

class CompletionMode(Enum):
    SYNCHRONOUS = "synchronous"   # the adapter reconciles before submit() returns
    CALLBACK    = "callback"      # the adapter arranges an out-of-band reconcile call
    POLL_ONLY   = "poll_only"     # only poll() can ever discover completion

@dataclass(frozen=True)
class BackendCapabilities:
    completion_modes: frozenset[CompletionMode]
    requires_shared_install: bool     # the callback needs grit reachable from the worker
    honours_resources: bool           # cores / memory_mb are real, not advisory
    supports_kill: bool
    supports_queues: bool
    supports_accounts: bool

@dataclass(frozen=True)
class JobSpec:
    """Everything scheduler-neutral about one unit of work."""
    name: str                       # step name; used for the scheduler's job name
    shell_command: str              # one composed shell string (see ToolProvider/compose)
    run_dir: Path                   # cwd for the job and the anchor for its logs
    cores: int = 1
    memory_mb: int = 4000
    walltime_min: int | None = None
    stdout: Path | None = None
    stderr: Path | None = None
    queue: str | None = None        # a named partition/queue if the site uses them
    account: str | None = None      # accounting group (LSF -G, Slurm -A)

@dataclass(frozen=True)
class CompletionHook:
    """Pure data describing the reconcile call the backend must arrange."""
    workdir: Path
    step: str
    run_dir: Path
    untracked: bool

@dataclass(frozen=True)
class JobHandle:
    backend: str          # "lsf" | "local" | "slurm" — stored with the id
    job_id: str           # opaque to the domain; non-empty
    run_dir: Path

@dataclass(frozen=True)
class JobStatus:
    handle: JobHandle
    state: JobState
    exit_code: int | None = None
    reason: FailureReason | None = None

class ExecutionBackend(Protocol):
    name: str
    capabilities: BackendCapabilities

    def render(self, spec: JobSpec, hook: CompletionHook | None) -> str:
        """The exact command line submit() would execute. Never executes anything."""

    def submit(self, spec: JobSpec, hook: CompletionHook | None) -> JobHandle:
        """Start the work. Raises SubmissionError; never returns a bogus handle."""

    def poll(self, handles: Sequence[JobHandle]) -> dict[str, JobStatus]:
        """Batch status query, keyed by job_id. Read-only. Raises BackendUnavailable."""

    def kill(self, handle: JobHandle) -> None: ...

    def job_workdir(self, handle: JobHandle) -> Path:
        """Where this job's own logs/scratch live (usually spec.run_dir)."""

    def describe_failure(self, handle: JobHandle) -> FailureReason | None:
        """Best-effort classification from the backend's own logs."""
```

### Semantics

**`render`** exists because `--print-only` is on the preserve list and must keep
printing the real submission line. It is a deviation from report 07's four-verb
shape and is justified by that: the alternative (print-only calling `submit` on
a no-op backend) loses the property that "the printed command is exactly what
would run", which report 04 identifies as the free verification tool for this
whole refactor.

**`submit`** takes a *composed* shell string. grit keeps building the inner
command (`cd {run_dir} && <preamble> && <tool>`); the backend only wraps it. The
backend owns all quoting of that string — which is where today's single-`"…"`
wrap and the `feedback_submit_bsub_quoting` footgun live, and it becomes
testable in one place.

**`hook` is data, not a shell string.** This is the design decision the whole
port turns on. Today the epilogue *is* a string built by
`_state_update_epilogue()`, which embeds `sys.argv[0]`. Instead each adapter
decides how to honour a `CompletionHook`:

- **LSF adapter** — renders `-Ep '<launcher> _state-update --workdir … --step …
  --run-dir … --status $([ $LSB_JOBEXIT_STAT -eq 0 ] && echo success || echo
  failed)[ --untracked]'`, i.e. today's behaviour verbatim. The launcher argv is
  **constructor state**, not `sys.argv[0]`: `LsfBackend(launcher=("…/bin/grit",))`
  or `("pixi","run","--manifest-path",…,"grit")`. It declares
  `requires_shared_install=True`. That is how `PORT-02` is *declared* instead of
  assumed: pre-flight (Port 6) refuses a `SCHEDULED` step when the backend
  requires a shared install and the launcher path is not readable from the
  configured worker view, with an actionable message, rather than every job
  silently sticking on `started` forever.
- **Local adapter** — `CompletionMode.SYNCHRONOUS`. It runs the command, waits,
  and calls the domain reconciler in-process with the real exit code. No
  callback, no shared filesystem, no launcher. `requires_shared_install=False`.
- **Slurm adapter (sketch, not built here)** — `sbatch` has no user-settable
  epilogue on most sites (`--epilog` is typically root-only), so the honest
  declaration is `{CALLBACK, POLL_ONLY}` where CALLBACK is implemented by
  appending `; <launcher> _state-update … --status $?` *inside the batch script
  payload* — which then also requires a shared install — and POLL_ONLY falls back
  to `sacct`/`squeue` in `poll()`. The contract does not pretend these are the
  same thing; `completion_modes` says which the site gets.

**`poll` is read-only and batched.** Batched because today's `bjobs -noheader
<ids>` sweep is one call for all tickets and that property is worth keeping.
Read-only because that is what makes `grit status` stop writing to the registry
(`ARCH-04`): the domain decides whether to act on a status, and only an explicit
reconcile pass writes.

**`FORGOTTEN` vs `UNKNOWN` vs `BackendUnavailable`** is the fix for `CORR-04` /
`PORT1-01`, and it is a contract-level distinction, not an implementation
detail:

- `FORGOTTEN` — the scheduler answered, and it has no record of this id (aged out
  of history). Legitimate; reconcile then decides by outputs alone.
- `UNKNOWN` — the scheduler answered with a state this adapter cannot classify.
  Reconcile does nothing.
- `BackendUnavailable` (raised) — the scheduler could not be reached at all.
  Reconcile does nothing, and the *user is told*. Today `_check_bjobs`
  pre-seeds every id as `"gone"` and swallows every exception, so a `bjobs`
  outage or a non-LSF host silently converts running jobs into failures.

**Externally-scheduled work.** `hic_remapping` scrapes `Job <\d+>` out of
`curationpretext.sh`'s stdout, and `microchromosome_second_shot` blocks on an
external script's own `bsub -K` jobs. Neither is a job grit submitted, so no
backend can poll or hook it. The contract does not paper over this: those steps
declare `completion=CompletionKind.EXTERNALLY_SCHEDULED` (Port 6), which means
reconcile may use **only** the output probe and may never claim a job state.
CLAUDE.md documents this blind spot in prose today; it becomes a declared
property with a different reconcile rule.

### Invariants an adapter must uphold

1. `submit` returns a handle with a non-empty, backend-parseable `job_id`, or
   raises `SubmissionError`. It must never return scheduler stdout as an id
   (`CORR-25`).
2. `render(spec, hook)` executes nothing and, for a given input, equals what
   `submit` would run.
3. `poll` never raises for an id the scheduler has forgotten; it raises
   `BackendUnavailable` when it could not query at all. It never maps "cannot
   query" to a terminal state.
4. `poll`, `render`, `describe_failure` and `job_workdir` perform no writes to
   registry, tracker or workdir.
5. At-least-once completion: for a `CALLBACK` backend, the hook fires at least
   once per finished job. Exactly-once is *not* required, because reconcile is
   idempotent.
6. A backend declaring `honours_resources=False` must not silently drop a memory
   request — the domain surfaces "this backend ignores --memory-mb" once.
7. The backend never consults `print_only`. It is not called in print-only mode;
   `render` is.
8. `job_id` is only meaningful together with `backend`; a handle from one
   backend must never be polled by another (the domain stores both on the run
   record, which today stores a bare `job_id`).

### Error model

```
ExecutionError                 (base; carries the rendered command when safe)
├── SubmissionError            submit failed; the step's run record is finished "failed"
├── BackendUnavailable         the scheduler could not be reached
└── KillFailed
```

No `SystemExit` inside adapters or domain (`ARCH-13`); the CLI is the only layer
that maps an exception to an exit code and a curator-facing message. `_run`'s
discarded stderr (`CORR-12`) becomes part of `SubmissionError`/`ExecutionError`.

### The `local` reference adapter

`LocalBackend(max_parallel=1)`:

- `render` — the composed shell string plus a `cd` into `run_dir`, i.e. the
  command with no wrapper at all.
- `submit` — `subprocess.Popen(shell_command, shell=True, cwd=run_dir)` with
  stdout/stderr to `spec.stdout`/`spec.stderr` (defaulting to
  `run_dir/<name>.out|.err`); waits; writes `run_dir/.grit_exit` with the
  return code; job_id = `str(pid)`; then invokes the domain reconciler
  in-process with `JobStatus(SUCCEEDED|FAILED, exit_code=rc)`.
- `poll` — reads `.grit_exit` if present (terminal), else checks the pid; an
  unknown id is `FORGOTTEN`.
- `kill` — `os.kill`.
- `describe_failure` — `NONZERO_EXIT`, or `OUT_OF_MEMORY` on rc 137.
- capabilities — `{SYNCHRONOUS}`, `requires_shared_install=False`,
  `honours_resources=False`, `supports_kill=True`, no queues, no accounts.

This adapter is what makes "a stranger can drive the whole pipeline on a
laptop" true for real commands, not just `--dry-run` placeholders — and it is the one the
conformance suite runs against in CI.

### Seams absorbed

All 24 Port-1 rows, plus:

- `build_bsub_opts`' whole flag vocabulary → `JobSpec` + the LSF adapter. `queue`
  defaulting to `"normal"` and `group="team135"` (3 sites) become adapter
  configuration, not literals in step files.
- `-K` / `wait=True` is **dropped**: declared but no caller uses it. If a step
  ever needs it, `LocalBackend` already is that semantics.
- `result_parsers.parse_lsf_exit_reason` + `find_lsf_log` → the LSF adapter's
  `describe_failure`; `status.py`'s `TERM_MEMLIMIT ⇒ suggest --bsub-ram` becomes
  `FailureReason.OUT_OF_MEMORY ⇒ suggest --memory-mb`. This keeps the
  `utils/output.py` + `result_parsers.py` split intact — the *genome file*
  parsers stay exactly where they are; only the scheduler-log parsers move,
  because they are LSF syntax by definition.
- `ctx.bsub_ram` / `--bsub-ram` → `ctx.memory_mb` / `--memory-mb`, with
  `--bsub-ram` retained as a hidden alias (see open question 7).
- `helpers._check_bjobs`, `registry._refresh_pending_jobs`,
  `registry._resolve_gone_job`, `status.py`'s bjobs enrichment → `poll` plus the
  single reconciler.

---

## Port 2 — `ToolProvider`

27 seams. `modules.py` is the right shape and the wrong return type, and it
governs 2 of ~20 externally-provided tools.

### Interface sketch

```python
# grit/ports/tools.py

@dataclass(frozen=True)
class ToolRequirement:
    key: str                          # logical tool: "pretext_to_asm", "fastga", "busco"
    binaries: tuple[str, ...]         # what must be on PATH afterwards
    version: str | None = None        # requested spec; None = site default
    optional: bool = False

@dataclass(frozen=True)
class DataRequirement:
    key: str                          # "busco_lineages", "blast_nt", "sex_busco_sets"
    hint: str = ""                    # human text: how to obtain it

@dataclass(frozen=True)
class Provision:
    preamble: tuple[str, ...] = ()    # zero or more shell statements, in order
    wrapper: tuple[str, ...] = ()     # argv prefix, e.g. ("singularity","exec","-B","/lustre",sif)
    env: Mapping[str, str] = MappingProxy({})
    versions: Mapping[str, str] = MappingProxy({})   # resolved concrete versions
    paths: Mapping[str, str] = MappingProxy({})      # resolved data roots by DataRequirement.key

@dataclass(frozen=True)
class Unmet:
    key: str
    what: str                         # "tool" | "data"
    detail: str                       # why it is unmet
    how_to_obtain: str                # the actionable half

class ToolProvider(Protocol):
    name: str
    def resolve(self,
                tools: Sequence[ToolRequirement],
                data: Sequence[DataRequirement] = ()) -> Provision:
        """Everything needed to make these available. Raises ToolUnavailable."""
    def check(self,
              tools: Sequence[ToolRequirement],
              data: Sequence[DataRequirement] = ()) -> list[Unmet]:
        """Pre-flight. No side effects, no execution of the tools themselves."""
```

and, in the domain, the one composer that fixes the arity problem:

```python
# grit/domain/shell.py
def compose(*parts: str | Sequence[str]) -> str:
    """Join non-empty shell statements with ' && '. Empty parts vanish."""
```

### Semantics

**The `PORT-19`/`ABST-02` fix is the return *type*, not the return value.**
Today `module_cmd()` returns `". /etc/profile.d/modules.sh && module purge &&
module load grit"` and 12 call sites write `f"{module_cmd('X')} && …"`, so a
backend needing no preamble cannot return `""` without producing `" && …"`.
`Provision.preamble` is a **tuple of statements** and the join lives in exactly
one function. A zero-preamble provider returns `()` and `compose()` yields a
clean command. The failure mode is eliminated by arity, not by care at 12 sites.

**Call sites become:**

```python
prov = ctx.env.tools.resolve(decl.tools, decl.data)
cmd = compose(prov.preamble, f"cd {run_dir}", f"{' '.join(prov.wrapper)} pretext-to-asm …")
```

**`versions` is load-bearing, not diagnostic.** It is the `software-env` rerun
trigger (see `## Borrowed patterns placement`) and the provenance record that
`PORT2-03` says does not exist today — four of five module keys resolve to a
single *unversioned* module named `grit`, so two curators can get different
`pretext-to-asm` behaviour with identical grit versions and nothing records it.
The Lmod adapter must therefore return either the resolved module version string
or the literal `"unpinned"`; "unpinned" is then visible in `grit status` and in
the run record instead of being invisible.

**`MODULE_VERSIONS`' broken single-source claim.** The table survives as the
Lmod adapter's configuration (one line per logical key — the preserve item is
the *shape*, and it is kept). What changes is that the requirement moves to the
step's `StepDecl`, and the bundled shell scripts stop provisioning themselves:
`grit/scripts/FastGA_dot_dgenies_stats.sh:36`'s `module load fastga/1.1-c1`
becomes a requirement on `fastga`'s decl, and the script receives an
already-provisioned environment from its caller. The invariant that replaces the
docstring's promise is checkable: **no `module load` (or any other provisioning
verb) may appear in `grit/scripts/**`** — one grep test.

**The 14 hardcoded absolute tool paths** (`~mh6/decon_fasta`,
`/software/grit/projects/vgp_curation_scripts/*.rb`, `~da16/*_buscos`,
`~dz11/…birds_microchromosomes/*.py`, …) are all the *same* seam as
`module_cmd`: they are tools with no indirection. Each becomes a
`ToolRequirement` whose resolution is provider configuration:

```yaml
tools:
  decon_fasta:   {kind: path,      path: /home/mh6/git_checkouts/reblast/bin/decon_fasta}
  busco:         {kind: container, image: /…/busco.sif, binds: [/lustre]}
  fastga:        {kind: module,    module: fastga/1.1-c1}
  pretext_to_asm:{kind: module,    module: grit}
data:
  busco_lineages: {path: /lustre/scratch122/tol/resources/busco/latest/lineages}
  blast_nt:       {path: null, hint: "not configured — see docs/data.md"}
```

`UserConfig` today has six fields and none covers tool or script locations
(`ARCH-06`/`PORT-03`), so this config block is the seam that does not exist yet.
The Singularity/`sing.bash` case is the third provisioning mode report 04 flags:
it is `wrapper`, not `preamble`, which is why `Provision` carries both.

**Coordination boundary.** *What* replaces `decon_fasta` or the `~da16` BUSCO ID
lists is not decided here. This port only requires that whatever replaces it is
nameable as a `ToolRequirement`/`DataRequirement` with a `how_to_obtain` string.
The vendor-into-repo case (the microchromosome scripts, which are the author's
own code) removes the seam entirely rather than filling it — `kind: bundled`,
resolved relative to `grit/scripts/`.

### Invariants

1. `resolve()` is pure with respect to the calling process: it must not mutate
   `os.environ`, `sys.path`, or the filesystem. It *describes* provisioning.
2. `preamble` must be idempotent — safe to run twice in one shell.
3. `check()` must not execute the requested tools and must not require them to
   be usable, only locatable.
4. Every satisfied `ToolRequirement` yields a `versions[key]` entry — a concrete
   version or the literal `"unpinned"`. Silence is not allowed.
5. Every satisfied `DataRequirement` yields a `paths[key]` that exists.
6. A provider that cannot satisfy a non-optional requirement raises
   `ToolUnavailable` from `resolve()` and reports it from `check()`. `check()`
   never raises for an unmet requirement — that is its return value.
7. `Provision` never contains a wildcard or an unexpanded `~`.

### Error model

```
ToolError
├── ToolUnavailable(key, how_to_obtain)     non-optional requirement unsatisfiable
└── ProviderMisconfigured(detail)           the provider's own config is unusable
```

`ToolUnavailable.how_to_obtain` is the string that turns
`PORT2-01`'s failure mode — `/bin/sh: /software/grit/…/get_lineage_from_species.rb:
No such file or directory` inside a `CalledProcessError` traceback — into a
sentence a stranger can act on.

### The `local` reference adapter

`PathProvider`:

- `resolve` — empty `preamble`/`wrapper`/`env`; `versions[key]` from an optional
  per-tool `version_cmd` probe, else `"unknown"`; `paths` from configured data
  roots.
- `check` — `shutil.which(b)` for each declared binary; `Path(root).is_dir()` for
  each data root; anything missing becomes an `Unmet` with the configured hint.

This is deliberately the adapter a pixi or conda user gets: pixi activates the
environment *outside* grit, so from grit's point of view the tools are simply on
`PATH` and no preamble is needed. A dedicated `PixiProvider` (`pixi run -e env
--`, as `wrapper`) is a thin variant, and the `lmod` adapter is today's
behaviour with a real version string.

### Seams absorbed

All 27 Port-2 rows: `MODULE_VERSIONS`, `_MODULES_INIT`, `module_cmd`'s 12 call
sites, the escaped `fastga` pin, `sing.bash`, `singularity exec -B /lustre`,
`curationpretext -profile sanger,singularity` (a `ToolRequirement` with a
site-configured profile string), `shutil.which("rename-and-orient")` on the
submit host, and the whole "2b. Tools invoked outside `modules.py`" table
including the four personal-home paths. The generic Unix commands (`zcat`,
`pigz`, `du -sb --apparent-size`) are *not* modelled as requirements — they are
assumed-present coreutils, and the GNU-only flag (`ARCH-16`) is a portability
bug to fix, not a provisioning seam.

---

## Port 3 — `MetadataSource`

16 seams. `from_yaml` is already close to a complete Jira-free path; the port's
job is to make it *the* path.

### Interface sketch

```python
# grit/ports/metadata.py

@dataclass(frozen=True)
class TicketMetadata:
    ticket_id: str
    manifest: Mapping[str, Any]     # the assembly YAML, unchanged in shape
    teloseq: str = ""               # telomere motif, or "" — a value, not a CLI fragment
    manifest_path: Path | None = None
    source: str = "yaml"            # for display/provenance

class MetadataSource(Protocol):
    name: str
    def fetch(self, ticket_id: str) -> TicketMetadata: ...
```

One verb. Everything else a `MetadataSource` might plausibly do (write a
comment, transition a ticket, list open tickets) has **no seam in the
inventory**, and ticket-state transitions belong to Port 5. YAGNI applied.

### Semantics

**Direction for `CurationContext`.** `from_yaml` becomes the *only*
constructor and gains the environment:

```python
CurationContext.from_yaml(
    ticket_id, metadata: TicketMetadata, user_config, *, env: Environment,
    print_only=False, dry_run=False, untracked=False, memory_mb=None,
) -> CurationContext
```

`from_ticket` disappears as a constructor and becomes two lines in the
composition root: `md = env.metadata.fetch(ticket); ctx =
CurationContext.from_yaml(ticket, md, cfg, env=env)`. Jira stops being a
special case with a bypass flag and becomes one adapter; `--yaml` stops being an
"override" and becomes the default adapter's input. This preserves the item
`TODO/49` cares about — `CurationContext` as an explicit value object with
derivation centralised in `from_yaml`, zero module-level mutable state — while
removing the `sys.path.insert` from the middle of it.

Note what this does to `ctx.teloseq`: today it is the string `"--teloseq TTAGG"`,
i.e. a CLI fragment stored in a value object. `TicketMetadata.teloseq` is the
motif; the flag is assembled where the command is assembled. That closes
`PORT3-02` cleanly and lets a YAML user supply `teloseq: TTAGG`.

**Adapters:**

- `YamlFileMetadataSource(path)` — reference. Reads one file; accepts `teloseq`
  as a manifest key; `manifest_path` is the file.
- `JiraMetadataSource(config)` — owns *everything* Jira: the `sys.path.insert`,
  `GritJiraIssue(ticket_id).yaml`, `customfield_11650`,
  `get_custom_field("yaml")`, and the `pymysql`-implied database. It is the only
  module in the tree that knows any of those names.
  `gritjiraissue_path` moves out of `UserConfig` into this adapter's config block
  (closing `PORT3-03`: a YAML-only user no longer needs a dummy value — the tell
  today is `tests/fixtures/test_config.yaml`'s `/tmp/dummy_gritjiraissue`).
- `RegistryMetadataSource` — optional, worth flagging: `grit status -t` needs
  metadata only for a display summary, and the registry already stores `tol_id`,
  `species` and `workdir`. A source that answers from the registry closes the
  `--yaml`-not-threaded-into-`status` gap without threading anything. Author's
  call; the port makes it a five-line adapter either way.

**Manifest validation happens once, in the domain**, not per adapter
(`validate_manifest(manifest) -> None`), so both adapters produce identical
errors for a missing `hic_read_dir`. `_detect_assembly_type` moves there too
(and is where `CORR-14`'s unproducible `paternal` gets settled).

### Invariants

1. `fetch` is read-only. No writes anywhere, including caches under `$HOME`.
2. `fetch` returns a `TicketMetadata` whose `manifest` passes
   `validate_manifest`, or raises. It never returns a partially-populated one.
3. Missing *configuration* raises `MetadataSourceUnavailable` at construction or
   first use — never an `ImportError`/`ModuleNotFoundError` escaping from inside
   context construction, which is today's off-site failure mode.
4. Constructing a source performs no I/O, so `grit --help` works with no config
   at all (preserve item). The composition root instantiates a source only for
   commands that need a ticket.
5. `teloseq` is a motif or `""` — never a flag fragment.

### Error model

```
MetadataError
├── MetadataNotFound(ticket_id)
├── MetadataInvalid(field, reason)          # manifest schema failures
└── MetadataSourceUnavailable(detail)       # auth, network, missing library/config
```

### Seams absorbed

All 16 Port-3 rows except the four registry/config-location rows
(`~/.grit/grit_registry.json`, `dry_run_root()`, the user-config default path),
which are *not* metadata — they are grit's own state location and belong to
packaging/site profiles, which another agent owns. Also absorbed: the two
`from_yaml`-completeness gaps (`teloseq`, `gritjiraissue_path`), and
`status.py:424-437`'s implicit Jira hit.

Not absorbed, deliberately: `_pick_highest_version()`'s preference for a
filename containing the literal `"RC"` and `setup.py`'s "pretext map filename
contains the ticket ID" filter. Those are ToL *naming*, not metadata — Port 4.

---

## Port 4 — `StorageLayout`

34 seams, the largest and the most duplicated. The design risk here is a god
object, so the first decision is what this port does **not** own.

### What it owns, and what it does not

| Owns | Does not own |
|---|---|
| Where the workdir, curated dir and deposit dirs are, given an assembly anchor | What a step's outputs are called (→ `StepDecl.outputs`; the existing spec tuples are on the preserve list) |
| Release filenames — the contract downstream consumers read | File *formats*: chromosome-list CSV grammar, `SUPER_`/`unloc` semantics, pretext-to-asm log grammar (→ `result_parsers.py`, also preserved) |
| Haplotype roles and the prefix alias table | The canonical-resolution policy (→ domain; unchanged) |
| Taxonomy-from-identifier, as data | Run-dir layout `{workdir}/<step>/<ISO-ts>/` (→ `RunTracker`; grit-internal, not a site convention) |

That split is the reason this port has 7 functions rather than 34.

### Interface sketch

```python
# grit/ports/layout.py

class HapRole(Enum):
    HAP1 = "hap1"
    HAP2 = "hap2"

class FileKind(Enum):
    ASSEMBLY   = "assembly"
    HAPLOTIGS  = "haplotigs"
    ADDITIONAL_HAPLOTIGS = "additional_haplotigs"
    CHR_LIST   = "chr_list"
    HIC_MAP    = "hic_map"

@dataclass(frozen=True)
class AssemblyAnchor:
    """The one input from which every derived path hangs."""
    draft_dir: Path        # the versioned draft dir from the manifest
    specimen_id: str       # tol_id
    release_version: int
    username: str

@dataclass(frozen=True)
class Taxon:
    clade: str                       # "bird" | "insect" | "nematode" | …
    traits: frozenset[str]           # "microchromosomes", "sex_busco_set", …
    busco_lineage: str | None = None
    sex_chromosome: str | None = None

class StorageLayout(Protocol):
    name: str

    def workdir(self, anchor: AssemblyAnchor) -> Path: ...
    def curated_dir(self, anchor: AssemblyAnchor) -> Path: ...
    def deposit_dir(self, base: Path, specimen_id: str) -> Path:
        """Destination for published maps under a shared tree. Never returns a glob."""
    def local_download_dir(self, specimen_id: str) -> str:
        """The curator's laptop-side directory used in scp tips."""

    def hap_roles(self, assembly_type: str) -> tuple[HapRole, ...]:
        """One role for a single-hap assembly, two otherwise."""
    def hap_token(self, hap_prefix: str) -> str:
        """The filename token for a manifest haplotype prefix (primary → hap1)."""

    def release_filename(self, specimen_id: str, hap: HapRole | None,
                         version: int, kind: FileKind) -> str: ...

    def classify(self, specimen_id: str) -> Taxon | None:
        """Taxonomy implied by the identifier, or None when it implies nothing."""
```

### Semantics

**`workdir` becomes total.** Today `_derive_workdir` does a literal
`assembly/draft` → `working` substitution and **raises `ValueError`** when the
substring is absent, so the ToL directory convention is a hard precondition with
no override (`PORT-09`/`PORT4-01`), and `status.py:610` re-derives the same
relationship independently as `.parent.parent.parent` (which is how the two can
drift). Contract: `workdir()` is **total** for a well-formed anchor. The ToL
adapter attempts the substitution, and on a miss falls back to a documented
default plus one warning; a `workdir:`/`curated_dir:` override in config short-
circuits it entirely. `status.py`'s ascent is deleted — it calls the same method.

**Haplotype aliasing, once.** `_PTA_ALIASES` is duplicated 5× with the fifth copy
(`find_hap_agp`) silently omitting `paternal`/`maternal` (`PORT4-02`), and
`is_single_hap` is reimplemented inline in `status.py:161` (`ARCH-14`/`DOM-13`).
`hap_token` and `hap_roles` are the single definitions. `is_single_hap(ctx)`
survives as a one-line domain helper over `hap_roles`, so the six call sites
CLAUDE.md documents keep working — the preserve list keeps the *helper*, not its
implementation.

**Taxonomy from identifier becomes data.** Today the ToL ID's leading characters
drive control flow: `tol_id.startswith("b")` ⇒ bird ⇒ suggest microchromosome
second shot; `_INSECT_PREFIXES = ("ic","il","id","n")` in `sex_matcher.py` with a
**second, divergent** copy `("ic","il","id")` in `setup.py`; `sex-matcher.sh`
selecting a BUSCO lineage *and* a sex-BUSCO ID list from chars 1 and 2; and
`tol_id[0]`/`tol_id[1]` indexed directly into an NFS directory tree
(`PORT4-03`). The replacement is one table in the ToL adapter:

```yaml
taxonomy:
  - {prefix: b,  clade: bird,     traits: [microchromosomes]}
  - {prefix: ic, clade: insect,   traits: [sex_busco_set], busco_lineage: coleoptera_odb10, sex_chromosome: X}
  - {prefix: il, clade: insect,   traits: [sex_busco_set], busco_lineage: lepidoptera_odb10, sex_chromosome: Z}
  - {prefix: id, clade: insect,   traits: [sex_busco_set], busco_lineage: diptera_odb10}
  - {prefix: n,  clade: nematode, traits: [sex_busco_set], busco_lineage: nematoda_odb10,  sex_chromosome: X}
```

longest-prefix wins, and **`classify` returns `None` for an unrecognised
identifier — it never raises and never exits**. That is the structural half of
the `sex-matcher exit 1` problem: the step declares
`traits=("sex_busco_set",)`, pre-flight (Port 6) resolves traits from
`classify()` or from an explicit `--trait`/config override, and an unresolved
trait produces an actionable pre-flight refusal instead of `raise SystemExit(1)`
from inside library code. Off-ToL, identifiers imply nothing and the traits are
supplied explicitly — which is exactly the property the scope decision requires.

**`deposit_dir` must never return a glob.** `finalize_qc._resolve_nfs_dest`
currently warns and returns a literal path containing `?` characters, which is
then used as a `cp` destination. Contract: resolve or raise `LayoutUnresolved`.

**`release_filename` is the *specification* of the release contract** that today
lives out of repo in `GritJiraIssue.get_curated_file_name_for_type()`, with grit
containing code that guesses what that function will look for (`PORT5-02`). The
table moves in-repo; Port 5's `validate()` is where the external consumer gets
to disagree.

### Invariants

1. Every method is pure and deterministic: same input ⇒ same output, no
   filesystem writes, no `mkdir`.
2. `workdir` and `curated_dir` are total for a well-formed anchor.
3. No returned path contains a glob metacharacter or an unexpanded `~`.
4. `hap_token` is total over the manifest prefixes the project supports
   (`hap1`, `hap2`, `primary`, `alternate`, `paternal`, `maternal`) — the
   invariant that would have caught the divergent fifth copy.
5. `hap_roles` returns exactly one role for a single-hap assembly type and
   exactly two otherwise.
6. `release_filename` is injective over `(hap, kind)` for fixed
   `(specimen_id, version)` — two distinct artifacts can never collide on a
   destination name. (Today the single-hap branch drops the hap token, which is
   correct only *because* single-hap ships one haplotype; the invariant makes
   that explicit rather than incidental.)
7. `classify` returns `Optional[Taxon]`; unknown is a value, not an error.
8. `deposit_dir` may read the filesystem (it resolves a real prefix tree) but
   never writes, and raises rather than returning a wildcard.

### Error model

`LayoutUnresolved(what, hint)` — raised only by `deposit_dir` and by an adapter
whose configuration is genuinely insufficient. Everything else is total.

### The `local` reference adapter

`FlatLayout`:

- `workdir(anchor)` = `anchor.draft_dir.parent.parent / "working" /
  f"{anchor.username}_curation" / base_id` where `base_id` strips a trailing
  `.<version>` — i.e. today's shape with no dependence on the literal
  `assembly/draft`.
- `curated_dir(anchor)` = `anchor.draft_dir.parent.parent / "curated" /
  f"{specimen}.{version}"`.
- `deposit_dir(base, _)` = `base` (no prefix tree).
- `local_download_dir(id)` = `~/curations/work/{id}` — one definition, which
  incidentally fixes `PORT4-04` (`hic_remapping.py:131` uses
  `~/curations/{id}` while five other sites use `~/curations/work/{id}`).
- `hap_token`/`hap_roles`/`release_filename` — identical to the ToL adapter.
  The *file naming* contract is what downstream consumers read, so the reference
  adapter keeps it; only the directory topology differs.
- `classify(_)` = `None` always.

### Seams absorbed

Section 4a in full (path derivation, the 3-level ascent, the ONT
`replace("fasta","")` hack, the local-download-dir drift, the two-level prefix
tree) and the *convention-as-control-flow* rows of 4b: the alias table ×5, the
haplotig-keyword tuple ×4, `is_single_hap`/`_canonical_haps`, the insect-prefix
tuples ×2, the bird-prefix suggestion, `sex-matcher.sh`'s char-indexed lineage
selection, the release-naming table, and `_pick_highest_version`'s `"RC"`
preference. Left where they are, by the split above: `_OUTPUT_SPECS`-style glob
patterns (→ `StepDecl`), the `SUPER_`/`unloc`/sex-chromosome/CSV grammars (→
`result_parsers.py`), the merquryk sub-path (→ `StepDecl.output_location`
`CURATED_DIR`, which also deletes the four duplicated derivations), and the
run-dir/`.grit` layout (→ `RunTracker`).

---

## Port 5 — `ReleaseTarget`

11 seams. The end of the pipeline, and the one place where an incomplete result
is currently published and reported as success.

### Interface sketch

```python
# grit/ports/release.py

@dataclass(frozen=True)
class ReleaseArtifact:
    kind: FileKind
    hap: HapRole | None
    source: Path                 # resolved by the canonical resolvers
    dest_name: str               # from StorageLayout.release_filename
    required: bool = True

@dataclass(frozen=True)
class ReleasePlan:
    ticket_id: str
    specimen_id: str
    version: int
    dest_dir: Path
    artifacts: tuple[ReleaseArtifact, ...]
    deposits: tuple[tuple[Path, Path], ...] = ()   # (source, dest_dir) for maps

@dataclass(frozen=True)
class ReleaseProblem:
    severity: Literal["error", "warning"]
    artifact: str | None
    detail: str

@dataclass(frozen=True)
class ReleaseReceipt:
    dest_dir: Path
    written: tuple[Path, ...]
    followups: tuple[str, ...] = ()      # human actions, e.g. the submission-text reminder

@dataclass(frozen=True)
class PostProcessOutcome:
    ran: bool
    skipped_reason: str | None = None
    marks_ticket_done: bool = False

class ReleaseTarget(Protocol):
    name: str
    def validate(self, plan: ReleasePlan) -> list[ReleaseProblem]:
        """Pre-flight the whole set. No writes."""
    def publish(self, plan: ReleasePlan) -> ReleaseReceipt:
        """All-or-nothing. Refuses a plan with any error-severity problem."""
    def finalize(self, ticket_id: str, receipt: ReleaseReceipt) -> PostProcessOutcome:
        """Site-specific post-release pipeline. See the post_process_rc placeholder."""
```

### Semantics

**The plan is assembled once, validated once, published atomically.** Today
`finalize_qc` copies FASTAs, haplotigs and chromosome lists in **three
independent loops**, a missing canonical FASTA is a `log.warning` + `continue`, a
missing haplotig file is `touch`-ed empty, and then `success` is recorded and the
ticket advances to `post_processing` with an incomplete release directory
(`CORR-06`, `DOM-05`). Making `ReleasePlan` a value that must be complete
*before* the first `cp` is the structural form of Batch 5's requirement: the
warn-and-continue path has nowhere to live.

`validate()` is where cross-artifact coherence checks belong — including "the
chromosome list names scaffolds absent from the FASTA", which is Batch 5's
closing test. I am *not* specifying that check's policy here (Batch 5 must first
resolve which fa/chr pairs are legal, since `recuration-canonical-priority.md`
L181-185 currently blesses one incoherent pair); the contract only fixes *where*
it runs and that publishing cannot bypass it.

**`publish` is all-or-nothing**: stage into a temporary directory under
`dest_dir` and move into place, or leave `dest_dir` untouched. Re-publishing an
identical plan is a no-op.

**No `announce` verb.** The only Jira "write" in the codebase today is a
*printed reminder* to the human ("don't forget Submission Text and attaching the
latest savestate") — no API call. Rather than a speculative notification port, it
is `ReleaseReceipt.followups`, printed by the domain. If a site ever really
transitions a ticket, that is `finalize()`'s business.

**`finalize()` is the `post_process_rc` placeholder, carried explicitly and
not invented.** What is *known*, from `post_processing.py:17,50-68` and nothing
else:

- invocation: `source /software/grit/projects/contamination_screen/conf/contamination_screen.conf`;
  `shopt -s expand_aliases`; `cd <curated dir>`; `post_process_rc <ticket_id>`,
  piped into `bash`.
- `post_process_rc` is a **shell alias** defined by that conf. There is no
  binary, no path, no module key, and no substitution point of any kind.
- it is described in a docstring as a Snakemake contamination-screen +
  submission-prep pipeline. Nobody in this repository can describe what it does.
- the only postcondition grit relies on: **exit 0 ⇒ `RegistryManager().mark_done(ticket)`**.

Contract, therefore: `finalize()` receives the ticket id and the receipt; it
returns a `PostProcessOutcome` whose `marks_ticket_done` the domain honours. The
Sanger adapter is `AliasShellPostProcess(conf=…, alias="post_process_rc")` — a
faithful copy of today's four lines, now the only place `shopt -s
expand_aliases` appears. **Three unknowns are recorded, not solved** (per the
scope decision): what the pipeline does, whether exit 0 is a sufficient
condition for "done", and whether the conf itself contains site paths or
credentials.

**`GritJiraIssue.get_curated_file_name_for_type()`.** The naming contract moves
in-repo (Port 4), and the Sanger `ReleaseTarget` adapter becomes the only module
allowed to know `GritJiraIssue` exists: its `validate()` may *ask*
`get_curated_file_name_for_type()` what it expects and report a mismatch as a
`ReleaseProblem`. That converts "code that guesses what an out-of-repo function
will look for" into "the adapter asks the consumer, before copying anything".

### Invariants

1. `validate()` performs no writes and is safe to call repeatedly.
2. `publish()` refuses any plan with an error-severity problem; it must call
   `validate()` itself, not trust the caller.
3. `publish()` is atomic and idempotent, and writes only under
   `plan.dest_dir` (plus the declared deposit destinations).
4. `publish()` never fabricates an artifact. No zero-byte placeholder, ever —
   if a required artifact is absent, the plan is invalid. (An intentionally
   empty file that a downstream consumer requires must be declared as an
   artifact with an explicit `EmptyPermitted` kind, not `touch`-ed as a
   side effect.)
5. Every published file's name comes from `StorageLayout.release_filename` —
   the adapter does not invent names.
6. `finalize()` reports `marks_ticket_done` honestly; the reference adapter
   never claims it.
7. The ticket's terminal state is written by the domain from
   `PostProcessOutcome`, not by the release adapter (`post_processing.py:68`
   calls `mark_done` directly today).

### Error model

```
ReleaseError
├── ReleaseRefused(problems)        validate() found errors
├── PublishFailed(detail)           partial publish rolled back
└── PostProcessUnavailable(detail)  finalize()'s site pipeline is absent/misconfigured
```

### The `local` reference adapter

`DirectoryReleaseTarget(dest_dir)`:

- `validate` — every required artifact's `source` exists and is non-empty; no
  two artifacts share a `dest_name`; `dest_dir` is writable; cross-artifact
  coherence checks as Batch 5 defines them.
- `publish` — stage + move; receipt lists written paths; `followups` carries the
  submission-text reminder text (which stops being a hardcoded personal gist
  link in library code — see the `gist.github.com/zilov/…` seam).
- `finalize` — returns `PostProcessOutcome(ran=False,
  skipped_reason="no post-processing configured for this site",
  marks_ticket_done=False)` and the CLI prints what a site would need to
  provide. A ticket is *not* silently marked done off a pipeline that never ran.

### Seams absorbed

All 11 Port-5 rows: the destination dir, the release-filename contract, the
`GritJiraIssue` naming dependency, the empty-haplotig `touch`, the pretext-map
deposit under the two-level tree, the QV auto-trigger (which becomes a
`followup`/declared dependency rather than a nested step call inside a copy
loop), the printed Jira reminder, the personal gist link, `post_process_rc`, and
`mark_done`.

---

## Port 6 — Capability declaration (collapsed into `StepDecl`)

**Finding: this is not a port.** It has no alternative implementations and
nothing swaps it; it is *data* that the other ports consume. Treating it as a
port would add a sixth wiring point for no variation. What it does do is
eliminate `ARCH-03` (six hand-maintained step registries in five files, already
disagreeing) and provide the pre-flight surface the scope decision forces.

### The declaration

```python
# grit/ports/steps.py   (data only — no behaviour, so it lives beside the ports)

class OutputLocation(Enum):
    RUN_DIR = "run_dir"
    WORKDIR = "workdir"
    CURATED_DIR = "curated_dir"

class CompletionKind(Enum):
    SCHEDULED             = "scheduled"    # grit submits it; the backend owns completion
    SYNCHRONOUS           = "synchronous"  # runs in-process; reconcile immediately
    EXTERNALLY_SCHEDULED  = "external"     # an external tool submits its own work

class Trigger(Enum):
    INPUTS = "inputs"
    PARAMS = "params"
    SOFTWARE = "software"

@dataclass(frozen=True)
class StepDecl:
    name: str                                  # tracker step name — THE identity
    command: str                               # CLI command name
    outputs: tuple[OutputSpec, ...]            # today's spec tuples, unchanged in shape
    output_location: OutputLocation = OutputLocation.RUN_DIR
    completion: CompletionKind = CompletionKind.SCHEDULED
    tools: tuple[ToolRequirement, ...] = ()
    data: tuple[DataRequirement, ...] = ()
    traits: tuple[str, ...] = ()               # resolved via StorageLayout.classify or config
    status_label: str | None = None            # replaces STEP_TO_STATUS
    keep_latest: bool = False                  # replaces _STEPS_KEEP_LATEST
    scp_tip_outputs: tuple[str, ...] = ()      # replaces _SCP_TIP_STEPS
    rerun_triggers: frozenset[Trigger] = frozenset({Trigger.INPUTS, Trigger.PARAMS, Trigger.SOFTWARE})
    supports_dry_run: bool = False             # replaces _DRY_RUN_SUPPORTED_COMMANDS
```

One `StepCatalog` maps both `name` and `command` to a decl. The six current
registries — `STEP_MANIFESTS` (19), `STEP_TO_STATUS` (17), `_get_step_specs`'
map (14), `_SCP_TIP_STEPS` (6), `_STEPS_KEEP_LATEST` (7),
`_DRY_RUN_SUPPORTED_COMMANDS` (24) — all become views over it, and the drift
they already exhibit becomes untypeable: six tracked steps with no
`STEP_MANIFESTS` entry (so `verify_outputs` returns `not_tracked` and reconcile
silently gives up), a phantom `agp_copied` in `STEP_TO_STATUS`, four commands
allowlisted for `--dry-run` with no `dry_run` branch (`ARCH-07`).

`STEP_MANIFESTS` is **deleted rather than moved**: `outputs` already does its job
better (it is what the epilogue, the bjobs recovery, `_step_output`'s re-glob and
`write_fake_outputs` all use), and its independent second opinion is precisely
what lets two reconcile paths disagree. `verify_outputs`'s
`ok/partial/missing/not_tracked/no_files` vocabulary collapses into the output
probe inside `reconcile`, where `not_tracked` cannot exist.

### What a step declares, and when it is checked

```python
@dataclass(frozen=True)
class Readiness:
    ok: bool
    unmet: tuple[Unmet, ...]

def preflight(decl: StepDecl, ctx: CurationContext) -> Readiness
```

`preflight` composes existing port methods and adds nothing new:

| Requirement | Checked via |
|---|---|
| `tools`, `data` | `ctx.env.tools.check(decl.tools, decl.data)` |
| `traits` | `ctx.env.layout.classify(ctx.tol_id)` plus config/CLI overrides |
| `completion` feasibility | `ctx.env.exec.capabilities` — e.g. a `SCHEDULED` step on a backend whose `requires_shared_install` cannot be satisfied |
| workdir | today's `require_workdir(ctx)` |

**When**: at the top of every step function, **before `tracker.start()`**. That
ordering matters — a pre-flight failure must leave no run record, so it can
never strand a `started` row (`CORR-09`'s failure mode) and never needs
`grit untrack` to recover. `preflight` is skipped in `print_only` (as
`require_workdir` already is) and in `dry_run`.

**How it surfaces:**

- `grit <step> --check` — run pre-flight and exit; prints each `Unmet` with its
  `how_to_obtain`.
- `grit doctor` — the whole catalog as a table: step × (tools, data, traits,
  backend) × ready/blocked. This is the command that answers "will this
  installation run anything?" for a stranger, which today has no answer short of
  running a step and reading a traceback.
- `grit <step> --help` — appends a static "Requires: …" section rendered from the
  decl. Static data, so it works with **no config at all** (preserve item).
- `grit status -t` — a per-step readiness marker next to the existing status, so a
  blocked step is visibly blocked rather than repeatedly failed.

**Interaction with Port 2**: `StepDecl.tools`/`data` are *the* input to
`ToolProvider.check`/`resolve`. The declaration says what the step needs in
logical terms; the provider says how this site provides it; the substitution
decision (whose port this is not) fills in the provider's config. `sex-matcher`
is the worked example: today it `exit 1`s on an unrecognised prefix and, if it
gets past that, `grep -f`s four BUSCO ID lists out of a third party's home
directory and marks itself `failed` with no indication that *reference data* was
missing. Declared, it is
`traits=("sex_busco_set",), data=(DataRequirement("sex_busco_sets", hint=…),)`,
and both failures become pre-flight sentences.

---

## Reconcile-once

`ARCH-01` is the single most expensive structural defect: "reconcile a finished
job with its outputs" exists four times with four different success criteria
(`click_cli.py:230-249`, `registry.py:241-296`, `status.py:518-541`,
`sex_matcher.py:99-128`), which is why the same run reports differently
depending on which path fires and why `rename_and_orient` can stick on
`done (check)` via one path and `success` via another.

### One function

```python
# grit/domain/reconcile.py

@dataclass(frozen=True)
class Evidence:
    """What we know about why we are reconciling. Never a verdict."""
    job: JobStatus | None = None          # from ExecutionBackend.poll or a completion hook
    local_exit: int | None = None         # from a synchronous in-process run
    probe_only: bool = False              # EXTERNALLY_SCHEDULED: outputs are all we may use

@dataclass(frozen=True)
class RunOutcome:
    status: Literal["success", "failed", "untracked", "unchanged"]
    outputs: Mapping[str, str]
    reason: FailureReason | None = None

def reconcile(decl: StepDecl, run: RunRecord, tracker: RunTracker,
              *, evidence: Evidence, untracked: bool) -> RunOutcome:
    ...
```

### The rules, stated once

1. **Outputs are collected once**, from `decl.outputs` against the location
   `decl.output_location` resolves to. There is no second opinion
   (`STEP_MANIFESTS` is gone) and no per-step special case — which deletes
   `core`'s `elif step == "sex_matcher":` branch and the three different assumed
   locations for that step's output (`ARCH-19`, `CORR-10`/`CORR-13`).
2. **Terminal status is a function of (job state, outputs), and success requires
   outputs:**

   | Evidence | Outputs complete | Outputs empty/partial |
   |---|---|---|
   | `SUCCEEDED` / `local_exit == 0` | `success` | **`failed`** (never success) |
   | `FAILED` / non-zero exit | `failed` (+ reason) | `failed` (+ reason) |
   | `FORGOTTEN` | `success` | `failed` |
   | `UNKNOWN`, or `BackendUnavailable` was raised | `unchanged` | `unchanged` |
   | `probe_only` (externally scheduled) | `success` | `unchanged` |

   Row 1's right-hand cell is Batch 3's rule (`CORR-03`): today the epilogue
   passes the LSF-derived status straight through and records empty outputs as
   `None` without downgrading. Row 4 is `CORR-04`: a `bjobs` outage must change
   nothing. Row 5 keeps `hic_remapping`/`curationpretext` from being declared
   failed merely because the pipeline is still running.
3. **`untracked` is honoured in one place.** `reconcile` writes
   `status="untracked"` when the run is untracked, while still recording
   outputs — so `grit retrack` can promote it later. This is the single
   `untracked=` call site that `TODO/tiny.md`'s bug had to be fixed at 40 times
   by hand, and the recovery paths that currently omit it (`_resolve_gone_job`,
   `status`'s fallback, `sex_matcher`'s guard) cannot omit it any more
   (`DOM-03`, `DOM-04`).
4. **Idempotent.** Reconciling a run that already has a terminal record returns
   the existing outcome and writes nothing. This is what makes at-least-once
   callback delivery safe and is why the port does not need exactly-once.
5. **`reconcile` is the only caller of `tracker.finish()`.**

### Why a second implementation cannot grow

Rule 5 is enforced, not requested:

- `RunTracker.finish` is renamed to `_finish` / marked module-private to
  `grit/domain/`, and a test AST-scans `grit/` for any `.finish(` call outside
  `grit/domain/reconcile.py`. Adding a fifth reconcile path fails CI.
- Steps have only two shapes available: `SCHEDULED` (call
  `ctx.env.exec.submit(spec, hook)` — completion is the port's problem) and
  `SYNCHRONOUS` (call `reconcile(..., evidence=Evidence(local_exit=rc))`). There
  is no third shape in which a step could write a terminal status itself. That
  also removes CLAUDE.md's documented footgun that a synchronous tracked step
  must remember to `try/except` and finish itself or strand the record forever.
- `poll` is read-only by contract (invariant 4 of Port 1), so a rendering path
  physically cannot finish a run. `grit status` becomes read-only (`ARCH-04`),
  and the two contradictory rules one `grit status -t` currently applies
  (`registry.py:290-292` vs `status.py:540-551`, `CORR-15`) have one place to be
  stated in.

### Where the four current paths go

| Today | Becomes |
|---|---|
| `click_cli.state_update_cmd` (the epilogue's CLI) | Parses argv; loads the run; calls `reconcile(evidence=Evidence(job=JobStatus(...)))`. No globbing, no status logic. |
| `registry._refresh_pending_jobs` + `_resolve_gone_job` | `domain.reconcile_pending(catalog, tickets, backend)` — one `poll` for all in-flight handles, then `reconcile` per run. Called explicitly (`grit reconcile`, and at the start of a step), never from rendering. |
| `status.py:518-541`'s inline recovery | Deleted. `status` calls `poll` for display and renders; a stale row is fixed by the explicit pass. |
| `sex_matcher.py:99-128`'s resubmit guard | `reconcile(...)` followed by a shared `should_skip(decl, ctx) -> SkipReason | None` built on the rerun triggers below. The unconditional `exit 0` in `sex-matcher.sh` stops mattering, because exit 0 with no `Best_match` file is row 1's right-hand cell. |

---

## Borrowed patterns placement

### 1. Snakemake-style unified rerun triggers → `StepDecl` + the run record

Home: `StepDecl.rerun_triggers` (declaration) + `RunFingerprint` on the run
record (state) + one domain predicate. Not a port — it needs no swappable
implementation — but it **depends on** Port 2 returning `Provision.versions`,
which is why that field is in the contract.

```python
@dataclass(frozen=True)
class RunFingerprint:
    inputs: Mapping[str, str]    # path -> mtime or content hash
    params: str                  # sha256 of the rendered command
    software: Mapping[str, str]  # resolved tool versions, from Provision.versions

def is_stale(decl, last_run, current: RunFingerprint) -> StaleReason | None
```

Computed at `tracker.start()`, stored beside `outputs`, and consulted by one
`should_skip`. It replaces five hand-written staleness checks — `hic_remapping`'s
"is the previous `hr.pretext` newer than the canonical FASTA", `fastga`'s reuse
check, `fastga_stats`' reuse check, `pretext_to_asm`'s
`inputs_newer_than_curated_fa`, and `sex_matcher`'s already-done branch.

Two correctness consequences, not conveniences:

- **A tool-version bump now invalidates.** Today a `MODULE_VERSIONS` change
  invalidates nothing at all, and no run record says which tool version produced
  a curated FASTA (`PKG-02`/`PORT2-03`).
- **`DOM-09` becomes fixable.** The "already done" skip currently decides whether
  a curator's new curation round runs from input-vs-output mtime alone, so any
  mtime-preserving copy of the AGP (`cp -p`, `rsync -a`, an archive extraction)
  makes grit print "Already done", run nothing and write no record. Hashing the
  AGP (small, one file) instead of stat-ing it closes that; see open question 5.

`Trigger.INPUTS` also needs the *declared* inputs, which `StepDecl` above does
not carry. I deliberately left them out: the inputs of most steps are resolved
at call time by `find_canonical_*` (that is the whole architecture — report 07
confirms grit has no DAG), so an input list would be a second, drifting truth.
The fingerprint therefore records the inputs the step *actually resolved*, which
is both accurate and requires no declaration.

### 2. Dagster-style named assets + explicit `supersedes` → the domain tracker

Home: `grit/domain/assets.py` and the run record. **Not a port**, and — critically
— **not a policy change.** Report 06 assessed the flat mtime-ordered pool as
sound and correct; it stays exactly as it is.

Two mechanical changes:

**(a) The pool becomes data.** One table replaces the three near-identical
hardcoded pools at `helpers.py:425` (fa), `:477` (haplotigs) and `:563` (chr
list):

```python
ASSETS = (
    AssetDecl(FileKind.ASSEMBLY,  producers=("pretext_to_asm", "microchromosome_combine",
                                             "blast_contaminants", "rename_and_orient",
                                             "rename_and_orient_hap2", RECURATE_FOR_HAP)),
    AssetDecl(FileKind.HAPLOTIGS, producers=("pretext_to_asm", RECURATE_FOR_HAP)),
    AssetDecl(FileKind.CHR_LIST,  producers=("pretext_to_asm", "microchromosome_combine",
                                             "rename_and_orient", "rename_and_orient_hap2",
                                             RECURATE_FOR_HAP)),
)

def resolve_canonical(ctx, asset: AssetDecl, hap: HapRole) -> Path | None
```

One generic resolver — same mtime rule, same first-listed tie-break, same
re-glob-on-incomplete-outputs behaviour (`143f425`'s `_step_output`), same
filesystem fallbacks (declared per asset as an ordered list of glob templates
rather than three bespoke code paths). The three public helpers
`find_canonical_fa`/`_haplotigs`/`_chr_list` stay as thin named wrappers, because
`recuration-canonical-priority.md` documents them by name to curators.

Which port lets it be stated as data: **Port 4** supplies `hap_token`/`hap_roles`
(so the resolver stops carrying its own alias dict and the `hap1`/`hap2` literal
guards) and **Port 6** supplies `decl.outputs` for the re-glob (so the resolver
stops importing step modules — the `helpers ↔ steps` cycle). `DOM-14`
(`rename_and_orient` and `rename_and_orient_hap2` both sitting in every
haplotype's pool, with cross-hap contamination prevented only by output keys
happening to differ) becomes expressible: a producer entry can be scoped to a
`HapRole`.

**(b) The winner is recorded, not only re-derived.** When `reconcile` records a
run's outputs, it evaluates the asset resolvers and writes onto the run record:

```python
"canonical_for": ["assembly:hap1", "chr_list:hap1"],
"supersedes":    {"assembly:hap1": "<previous run_dir>"}
```

The edge is a **memo of the existing rule's decision**, not a new rule. What it
buys:

- `grit status`' `Canonical` column is *read*, not re-derived. That deletes
  `_canonical_mark`'s partial re-implementation of `_step_output`'s attribution
  rule and the display layer's own copy of the single-hap test (`DOM-13`,
  `ARCH-14`) — keeping the display thin, which is the standing style note.
- An audit trail: "which run was canonical for hap1's FASTA when finalize-qc
  shipped" becomes a fact rather than a re-computation against a filesystem that
  has since changed.
- **Detection instead of patching.** When the mtime rule now resolves to a run
  *older* than the last recorded edge, that is the "canonical moves backwards"
  symptom (`143f425`, the RC-4833 report) and it becomes a loud, specific warning
  — "canonical for assembly:hap1 moved backwards from X to Y" — rather than a
  silent regression that had to be patched around with a re-glob. Report 07 is
  right that this would have *prevented* the bug; note that the re-glob stays
  (it is the correct behaviour for incompletely-recorded outputs), it just stops
  being the only line of defence.
- `DOM-08`'s clock-skew risk gets a cheap mitigation: the edge records the
  run-dir ISO timestamps, which all come from one host, so a mtime comparison
  that contradicts the timestamp order is detectable.

### 3. Nextflow-style `errorStrategy` / retry-backoff — deferred, no port surface

It needs nothing beyond `submit`, so it is a `StepDecl` field
(`retries`, `retry_on`, `memory_escalation`) whenever the author wants it. Kept
out of the contracts per YAGNI.

### Transactional state (append-only JSONL) — not a port

`TODO/50` Batch 2's remediation. It has one implementation at a time and no
alternative, so it is not a port (see `## Ports I decided against`). Noted here
only because report 07 lists it beside the other borrowed patterns and because
Port 1's local/Slurm adapters *increase* the number of concurrent writers, which
makes it more urgent, not less.

---

## Adapter conformance suite

`TEST-09` found nothing that could seed a contract suite, and `TEST-01` found the
whole execution seam has zero tests. The suite below is therefore two things at
once: the adapter contract, and the missing baseline to refactor against. It
lives in `tests/conformance/`, is parametrised over adapter instances, and ships
with an in-memory fake per port so the suite itself is provably executable in CI
with no farm.

**Cross-cutting:** each suite is a `pytest` class parametrised over
`(adapter, capabilities)`; a test whose precondition the adapter declares away
(`supports_kill=False`) is `skip`ped, not silently passed, and a declared
capability that the adapter fails is an error. Integration-only tests are
marked and deselected by default.

### `ExecutionBackend`

1. `submit` returns a handle with a non-empty `job_id` and the correct `backend`;
   the id round-trips through `poll`.
2. `render(spec, hook)` returns a non-empty string containing `run_dir`, and
   executes nothing (asserted with a spy over `subprocess`).
3. `render` ≡ what `submit` runs (adapters expose a test hook, or the local
   adapter compares against the recorded command).
4. **Quoting round-trip**: a spec whose `shell_command` contains `"`, `'`, `$`,
   a newline and a space-bearing path submits and runs verbatim. This is the test
   that would have caught the single-`"…"` wrap footgun.
5. `poll([never_submitted])` → `FORGOTTEN`, no exception.
6. `poll` with the scheduler made unreachable → raises `BackendUnavailable`
   (never `FORGOTTEN`, never a terminal state).
7. `poll` writes nothing: asserted against a sentinel registry/tracker.
8. Job exits 0 **with** declared outputs → `reconcile` records `success` exactly
   once; a second `reconcile` is a no-op returning the same outcome.
9. Job exits 0 **without** outputs → not `success`.
10. Job exits non-zero → `failed`, and `describe_failure` returns a
    `FailureReason`; an OOM-killed job returns `OUT_OF_MEMORY`.
11. An `untracked` run survives the whole completion path as `untracked`, with
    outputs recorded.
12. Declared `completion_modes` are honoured: for `SYNCHRONOUS`, the terminal
    record exists before `submit` returns; for `CALLBACK`, the rendered command
    contains the callback and the callback argv is executable-shaped and its
    parsed form matches the `CompletionHook`.
13. `requires_shared_install=True` ⇒ the adapter exposes its launcher argv and
    pre-flight can evaluate it. (No adapter may derive it from `sys.argv[0]`.)
14. `cores`/`memory_mb` are honoured, or `honours_resources=False` is declared.
15. `kill` on a running job leads `poll` to `KILLED`/`FAILED` within a bounded
    wait (skipped when `supports_kill=False`).

### `ToolProvider`

1. `resolve([])` → empty `preamble`, and `compose()` of it yields a command with
   no leading/trailing `&&` — the `PORT-19`/`ABST-02` regression test.
2. `resolve` of an unknown key → `ToolUnavailable` with a non-empty
   `how_to_obtain`; `check` of the same returns one `Unmet`, no raise.
3. `resolve`/`check` mutate neither `os.environ` nor `sys.path` nor the
   filesystem (asserted by snapshot).
4. `check` does not execute the requested tools (spy over `subprocess`).
5. `preamble` is idempotent: running it twice in a recording fake shell is
   equivalent to once.
6. Every satisfied requirement yields a `versions[key]` — concrete or the literal
   `"unpinned"`. Absence fails.
7. Every satisfied `DataRequirement` yields an existing `paths[key]`.
8. No returned string contains a glob metacharacter or an unexpanded `~`.
9. Integration-marked: after running the preamble in a real shell, every declared
   binary is on `PATH`.

### `MetadataSource`

1. `fetch(known)` returns a `TicketMetadata` whose `manifest` passes
   `validate_manifest`.
2. `fetch(unknown)` → `MetadataNotFound` — not `KeyError`, not `ImportError`,
   not `ModuleNotFoundError`.
3. Missing configuration → `MetadataSourceUnavailable`, raised from the source,
   never escaping from inside `CurationContext` construction.
4. `fetch` writes nothing (asserted with a sandboxed `$HOME`).
5. Constructing a source performs no I/O — the `grit --help`-with-no-config
   guarantee.
6. `teloseq` round-trips as a motif, and `""` when absent.
7. **The golden equivalence test**: for one fixture ticket, the Jira adapter (a
   recorded fixture double) and the YAML adapter produce `CurationContext`
   objects that are field-for-field equal. This is what keeps `from_yaml` the
   primary path instead of a second-class one, and it is the test that fails the
   day a Jira-only field creeps back in.

### `StorageLayout`

1. `workdir`/`curated_dir` are total over a corpus of anchors — ToL-shaped,
   non-ToL-shaped, no `assembly/draft` substring, a version suffix present and
   absent — and never raise.
2. Purity: called twice, identical results; no directory is created (asserted
   against a sandbox tree).
3. No returned path contains a glob metacharacter or an unexpanded `~`;
   `deposit_dir` either resolves or raises `LayoutUnresolved`.
4. `hap_token` is total over
   `{hap1, hap2, primary, alternate, paternal, maternal}` — the test that would
   have caught the divergent fifth alias dict.
5. `hap_roles` returns 1 role for each single-hap assembly type and 2 otherwise,
   across a fixture table.
6. `release_filename` is injective over `(hap, kind)` for fixed specimen and
   version, and round-trips through the release-manifest parser.
7. `classify(unknown)` → `None`, never an exception, never `SystemExit`; for the
   ToL adapter, a fixture table of identifiers → expected `Taxon`, including the
   longest-prefix cases that today's two divergent insect tuples disagree on.
8. `workdir` and `status`' curated-dir derivation agree by construction — there
   is only one method, so the test is that no other module derives either.

### `ReleaseTarget`

1. `validate` on a plan missing a required artifact returns error-severity
   problems, and `publish` then raises `ReleaseRefused` without writing.
2. `publish` is atomic: an induced failure part-way leaves `dest_dir`
   byte-identical to before.
3. `publish` is idempotent for an identical plan.
4. `validate` writes nothing; `publish` writes only under `dest_dir` and the
   declared deposit destinations (asserted by whole-tree snapshot).
5. No zero-byte artifact is ever created as a side effect.
6. Every written filename equals `layout.release_filename(...)` for its
   artifact.
7. `finalize` on the reference adapter returns `ran=False`,
   `marks_ticket_done=False`, and the ticket's registry status is unchanged
   afterwards.
8. Batch 5's coherence check, once its policy is settled: a plan whose chromosome
   list names scaffolds absent from its FASTA is refused.

### Step catalog (not an adapter suite, but the `ARCH-03` gate)

1. Every registered CLI command has exactly one `StepDecl`, and vice versa.
2. Every tracker step name appearing anywhere in `grit/` (string literals
   included) exists in the catalog.
3. `supports_dry_run` is *derived* from the presence of a dry-run branch (AST
   check), not asserted independently — so `ARCH-07` cannot recur.
4. Every decl's `tools`/`data` resolve under the shipped reference provider
   config, or are explicitly marked unavailable with a hint.
5. `status_label` values are drawn from the known status vocabulary — which is
   how the phantom `agp_copied` dies.

---

## Incremental seam migration

`TEST-02` is the hard constraint: 147 `@patch` decorators target private
module-level imports in 17 step modules, so the port's seam and the tests' seam
are the same lines, and ~123 tests fail on the patch target alone if the ports
land first. Verified shape of the coupling (top clusters): 20 ×
`pretext_to_asm._run`, 20 × `rename_and_orient.find_canonical_fa`, 18 ×
`rename_and_orient._submit_bsub`, 17 × `rename_and_orient.glob.glob`, 16 ×
`qv._run`, 16 × `hic_remapping._run`, 16 × `pretext_to_asm.glob.glob`.

### The mechanism: one seam, moved once, per module

The reason this can be incremental at all is that **`ctx.env` is a single new
field**. A test stops patching a module attribute and starts configuring a fake
on the context it already builds:

```python
# before
@patch("grit.steps.optional.fastga._submit_bsub")
def test_x(mock_submit, mock_ctx): ...

# after
def test_x(mock_ctx):                      # mock_ctx.env is a FakeEnvironment
    run_fastga(mock_ctx)
    assert mock_ctx.env.exec.submitted[0].memory_mb == 24000
```

That is a mechanical, reviewable diff, and it is *strictly better* than the
`@patch` it replaces: the assertion moves from "a private function was called
with this string" to "a job was requested with these semantics", which is the
rewrite report 07's test-suite verdict says is desirable anyway (only ~21
assertions in 10–12 tests encode real LSF semantics; the other ~102 breakages are
purely the patch target).

### Per-port commit shape

Each port lands as **A, then one B per step module, then C**:

- **Commit A — the port exists, nothing uses it.** Define the Protocol and value
  objects in `grit/ports/`; implement the *current* behaviour as the site adapter
  (a copy of today's code, no behaviour change); wire a composition root that
  defaults to it; write the conformance suite against it; extend
  `tests/conftest.py`'s `mock_ctx` with the `FakeEnvironment` recording fakes.
  **No production call site changes and no existing test changes.** Green by
  construction.
- **Commits B₁…Bₙ — one step module each.** Replace that module's private
  imports with `ctx.env.*` calls **and** migrate that module's tests in the same
  commit. Two files, one reviewer, green at every commit. 17 modules for Port 1's
  `_submit_bsub`/`build_bsub_opts`; 12 sites for Port 2; the `glob.glob`/
  `find_canonical_*` clusters for Port 4.
- **Commit C — delete the old free functions** (`_submit_bsub`,
  `build_bsub_opts`, `_check_bjobs`, `_state_update_epilogue`, `module_cmd`)
  once nothing imports them, and add the grep/AST test that asserts they do not
  come back.

### Two hard constraints on that shape

1. **The baseline lands before any B commit.** Commit A must include (a) the
   conformance suite against the site adapter — the tests `TEST-01` says do not
   exist for this seam — and (b) a `--print-only` golden snapshot for every step,
   captured *before* the first B commit and diffed after each. `--print-only` is
   preserved precisely because "the printed command is exactly what would run",
   which makes it the free equivalence check for the whole refactor. Without both,
   there is nothing to refactor against and the port is being introduced on
   faith.
2. **Reconcile-once lands with Port 1, not after it.** `TODO/50` re-sequenced
   Batch 6 into Phase 2 for exactly this reason: "collapse the four reconcile
   implementations" and "design `ExecutionBackend`" are the same piece of work,
   because completion detection has to live inside the contract. Concretely, the
   Port 1 A-commit introduces `domain.reconcile` and the `Evidence`/`RunOutcome`
   types; the four current reconcile sites become four callers during the B
   commits; and Commit C is where `tracker.finish` becomes domain-private and the
   AST test lands. Doing reconcile before the port means writing it against
   `bjobs` and rewriting it.

### Ordering constraints between ports

Not a roadmap — these are the dependencies the contracts impose:

- **Port 1 first.** It unblocks reconcile-once, and its test coupling is the
  cheapest to move (`_submit_bsub` clusters are concentrated in 7 modules).
- **Port 6's catalog second**, because `reconcile`'s output probe needs one
  source of truth for `decl.outputs`/`output_location`, and because it deletes
  six registries whose drift would otherwise have to be preserved through the
  later ports.
- **Port 2 third** (12 sites, self-contained), and it must precede the rerun-
  trigger work because the `software` fingerprint comes from
  `Provision.versions`.
- **Port 3 fourth**: it breaks the `click_cli ↔ steps` cycle, which every later
  refactor benefits from, and it is small.
- **Port 4 fifth.** It is deliberately late: the `glob.glob` + `find_canonical_*`
  patches are the largest test-coupling cluster (~60 decorators), and they
  migrate far more cheaply once `mock_ctx.env` already exists and the canonical
  resolvers already read an injected catalog.
- **Port 5 last**, since its `validate()` depends on Batch 5 having settled which
  fa/chr pairs are legal — a policy question this design explicitly does not
  answer.

Everything beyond that ordering — what ships when, in which branch, against
which milestone — belongs to the consolidation.

### Preserve-list check

All of `TODO/49`'s preserve items survive. Two are modified deliberately, and I
state both rather than quietly breaking them:

- **`module_cmd()`'s return type changes** from `str` to `Provision`. The
  preserved property is the *shape* — one logical key → one provisioning
  statement, one line per tool version — and it is kept (as the Lmod adapter's
  config table). The string return is exactly the defect `PORT-19`/`ABST-02`
  documents, so it cannot be preserved as-is.
- **`RunTracker.finish` stops being callable by steps.** `start`/`finish` still
  enforce `print_only` internally, at the same layer, so the invariant
  `TODO/49` preserves ("a step cannot pollute the registry in preview mode even
  if it forgets a guard") is unchanged. What changes is *who may call*
  `finish` — and that restriction is precisely what makes reconcile-once
  structural rather than a convention.

Unchanged: `CurationContext` as the single injected value object (it gains one
field and loses a constructor); the `bsub -Ep` epilogue *concept* (it becomes the
LSF adapter's implementation of `CompletionMode.CALLBACK` — the semantics are
kept, the fallbacks are what reconcile fixes); `--print-only` and `--dry-run`
including `grit --help` with no config (guaranteed by `render()`, by adapters
doing no I/O at construction, and by `supports_dry_run` becoming derived);
`collect_outputs()` and the spec tuples (they move into `StepDecl` unchanged in
shape and become *more* load-bearing, since they are now the only output truth);
`utils/output.py` + `utils/result_parsers.py` (only the LSF *log* parsers move,
into the LSF adapter, because they are scheduler syntax by definition — the
genome-file parsers stay); `recuration-canonical-priority.md` (it needs one
edit, describing the pool as a table and the new supersession record, plus the
`DOM-15` honesty pass Batch 5 owns).

---

## Ports I decided against

- **`JobRenderer` / `SchedulerSyntax` as a separate port.** Splitting "how a job
  is spelled" from "how a job is submitted" gives two adapters that must always
  be swapped together. Folded into `ExecutionBackend.render`.
- **A `Notifier` / Jira-write port.** The only Jira write in the codebase is a
  *printed reminder to the human* — there is no API call anywhere. A port for it
  would be speculative surface. Folded into `ReleaseReceipt.followups`.
- **Capability declaration as a port (Port 6 as briefed).** *Collapsed.* It has
  no alternative implementation and nothing swaps it; it is data consumed by
  ports 1, 2 and 4. Making it a port would add a wiring point with one
  implementation forever. This is the valuable collapse: the brief's sixth port
  becomes the thing that deletes six duplicated registries instead.
- **A `NamingConvention` port split out of `StorageLayout`.** Paths and names are
  always configured together as one site profile; splitting doubles the wiring
  for variation nobody has. Noted as separable if a site ever needs ToL *names*
  with non-ToL *paths* — the two method groups are already disjoint.
- **`RegistryStore` as a port** (JSON vs append-only JSONL vs sqlite). Tempting
  given `CORR-01`/`CORR-02`, but there is exactly one implementation at a time
  and no site variation: the choice is a remediation decision (`TODO/50` Batch 2),
  not an axis of environment portability. A port here would freeze a design
  before it is made. `RunTracker`'s existing fold-forward reader is already the
  abstraction that lets the store change underneath it.
- **`Clock` / `Filesystem` ports.** No seam in the inventory asks for them.
  `DOM-08`'s cross-host clock skew is fixed by consulting the run-dir ISO
  timestamps (which all come from one host) inside the canonical resolver, not by
  injecting a clock.
- **A `JobDependency` verb on `ExecutionBackend`.** grit uses no job-dependency
  syntax at all — no `-w`, no `done(jobid)`, no arrays — because sequencing is a
  human re-invoking `grit`. Report 07's verdict rests on this. Adding dependency
  support would be inventing the DAG the assessment established does not exist.
- **`JobSpec.blocking` / `-K`.** Declared in `build_bsub_opts` today with no
  caller. `LocalBackend` already *is* that semantics.

---

## Open questions for the author

1. **Is the `_state-update` callback contract allowed to change shape?** Adding
   fingerprint/version fields changes the epilogue argv, and jobs submitted by
   an older grit will call a newer CLI after an upgrade. Options: accept-and-
   ignore unknown flags, version the hidden subcommand, or accept a
   drain window. This is the one place where a contract change can break
   *in-flight* work.
2. **How should a `POLL_ONLY` backend actually get polled, now that `grit status`
   is read-only?** Candidates: a `grit reconcile` command the curator runs, a
   reconcile pass at the start of every step invocation, or both. It is a UX
   decision, not a contract one, but the contract needs the answer to know
   whether `POLL_ONLY` is a usable mode or a theoretical one.
3. **`post_process_rc`.** Can anyone read
   `/software/grit/projects/contamination_screen/conf/contamination_screen.conf`?
   Until someone can, `finalize()`'s postcondition — "exit 0 ⇒ the ticket is
   done" — is inferred from grit's own code, and marking a ticket terminally done
   off an unknown pipeline's exit status may be wrong. Carried as a placeholder
   per the scope decision; flagged as the highest-uncertainty item in Port 5.
4. **Should the release naming contract be published in-repo as a spec** (so a
   reimplementation of the downstream consumer has a target), even before
   `GritJiraIssue.get_curated_file_name_for_type()` can be read? Port 4 assumes
   yes.
5. **Rerun triggers: content hash or mtime for inputs?** Hashing fixes `DOM-09`
   (mtime-preserving copies making grit print "Already done" and run nothing) at
   the cost of reading every input on every invocation. AGPs are small; canonical
   FASTAs are not. Per-kind policy, or mtime plus size?
6. **Where does the taxonomy table live** — shipped in the public core as data, or
   only in the Sanger site profile? ToL ID clade semantics are not secret (they
   are published) but they are a ToL convention, and an off-site user's
   identifiers will not follow them.
7. **Rename `--bsub-ram` to `--memory-mb`?** The scheduler-neutral name is
   correct and the LSF name is in curators' fingers. The design assumes rename
   plus a hidden alias; say if muscle memory wins.
8. **`EXTERNALLY_SCHEDULED` completion.** Report 07 suggests treating a
   Nextflow-backed step's completion as "read the pipeline's own trace/report"
   rather than "the launcher exited". Is that worth building for
   `hic_remapping`/`microchromosome_second_shot`, or is outputs-probe-only
   (what this design specifies) sufficient?
9. **`paternal`/`maternal`.** `_detect_assembly_type` can never produce
   `paternal` (`CORR-14`), so every branch handling it is dead code — yet the
   alias table exists because the naming is expected. Should `StorageLayout`
   support the roles (and the manifest detector start producing them), or should
   they be deleted? Port 4's totality invariant needs the answer.
10. **Does `preflight` gate, or advise?** As specified it refuses before
    `tracker.start()`. A curator on a partly-provisioned site may prefer
    "warn and try anyway" with `--force`. Refusing is safer and matches the
    scope decision's motivation ("an actionable message rather than a mid-run
    failure"); confirm that is the intent.
