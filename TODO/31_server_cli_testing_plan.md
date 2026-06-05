# 31 — Server CLI Testing Plan

Goal: manually validate every `grit` CLI command against a real ticket on the farm,
confirming that each step produces the expected output, does not crash, and logs
sensibly at both `INFO` and `DEBUG` levels.

**Workflow:** you run the commands on the farm and paste the output (stdout + stderr)
back here. I analyse the output and push fixes to the `test_and_fix_steps` branch.
All changes go to that branch; pull it before each new round of testing.

---

## Prerequisites

| Item | Notes |
|---|---|
| `grit` installed in the active environment | `pip install -e .` or pixi |
| `~/.grit_curation_config.yaml` present | See template below — create before first run |
| A test ticket YAML available | Ideally one hap1/hap2 ticket **and** one primary/alternate ticket |
| LSF access | Most steps submit jobs — use `--print-only` first |
| Reference genome downloaded (for optional steps) | Needed by `find-reference`, `fastga`, `rename-and-orient`, `busco-*` |

Suggested tickets for testing: pick a recently curated insect (has microchromosomes
+ sex chromosomes) and a recently curated vertebrate (straightforward primary).

### `~/.grit_curation_config.yaml` — required fields

Create this file before running any command. All fields are required.

```yaml
# Your Sanger / farm username (used to derive the working directory path)
username: zd1

# NFS path where PretextView maps live before curation starts
pretext_maps_nfs: /nfs/team135/pretext_maps

# NFS path where the curator saves the finished PretextView session
curated_pretext_maps_nfs: /nfs/team135/curated_pretext_maps

# NFS path for PretextView save-states (.pretext sessions)
curation_savestates_nfs: /nfs/team135/curation_savestates

# Hostname of the farm submission node (used for SSH / bsub)
farm_host: farm22-login

# Your email address (used in LSF -u flag for job notifications)
email: zd1@sanger.ac.uk

# Absolute path to the directory that contains GritJiraIssue.py
# (the module used to fetch ticket YAML from Jira)
gritjiraissue_path: /path/to/GritJiraIssue
```

> **Note:** when testing with a local `--yaml ticket.yaml` file the
> `gritjiraissue_path` is never imported, so any non-empty string is fine for
> those runs.

---

## Global smoke tests

Run these before anything else to confirm the install is healthy.

```bash
grit --help
grit setup --help
grit post-curation --help
grit busco-curated --help
```

**Check:** Every command prints a help block with at least a one-line description and
lists its options. No `ImportError` or traceback.

---

## 1. Pre-curation steps

### 1.1 `setup`

**Purpose:** creates the workdir, copies the draft assembly and pretext maps, prints
the curation summary.

```bash
# Dry-run first
grit --yaml ticket.yaml --print-only setup -t RC-XXXX

# Real run
grit --yaml ticket.yaml setup -t RC-XXXX
```

**Check:**
- Workdir `<base_dir>/<tol_id>/` created. (Done)
- `original.fa` (or `.fa.gz`) present in workdir. (Done)
- Summary table printed with correct ticket, tol_id, species name, assembly type. (Done)
- Pretext maps scp command printed (Done)

---

### 1.2 `add-gap-track`

**Purpose:** adds a gap track to the pretext map.

```bash
grit --yaml ticket.yaml --print-only add-gap-track -t RC-XXXX
grit --yaml ticket.yaml add-gap-track -t RC-XXXX
```

**Check:**
- LSF job submitted (or command printed in `--print-only`).
- After job completes: pretext map contains a gap track visible in PretextView.

---

### 1.3 `add-telo-track`

**Purpose:** adds a telomere track to the pretext map.

```bash
grit --yaml ticket.yaml --print-only add-telo-track -t RC-XXXX
grit --yaml ticket.yaml add-telo-track -t RC-XXXX
```

**Check:** same pattern as gap track — job submitted, telomere track visible in map.

---

### 1.4 `add-bedgraph-track`

**Purpose:** adds a custom bedgraph coverage/signal track to the pretext map.

```bash
grit --yaml ticket.yaml --print-only add-bedgraph-track -t RC-XXXX --file coverage.bg
grit --yaml ticket.yaml add-bedgraph-track -t RC-XXXX --file coverage.bg
```

**Check:**
- `--file` is validated to exist before any job is submitted.
- Track visible in PretextView after job completes.

---

### 1.5 `sex-matcher`

**Purpose:** runs the sex-determination script against kmer data.

```bash
grit --yaml ticket.yaml --print-only sex-matcher -t RC-XXXX
grit --yaml ticket.yaml sex-matcher -t RC-XXXX
```

**Check:**
- Job submitted; result file (e.g. `sex_matcher_result.txt`) written to workdir.
- Result logged at `INFO`.

---

### 1.6 `find-reference`

**Purpose:** queries NCBI/ToLID DB and downloads the closest reference genome.

```bash
grit --yaml ticket.yaml --print-only find-reference -t RC-XXXX
grit --yaml ticket.yaml find-reference -t RC-XXXX
```

**Check:**
- Reference FASTA downloaded to workdir (or path logged).
- `ctx.reference_path` resolves to the downloaded file in subsequent steps.

---

### 1.7 `microchromosome`

**Purpose:** sets up the second-shot microchromosome curation (pre stage).

Only relevant for species with microchromosomes — verify with a known insect ticket.

```bash
grit --yaml ticket.yaml --print-only microchromosome -t RC-XXXX
grit --yaml ticket.yaml microchromosome -t RC-XXXX
```

**Check:**
- Microchromosome FASTA created.
- PretextView map for microchromosomes submitted/generated.

---

### 1.8 `microchromosome-post`

**Purpose:** post stage of microchromosome curation — combines large + small fastas.

Run **after** the curator has finished the microchromosome PretextView session.

```bash
grit --yaml ticket.yaml --print-only microchromosome-post -t RC-XXXX
grit --yaml ticket.yaml microchromosome-post -t RC-XXXX
```

**Check:**
- Combined FASTA written to workdir.
- AGP file updated/created.

---

## 2. Post-curation steps

Run these **after** the curator has finished PretextView and the curated files exist.

### 2.1 `pretext-to-asm`

**Purpose:** converts the curator's PretextView output back to an assembly FASTA + AGP.

```bash
grit --yaml ticket.yaml --print-only pretext-to-asm -t RC-XXXX
grit --yaml ticket.yaml pretext-to-asm -t RC-XXXX
```

**Check:**
- `<tol_id>.curated.hap1.fa` and/or `curated.primary.fa` written to workdir.
- AGP file present.
- No jobs still running when function returns (or job ID logged for tracking).

---

### 2.2 `haplotig-files`

**Purpose:** ensures haplotig FASTA files are in place (hap1/hap2 or primary/alternate).

```bash
grit --yaml ticket.yaml --print-only haplotig-files -t RC-XXXX
grit --yaml ticket.yaml haplotig-files -t RC-XXXX
```

**Check:**
- Both hap files (or primary + alternate) exist in workdir.
- Warning logged if a file is missing but non-fatal.

---

### 2.3 `hic-remapping`

**Purpose:** remaps HiC reads to the curated assembly.

```bash
grit --yaml ticket.yaml --print-only hic-remapping -t RC-XXXX
grit --yaml ticket.yaml hic-remapping -t RC-XXXX
```

**Check:**
- LSF array job submitted.
- `bam` / `cram` files written to workdir after job completes.

---

### 2.4 `qv`

**Purpose:** computes QV (quality value) metrics for the curated assembly.

```bash
grit --yaml ticket.yaml --print-only qv -t RC-XXXX
grit --yaml ticket.yaml qv -t RC-XXXX
```

**Check:**
- QV result file (`*.qv`) written to workdir.
- QV value logged at `INFO`.

---

### 2.5 `validate-files`

**Purpose:** checks that all required curated files are present and well-formed.

```bash
grit --yaml ticket.yaml validate-files -t RC-XXXX
```

**Check:**
- Passes silently when all files are present.
- Exits non-zero and logs `ERROR` when a required file is missing.
- Try intentionally removing one file and re-running to confirm error path.

---

### 2.6 `finalize-qc`

**Purpose:** copies curated files to the QC staging area / iRODS handoff location.

```bash
grit --yaml ticket.yaml --print-only finalize-qc -t RC-XXXX
grit --yaml ticket.yaml finalize-qc -t RC-XXXX
```

**Check:**
- Destination directories exist or are created.
- Files copied/linked correctly.
- Log shows source → destination mapping.

---

### 2.7 `post-curation` (full pipeline)

**Purpose:** runs all post-curation steps in order: `pretext-to-asm` → `haplotig-files`
→ `hic-remapping` → `qv` → `validate-files` → `finalize-qc`.

```bash
grit --yaml ticket.yaml --print-only post-curation -t RC-XXXX
grit --yaml ticket.yaml post-curation -t RC-XXXX
```

**Check:**
- Each sub-step logs its start.
- Pipeline aborts at the failing step (not silently continues).
- End-to-end: all QC-ready files present after successful run.

---

## 3. Optional steps

### 3.1 `blast-contaminants`

**Purpose:** runs BLAST against contamination databases in the Shrapnel service.

```bash
grit --yaml ticket.yaml --print-only blast-contaminants -t RC-XXXX
grit --yaml ticket.yaml blast-contaminants -t RC-XXXX
```

**Check:**
- LSF job submitted to Shrapnel queue.
- Contamination report file written to workdir.

---

### 3.2 `busco-curated`

**Purpose:** runs BUSCO completeness check on the curated assembly.

```bash
grit --yaml ticket.yaml --print-only busco-curated -t RC-XXXX --lineage insecta_odb10
grit --yaml ticket.yaml busco-curated -t RC-XXXX --lineage insecta_odb10
```

**Check:**
- `--lineage` is required — confirm `UsageError` when omitted.
- BUSCO output directory created in workdir.
- Summary table logged at `INFO`.

---

### 3.3 `busco-synteny`

**Purpose:** runs BUSCO synteny analysis between curated assembly and reference.

```bash
grit --yaml ticket.yaml --print-only busco-synteny -t RC-XXXX --lineage insecta_odb10
grit --yaml ticket.yaml busco-synteny -t RC-XXXX --lineage insecta_odb10
```

**Check:** same as `busco-curated`, plus a synteny plot or table in workdir.
Requires reference to be already downloaded (run `find-reference` first).

---

### 3.4 `fastga`

**Purpose:** runs FastGA dot-plot comparison of curated assembly vs reference.

```bash
grit --yaml ticket.yaml --print-only fastga -t RC-XXXX
grit --yaml ticket.yaml fastga -t RC-XXXX
```

**Check:**
- Reference path resolved from context (or `--reference` override if implemented).
- FastGA output (`.png` / alignment file) written to workdir.

---

### 3.5 `rename-and-orient`

**Purpose:** renames and orients scaffolds to match the reference naming convention.

```bash
grit --yaml ticket.yaml --print-only rename-and-orient -t RC-XXXX
grit --yaml ticket.yaml rename-and-orient -t RC-XXXX
```

**Check:**
- AGP / FASTA with renamed scaffolds written to workdir.
- Mapping table logged or saved to workdir.

---

## 4. Cross-cutting checks

Run these for at least two commands (one simple, one complex).
Paste the **full terminal output** (stdout + stderr) when sending results.

### 4.1 Logging levels

```bash
# Should show step start + major decisions only
grit --logging-level INFO --yaml ticket.yaml setup -t RC-XXXX

# Should also show LSF command strings, resolved paths
grit --logging-level DEBUG --yaml ticket.yaml setup -t RC-XXXX
```

**Expected:** `DEBUG` output contains full command strings and path resolutions;
`INFO` output is concise (no raw command strings).

### 4.2 `--print-only` mode

Always run every command with `--print-only` first before the real run.

```bash
grit --yaml ticket.yaml --print-only setup -t RC-XXXX
```

**Expected:** No LSF jobs submitted; commands printed to the log instead.

### 4.3 Error handling

Force a failure (e.g. rename a required input file) and run any command.
Then restore the file.

```bash
grit --yaml ticket.yaml setup -t RC-XXXX
echo "exit code: $?"
```

**Expected:**
- Exit code is non-zero.
- `ERROR` logged with Rich traceback.
- Error message clearly names the missing file — no silent swallowing.

### 4.4 Missing config

```bash
grit --config /nonexistent.yaml setup -t RC-XXXX
```

**Expected:** clean error message, not an unhandled Python exception.

### 4.5 Missing ticket option

```bash
grit --yaml ticket.yaml setup
```

**Expected:** `UsageError: Missing option '--ticket'` (or `-t`).

---

## 5. Test matrix

Fill in after each server run:

| Command | hap1/hap2 ticket | primary ticket | `--print-only` | Notes |
|---|---|---|---|---|
| `setup` | ⬜ | ⬜ | ⬜ | |
| `add-gap-track` | ⬜ | ⬜ | ⬜ | |
| `add-telo-track` | ⬜ | ⬜ | ⬜ | |
| `add-bedgraph-track` | ⬜ | ⬜ | ⬜ | needs `.bg` file |
| `sex-matcher` | ⬜ | ⬜ | ⬜ | |
| `find-reference` | ⬜ | ⬜ | ⬜ | |
| `microchromosome` | ⬜ | — | ⬜ | insect only |
| `microchromosome-post` | ⬜ | — | ⬜ | insect only |
| `pretext-to-asm` | ⬜ | ⬜ | ⬜ | |
| `haplotig-files` | ⬜ | ⬜ | ⬜ | |
| `hic-remapping` | ⬜ | ⬜ | ⬜ | |
| `qv` | ⬜ | ⬜ | ⬜ | |
| `validate-files` | ⬜ | ⬜ | ⬜ | |
| `finalize-qc` | ⬜ | ⬜ | ⬜ | |
| `post-curation` | ⬜ | ⬜ | ⬜ | full pipeline |
| `blast-contaminants` | ⬜ | ⬜ | ⬜ | |
| `busco-curated` | ⬜ | ⬜ | ⬜ | needs `--lineage` |
| `busco-synteny` | ⬜ | ⬜ | ⬜ | needs `--lineage` + ref |
| `fastga` | ⬜ | ⬜ | ⬜ | needs ref |
| `rename-and-orient` | ⬜ | ⬜ | ⬜ | needs ref |

Legend: ✅ pass · ❌ fail (link issue) · ⬜ not yet tested · — not applicable
