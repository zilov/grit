# Phase 2 / A — Capability parity: replacing every Sanger-internal dependency

Read-only research pass. Input: `TODO/49_architecture_assessment.md` (settled verdicts),
`TODO/50_assessment_remediation.md` § "Scope decision — 2026-09-03" (charter: **all 21 steps must
work outside Sanger**), `TODO/claude/assessment/04_portability_seam_inventory.md` (the 125-seam map).
Every dependency below was re-verified against the code at `9175121`; every external claim was
verified against a live source and is cited in `## Sources`.

Scope of this document: **per-dependency substitution decisions with evidence**. No port design, no
packaging, no migration sequencing — those belong to other Phase 2 agents.

Taxonomy is fixed by the scope decision: **vendor** / **swap** / **recover-data** / **reimplement**.

---

## Summary

**The six steps are not equally hard, and the difficulty does not follow the code volume.**

- Two steps are *code* problems with clean public answers: `find-reference` (reimplement two small
  clients over the public NCBI Datasets CLI + taxonomy) and the microchromosome pair (vendor the
  author's own scripts — with one large caveat below).
- One step is a *data* problem: `sex-matcher`. Its four BUSCO-ID lists are **not derivable from
  public BUSCO lineage files** — odb10 datasets contain HMMs, cutoffs and ancestral sequences and
  carry no chromosome assignment at all (verified against the BUSCO user guide's dataset file list).
  They are curation work product. Either `da16` grants permission, or they are *regenerated* from
  published chromosome-level assemblies — reproducible, but the regenerated lists will not be
  identical and calls will differ at the margin.
- One step is a *product* problem disguised as a code problem: `blast-contaminants`. A public
  first-party replacement exists and is excellent (NCBI FCS-GX; public domain; bioconda), but its
  database is **470 GiB with a 512 GiB RAM requirement**. The public ToL equivalent
  (`sanger-tol/ascc`, MIT) wraps FCS-GX plus five other screens and needs *more* data, not less.
  There is no configuration of this step that a lone external user on a laptop can run. Portable ≠
  usable.
- One step has no substitution point at all: `post-processing`. `post_process_rc` is a shell alias.
  I did not design a replacement, per the charter. What I did instead is pin down its **observable
  contract** exactly (§ post-processing) and produce the question list.
- Plus a sixth item the brief folded in: the five `/software/grit/projects/vgp_curation_scripts/*`
  scripts. Two of the three "probably public GPL-ish vendored copies" suspicions were checked:
  `ragtag_paf2delta.py` **is** RagTag's (MIT — fine); `dgenies_index.py` **is not in D-GENIES
  upstream** (upstream's file is `src/dgenies/bin/index.py`), so its provenance and licence remain
  genuinely unknown and it may be Sanger's own code writing a D-GENIES-format index.

**Two corrections to Phase 1 that matter for this design.**

1. `TODO/49` (§ Orchestration verdict) states "`hic_remapping.py:99-116` **and `find_reference.py`**
   invoke the Nextflow pipeline `curationpretext`". `find_reference.py` does not: `grep -rn
   curationpretext grit/` hits only `hic_remapping.py` (plus a comment in `status.py` and a config
   comment). `find-reference` has **no** public-pipeline dependency to build on; its whole Sanger
   surface is two small internal executables. This makes it easier, not harder, than the assessment
   implies.
2. `pretext-to-asm` was flagged as a "core blocker candidate" (`04`, external-tool table). It is
   **not a blocker**: it is a public MIT entry point of `sanger-tol/agp-tpf-utils`, with a CLI that
   matches grit's invocation (`-a` assembly, `-p` pretext AGP, `-o` output). It is not on PyPI or
   bioconda — install is git-based — but licence and availability are settled. Recorded here because
   it is upstream of five of the steps in this document.

**The honest bottom line on external usability** (full table in
§ "Usable by an outsider vs needs institutional infrastructure"): of the 21 steps, roughly 12 are
genuinely runnable by one person on a workstation once the code seams are fixed. `sex-matcher`,
`busco-curated` and `busco-synteny` need a BUSCO lineage download (single-GB, fine) plus, for
sex-matcher, recovered data. `blast-contaminants` and `post-processing` will always need
institutional infrastructure or a hosted service; saying otherwise in a README would be dishonest.

---

## Substitution table

| Dependency | Step(s) | Kind | Replacement | Licence | Bioconda? | Effort | Behavioural difference |
|---|---|---|---|---|---|---|---|
| `~mh6/git_checkouts/reblast/bin/decon_fasta` | blast-contaminants | **swap** | Tier 1: `sanger-tol/ascc` (public ToL equivalent). Tier 2: `ncbi-fcs-gx` direct. Tier 3: `blastn` vs `core_nt` + taxonomy join (closest to today's output) | ASCC MIT; FCS-GX US-Gov public domain; BLAST+ public domain | ASCC no (Nextflow); `bioconda::ncbi-fcs-gx` 0.5.5 **yes**; `bioconda::blast` yes | **L** | **Large.** See § blast-contaminants. Different call semantics (action verbs vs top-hit phylum), needs a tax-id not a phylum name, measurably different sensitivity/precision |
| Unnamed BLAST nt-class DB inside `decon_fasta` | blast-contaminants | **recover-data** (identity unknown) | Cannot be named from the repo. If it is `nt`/`core_nt`, both are public: core_nt ≈ 220 GB, nt ≈ 625 GB (FTP volume listing) | NCBI, unrestricted | n/a | S to *find out*, L to *ship* | The identity determines whether today's calls are even reproducible |
| `~mh6/remove_contamination_bed` | blast-contaminants | **reimplement** | `seqkit grep -v -f <ids>` or 15 lines of Python. grit's BED is a synthetic `0..10000` interval per scaffold and the semantics are "drop the whole sequence", so an ID-list filter is exact | seqkit MIT | `bioconda::seqkit` yes | **S** | None, and it removes the `<name>_cleaned` sibling-file convention grit currently has to `mv` |
| `get_lineage_from_species.rb` | blast-contaminants | **swap** | `datasets summary taxonomy taxon "<sp>"` (ncbi-datasets-cli) or `taxonkit lineage -R` + taxdump | NCBI public domain / taxonkit MIT | `conda-forge::ncbi-datasets-cli` yes; `bioconda::taxonkit` yes | **S** | Improves it: ask for `rank=phylum` explicitly instead of `lineage.split(";")[3]`, which is fragile today (`blast_contaminants.py:149`) |
| `/nfs/users/nfs_d/da16/…/{coleop_X,lep_Z,nematode_X,dip_LG6}_buscos` | sex-matcher | **recover-data** | Permission from `da16`, **or** regenerate: BUSCO a published chromosome-level assembly of the clade, keep `Complete` BUSCOs whose `Sequence` is the known Z/X | unknown / unrecorded | n/a | **S** with permission, **M** to regenerate | Regenerated lists differ from `da16`'s → marginal calls change. Not derivable from BUSCO lineage files (verified) |
| `/software/…/vgp_curation_scripts/sex_matcher.py` | sex-matcher | **reimplement** | ~30 lines: count sex-linked BUSCO hits per scaffold from `sex_table.tsv`, rank descending, write `Best_match*` CSV | unknown | n/a | **S** | Contract is fully observable from `parse_sex_matcher` (`result_parsers.py:104`) — see § sex-matcher |
| `busco.sif` in `~mh6/singularity/`, `source ~mh6/sing.bash` | sex-matcher, busco-curated, busco-synteny | **swap** | `bioconda::busco` env, or the public biocontainer | BUSCO MIT | yes (`busco`, 6.1.0 current) | **S** | None, if the BUSCO major version is pinned. Today's SIF version is unrecorded — a silent behaviour change risk |
| `/lustre/…/busco/latest/lineages` | sex-matcher, busco-curated, busco-synteny | **recover-data** (public) | `busco-data.ezlab.org/v5/data/lineages/`, or AWS Open Data `busco-data`; BUSCO auto-downloads | public | n/a | **S** | The `latest` symlink must be replaced by a pinned version — today's runs are not reproducible across time (already noted in `04`) |
| ToL-ID-prefix clade gate (`exit 1`) | sex-matcher | **reimplement** | An explicit `--clade {coleoptera,lepidoptera,diptera,nematoda}` plus a capability precheck | n/a | n/a | **S** | Removes "taxonomy encoded in a filename prefix" — a hard non-ToL blocker today (`PORT-11`) |
| `get_nearest_comparator.rb` | find-reference | **reimplement** | NCBI Datasets CLI (`datasets summary/download genome taxon … --assembly-level chromosome`) + taxonomy walk-up via `taxonkit`/Datasets taxonomy | NCBI public domain / MIT | `conda-forge::ncbi-datasets-cli`, `bioconda::taxonkit` | **M** | "Nearest" ranking will differ from the Ruby script's undocumented heuristic. Must be documented as a new, stated selection rule, not presented as identical |
| `reheader` (from `module load grit`) | find-reference (+ fastga, busco-synteny consumers) | **reimplement** | Rename reference chromosome headers to `chr_n`/`chrN`; `seqkit replace` or ~20 lines | unknown | n/a | **S** | Exact mapping rule (NCBI header field → number, unplaced-scaffold naming) is **unverified**; must reproduce the prefixes `busco_synteny_format_and_plot.py:63` detects |
| `~dz11/…/birds_microchromosomes/microchr_second_shot_curation.py` | microchromosome-second-shot | **vendor** (licence) + **reimplement** (execution) | Move into `grit/scripts/`. But it submits its own `bsub -K` jobs internally → vendoring does not make it portable | author's own | n/a | **M–L** | Its embedded LSF calls are invisible to grit's executor seam — the exact failure class CLAUDE.md already documents. Unreadable from this machine: see § microchromosome pair |
| `~dz11/…/birds_microchromosomes/combine_curated_micros.py` | microchromosome-combine | **vendor** | Move into `grit/scripts/`. Pure file-merge CLI (`-l -s -o --large-chr --small-chr --chr-output`) | author's own | n/a | **S** | Likely none; unverified dependencies |
| `/nfs/users/nfs_d/dz11/hap_bedgraph.py` | add-gap-track (currently commented out of the CLI) | **vendor** or **reimplement** | N-run intervals from `original.fa` → bedgraph on stdout; ~20 lines | author's own | n/a | **S** | None |
| `post_process_rc` (shell alias from `/software/grit/projects/contamination_screen/conf/contamination_screen.conf`) | post-processing | **reimplement** — needs Sanger access | **No design proposed.** Observable contract documented in § post-processing; question list in § post_process_rc | unknown | n/a | **unknown** | Unknown. Gates the ticket's `done` state and grit verifies nothing about it |
| `ragtag_paf2delta.py` | fastga (`FastGA_dot_dgenies_stats.sh`) | **swap** (or vendor with attribution) | `bioconda::ragtag` — the file exists at RagTag's repo root, MIT | MIT | `bioconda::ragtag` 2.1.0 | **S** | None. MIT permits vendoring with the notice retained |
| `dgenies_index.py` | fastga | **reimplement** | **Does not exist in D-GENIES upstream** (upstream has `src/dgenies/bin/index.py`), so the vendored-GPL assumption is unconfirmed. The index is a trivial `name` + `seq\tlength` text file — reimplement (~15 lines) and avoid D-GENIES' GPL-3.0 entirely | **unknown** (D-GENIES itself is GPL-3.0) | `bioconda::dgenies` exists | **S** | None if the format is reproduced |
| `DotPrep.py` | fastga | **swap/vendor** | `dnanexus/dot`, MIT, file confirmed present at repo root; no versioned release, not on conda | MIT | no | **S** | None. Vendor with the MIT notice, since there is no package to depend on |
| `pretext-to-asm` (`module load grit`) | pretext-to-asm & 3 recurate/micro variants | **swap** | `sanger-tol/agp-tpf-utils` — public, MIT, entry point `pretext-to-asm`, CLI matches grit's `-a/-p/-o` | MIT | **no** (not on PyPI or bioconda; git install) | **S** | None expected; verify AGP dialect against a real run. *Not one of the six steps, but it was Phase 1's "core blocker candidate" and it is resolved* |
| `kmer_completeness.bash` (`module load grit`) | qv | **reimplement** | Wrap `merquryfk` + `fastk` directly | both BSD-3-Clause | `bioconda::merquryfk`, `bioconda::fastk` | **M** | Output layout must match what `cleanup.py:76-78` and `finalize_qc`'s `merquryk/` check expect |
| `curationpretext.sh -profile sanger` | hic-remapping | **swap** (profile only) | `sanger-tol/curationpretext` v1.6.1, MIT — replace `-profile sanger,singularity` with a generic profile | MIT | n/a (Nextflow) | **S** | None beyond resource defaults |
| `GritJiraIssue` via `sys.path` | context, finalize-qc release names | (belongs to the `MetadataSource` port, not this doc) | — | internal | n/a | — | Recorded because `finalize_qc`'s output filenames — the *input* to `post_process_rc` — are governed by `get_curated_file_name_for_type()`, which is out of repo |

---

## blast-contaminants

**What grit actually does today** (`grit/steps/optional/blast_contaminants.py`), per haplotype:

1. `get_lineage_from_species.rb <species>` → a `;`-delimited lineage; grit takes element **3**
   (`lineage_parts[3]`) as the target phylum, defaulting to `"Unknown"`.
2. `decon_fasta --fasta <canonical fa> --outdir <run_dir>/<hap>/blast_out_dir`. The docstring at
   `blast_contaminants.py:33-35` says it blasts headers matching `.*SCAFFOLD_\d+.*` and writes
   `taxonomy.txt` with a lineage per BLAST hit. **Only `taxonomy.txt` is ever read by grit.**
3. `grep -v <target_phylum> taxonomy.txt | perl -anE 'say "$F[0]\t0\t10000\tREMOVE"' >> contaminated.bed`
4. If the BED is non-empty: `remove_contamination_bed -f <fa> -c <bed>`, then `mv <fa>_cleaned` to
   `<tol_id>.<hap>.<release>.decontaminated.fa`, which becomes canonical.

So grit's whole dependency on `decon_fasta` reduces to: *give me, for each unplaced scaffold, a
taxonomic lineage string whose text I can grep for the target phylum name.* That is a narrow and
replaceable contract — which is the good news. The bad news is everything about the data.

**The database is unnamed and it matters.** `decon_fasta` lives in `~mh6/git_checkouts/reblast/`; I
searched for a public `reblast` / `decon_fasta` and found nothing. Its database is invisible from
grit's source. Until someone reads that checkout, we cannot say whether today's calls are
reproducible at all. **Settle by:** `ls ~mh6/git_checkouts/reblast` and reading its config for a
`-db` argument. One command; nobody has run it.

**Substitution, in the order I would recommend it:**

*Tier 1 — `sanger-tol/ascc` (MIT).* This is the best possible answer under the brief's own rule
("a public ToL equivalent of an internal script is the best possible answer"). ASCC is ToL's public
Nextflow pipeline for exactly this job: cobiont and contaminant identification, wrapping FCS-GX,
Tiara, sourmash, Kraken2, BLAST, Diamond, VecScreen, BlobToolKit and BUSCO, each individually
switchable (`['both','genomic','organellar','off']`). Its `autofilter/` outputs are
`ABNORMAL_CHECK.csv`, `autofiltered.fasta`, `assembly_filtering_removed_sequences.txt` and
`fcs-gx_alarm_indicator_file.txt`.

There is direct corroborating evidence in the author's own workspace that this is the intended
direction: `/Users/dz11/curations/contamination_check/` contains
`{sample}_ABNORMAL_CHECK.csv` files with exactly ASCC's `scaff, fcs_gx_action, sourmash_action,
tiara_action, combined_action, combined_action_source` columns, an `error_logs_ascc/` directory, and a
`contamination_check_metrics.csv` benchmarking FCS-GX / sourmash / Tiara against a HiC-derived ground
truth. That is not a design document, but it is strong evidence about what "the public equivalent"
is and that the author has already been measuring it.

Adopting ASCC also *changes the shape of the step*: `autofiltered.fasta` and
`assembly_filtering_removed_sequences.txt` replace both the taxonomy-grep and
`remove_contamination_bed`. grit would go from "parse a lineage table, build a BED, filter" to
"launch a pipeline, accept its filtered FASTA and its removed-sequence list". Simpler grit, more
external machinery.

*Tier 2 — FCS-GX directly.* `bioconda::ncbi-fcs-gx` 0.5.5 exists; licence is a US Government Work
public-domain notice (quoted in Sources); requires `--tax-id`, produces
`<name>.<taxid>.taxonomy.rpt` and `<name>.<taxid>.fcs_gx_report.txt` with EXCLUDE/TRIM/FIX actions.
Cheaper to wire than a Nextflow pipeline, and the `taxonomy.rpt` is the closest structural analogue
to today's `taxonomy.txt`. Needs a species→tax-id lookup, which the `get_lineage_from_species.rb`
replacement provides anyway.

*Tier 3 — plain BLAST+ against `core_nt`.* The most faithful reproduction of today's behaviour:
`blastn -db core_nt -outfmt "6 qseqid staxids ..."` plus a taxid→lineage join gives a drop-in
`taxonomy.txt` and leaves the existing grep/BED/filter logic untouched. Smallest code change,
largest data burden relative to value.

**Behavioural differences, stated plainly, not smoothed over:**

- Today's rule is *"top-hit lineage does not contain the target phylum name → remove the scaffold"*.
  FCS-GX's rule is its own contamination model emitting EXCLUDE/TRIM/FIX. These do not agree.
- The author's own measurements on `icCatNigr1_HAP1` (`contamination_check_metrics.csv`) put
  `fcs_strict` at sensitivity 0.409 / precision 0.988 against a HiC-derived ground truth. Whatever
  `decon_fasta`'s numbers are, they are not these. A swap therefore removes a **different set of
  scaffolds**, and curators will see a different assembly. This must be released as a new tool with
  a documented changeover, not as a refactor.
- Today's step is scoped to `SCAFFOLD_\d+` headers only (unplaced shrapnel). FCS-GX and ASCC screen
  the whole assembly. Either grit pre-subsets the FASTA, or the step's scope silently widens to
  include named chromosomes — which interacts with `DOM-05` (the excluded-from-chr-list-pool
  premise) and would make that premise *more* false, not less.
- `"Unknown"` as a target phylum currently means the grep matches nothing and *every* scaffold is
  marked for removal. Any replacement must make an unresolvable species a hard error.

---

## sex-matcher

**Four blockers, three different kinds.**

**1. The BUSCO ID lists — `recover-data`, and the one genuinely irreplaceable artifact.**
`grit/scripts/sex-matcher.sh:12-14,21,25,29,35` reads four files from `da16`'s home:
`coleop_X_buscos`, `lep_Z_buscos`, `nematode_X_buscos`, `dip_LG6`. The script greps
`full_table.tsv` for those IDs to build `sex_table.tsv`; everything downstream is arithmetic on the
result. Without the lists the step is inert.

Are they derivable from public BUSCO lineage data? **No.** An odb10 lineage dataset contains
`hmms/`, `prfl/`, `scores_cutoff`, `lengths_cutoff`, `info`, `ancestral`, `ancestral_variants`,
`refseq_db.faa.gz`, `dataset.cfg` and sometimes `links_to_ODB10.txt` — no chromosome or linkage-group
assignment anywhere. Sex-linkage is not a property BUSCO records. These lists are curation work
product.

Two routes:

- *Permission.* Four small text files. `da16` says whether they are internal work product or
  transcribed from a publication (in which case cite it). This is the cheap route and it preserves
  behaviour exactly.
- *Public regeneration.* Fully reproducible and grit already contains the machinery: for each clade,
  take a published chromosome-level assembly with an established Z/X (Lepidoptera Z, Coleoptera X,
  Nematoda X), run BUSCO with the matching lineage, and keep the `Complete` BUSCOs whose `Sequence`
  column is that chromosome — which is precisely the parse
  `busco_synteny_format_and_plot.py:75-90` already performs. Deliverable: a small script plus the
  named source assemblies, so the lists become versioned, citable data instead of four unattributed
  files. **But:** the regenerated lists will not equal `da16`'s, so scaffold rankings shift at the
  margin, and choosing the source assembly per clade is a scientific judgement, not an engineering
  one.
- `dip_LG6` is the odd one out: the name suggests a *linkage group*, not an X/Z, and the Diptera
  branch of the script is reached for `tol_id` prefix `id`. What "LG6" refers to, and why it is the
  sex-linkage proxy for Diptera, is **unknown from the repo** and I will not guess.

**2. `sex_matcher.py` — `reimplement`, small, contract fully observable.**
Invocation: `sex_matcher.py -p $myDirPath -i $myTolPrefix`, where `-p` is a directory containing
`sex_table.tsv` (the ID-filtered BUSCO full table) and `-i` is a single clade letter (`c`, `l`, `d`
from `tol_id[1]`, or `n`). Output: files matching `Best_match*` in that directory. Their format is
pinned by grit's own reader, `parse_sex_matcher` (`result_parsers.py:104-118`): a header line, then
comma-separated rows whose first two fields are `(scaffold, count)`, presented top-N — i.e. per-scaffold
counts of sex-linked BUSCO hits, ranked descending. That is a ~30-line reimplementation.

Two hazards to carry forward: `STEP_MANIFESTS["sex_matcher"]` expects `Best_match*.txt` in
**workdir** while the step globs `Best_match*` in **run_dir** (this is `CORR-10`/`CORR-13`/`ARCH-19`
— three assumed locations); and the real filename suffix is unverified. A reimplementation should
fix the location and name by declaration rather than inherit the ambiguity.

**3. The BUSCO container and lineage path — `swap` + `recover-data`, both easy.**
`source /nfs/users/nfs_m/mh6/sing.bash` and a `busco.sif` in a personal directory become
`bioconda::busco` (MIT, 6.1.0 current). `/lustre/scratch122/tol/resources/busco/latest/lineages`
becomes a configured path with a **pinned** lineage version; BUSCO downloads lineages itself, and
they are also on AWS Open Data. The four lineages this step uses — `endopterygota_odb10`,
`lepidoptera_odb10`, `diptera_odb10`, `nematoda_odb10` — are each in the low GB.

**4. The clade gate — `reimplement`.** `sex_matcher.py:86-95` `exit 1`s when `tol_id` does not start
with `ic`/`il`/`id`/`n`. That encodes ToL's naming convention as a hard precondition (`PORT-11`) and
is the single most visible "this tool is not for you" moment for an outsider. Replace with an
explicit `--clade` option (defaulting to prefix inference when the ID looks like a ToL ID) and a
capability precheck that names the missing ID list and how to obtain it. Note the prefix tuple is
also defined twice with different contents in the repo (`("ic","il","id","n")` vs `("ic","il","id")`)
— see `TODO/50` Batch 8.

Also relevant and already queued: `sex-matcher.sh` ends in an unconditional `exit 0` (`CORR-03b`),
so this step reports success whether or not any of the above worked.

---

## find-reference

**Smaller than the assessment suggests.** Two internal executables, nothing else:

| Piece | Status |
|---|---|
| `get_nearest_comparator.rb` (`/software/…/vgp_curation_scripts/`) | internal Ruby, licence unknown |
| `reheader` (via `module load grit`) | internal, licence unknown, provenance unknown |
| `module_cmd('GRIT')` preamble | the generic lmod seam, not step-specific |
| `--local` path | **already portable** — `_prep_local_reference` only needs `gunzip` + `reheader` |
| `curationpretext` | **not used by this step.** Phase 1 says it is; the code says otherwise |

Everything this step *fetches* is public NCBI data. Only the client is internal.

**`get_nearest_comparator.rb` → reimplement (M).** Observable contract:
`get_nearest_comparator.rb -s "<species>" -d -n <number>`, run with cwd = run_dir, downloading
`<n>` reference FASTAs (`*.fa.gz`/`*.fna.gz`/`*.fa`/`*.fna` — the globs
`_reheader_downloaded_references` sweeps) into that directory. Public replacement:

- `datasets summary genome taxon "<species>" --assembly-level chromosome --as-json-lines` to
  enumerate candidates, `datasets download genome accession <acc>` to fetch
  (`conda-forge::ncbi-datasets-cli`, NCBI public-domain notice).
- "Nearest" needs a taxonomic distance: walk up the lineage from the query species (via
  `taxonkit lineage`/`taxonkit taxid-changelog`, MIT, `bioconda::taxonkit`, or the Datasets taxonomy
  endpoints) and take the first ancestor rank with a chromosome-level assembly, preferring RefSeq
  reference/representative genomes.

**Behavioural difference:** the Ruby script's ranking heuristic is undocumented, so a
reimplementation will sometimes pick a *different* comparator. Since the comparator only feeds
visual/synteny QC (`fastga`, `busco-synteny`), a different-but-defensible choice is acceptable — but
the new rule must be written down and the step should print which assembly it chose and why. Do not
claim parity.

**`reheader` → reimplement (S), with an unverified detail.** Its job is inferable: rename a
reference's chromosome headers to the `chr_n`/`chrN` convention that
`busco_synteny_format_and_plot.py:60-73` detects (alongside `SUPER_n` for curated ToL assemblies),
writing `{prefix}_reheader.fna`. What is **not** verifiable from the repo: how it maps an NCBI header
(`>NC_012345.1 Genus species chromosome 7, whole genome shotgun sequence`) to a number, and what it
does with unplaced scaffolds, plasmids and organelles. Settle by running `reheader` on one NCBI FASTA
and diffing headers, or by reading the `grit` module's `bin/`. A replacement that gets the numbering
wrong produces a silently mis-labelled synteny plot — a quiet failure, so this needs a test with a
recorded fixture.

---

## microchromosome-second-shot and microchromosome-combine

**I could not read either script.** `/nfs` and `/software` are not mounted on this machine
(`ls /nfs` → No such file or directory). Everything below is inferred from grit's invocations,
output specs and comments, and each inference is marked. The list of things that must be checked by
someone with farm access is at the end of this section.

**Licensing: `vendor`, and it is the easy half.** Both scripts are under
`/nfs/users/nfs_d/dz11/gitlab/vgp_curation_scripts/birds_microchromosomes/` — `dz11` is grit's
author, and the code comments in both step files call this a **TEMP** pointer at his own unmerged
branch, to be reverted to `/software/…/vgp_curation_scripts/` once it lands. So: his own code, in
his own checkout. Moving it into `grit/scripts/` removes the seam and needs no third party's
permission — subject to whatever institutional claim exists over `vgp_curation_scripts` as a whole
(the same open question as the five `/software` scripts).

**Portability: `combine_curated_micros.py` is simple; `microchr_second_shot_curation.py` is not.**

`combine_curated_micros.py` is invoked (`microchromosome_combine.py:214-220`) as
`-l <large_fa> -s <small_fa> -o <merged_fa> --large-chr <..> --small-chr <..> --chr-output <..>` —
a pure per-haplotype file merge of a large-scaffold set with a curated small-scaffold set, plus the
two chromosome lists. Almost certainly self-contained Python + a FASTA parser. **Vendor, S.**

`microchr_second_shot_curation.py` is a different animal. Invoked
(`microchromosome_second_shot.py:150-156`) as
`-hap1 <fa> -hap1_chr <csv> [-hap2 <fa> -hap2_chr <csv>] -hic <dir> -lr <dir>/fasta -rt <read_type> -o <run_dir>`,
and grit's own docstring states it "splits the assembly into large (>20 Mbp) and small (≤20 Mbp)
scaffolds and runs HiC remapping on the merged small scaffolds", and that **"the script blocks
internally on its own `bsub -K` MicroFinder/merge jobs"** — which is why grit runs it synchronously
with `capture=False`.

That last sentence is the finding. Vendoring the file into the repo does **not** make this step
portable, because the file contains its own scheduler calls. This is exactly the failure class
CLAUDE.md already documents: *"if a step instead shells out to an external script that submits (or
backgrounds) its own async work internally, grit never sees a job it can attach an epilogue to."*
Here it is worse than the tracked-status problem, because the embedded `bsub -K` is a hard LSF
dependency inside code that Phase 2 intends to ship to non-LSF users. So the honest classification
is **vendor for licensing, reimplement/adapt for execution** — the internal job submission has to be
lifted out into grit's executor seam (or replaced by in-process work), which is the same piece of
work as `PORT-02`/borrowed-pattern-1 and should be sequenced with it.

It also almost certainly depends on a HiC-remapping tool stack of its own (it produces
`hic/pretext_maps_processed/*hr.pretext`, i.e. the same artifact `curationpretext` produces), plus
`module load` for those tools — so its dependency closure may be as large as `hic-remapping`'s.

**Declared outputs, per grit's specs** — and note grit's own comment says these globs are *inferred
from its documented output structure, not yet exercised against real output*
(`microchromosome_second_shot.py:33-36`):
`*.hap{1,2}.large.fa`, `*.hap{1,2}.large.chr_list.csv`, `*_curated_small_merged.fa`,
`hic/pretext_maps_processed/*hr.pretext`. Combine's: `{tol_id}.hap{1,2}.fa`,
`{tol_id}.hap{1,2}.chromosome.list.csv`. Both scripts always use the literal `hap1`/`hap2` tokens
regardless of the ticket's YAML keys (documented at `microchromosome_combine.py:31-38`).

**Must be checked on the farm before this pair can be planned:**

1. `head -50` both scripts: shebang, imports, third-party dependencies, embedded absolute paths.
2. Every `bsub` / `subprocess` / `os.system` call inside `microchr_second_shot_curation.py` — what
   it submits, with what resources, and whether `-K` blocking is load-bearing.
3. What "MicroFinder" is and whether it is a separate internal tool (it is named nowhere else in
   grit).
4. What performs the internal HiC remapping — `curationpretext`, or a hand-rolled
   minimap2/bwa + yahs + PretextMap chain.
5. Whether the 20 Mbp large/small threshold is a CLI flag or hardcoded (it is bird-specific; other
   clades will need it configurable).
6. Whether the real output filenames match the six inferred globs above.
7. Any `module load` lines, and whether the versions agree with `MODULE_VERSIONS`.
8. Whether the `vgp_curation_scripts` repo (gitlab) carries a licence or a Sanger IP header.

**`hap_bedgraph.py`** (`/nfs/users/nfs_d/dz11/hap_bedgraph.py`, `add_pretext_view_tracks.py:24`) —
also the author's own, also unreadable from here. Its use is `python3 hap_bedgraph.py <original.fa> |
PretextGraph -i <map> -n gap`, so it emits a gap bedgraph (N-run intervals) on stdout. **Vendor**, or
**reimplement in ~20 lines** — the latter is probably less work than locating the original. The step
is currently commented out of the CLI (`click_cli.py:155-159`) and deliberately excluded from
dry-run, so it is not on the critical path.

---

## post-processing

**Per the charter: no design is proposed here.** What follows is only what grit can observe.

### What grit executes

`run_post_processing` (`post_processing.py:50-68`) pipes a four-line script to `bash` via
`subprocess.run(["bash"], input=script, check=True)` — one of the two documented bypasses of
`_run()` (`ARCH-16`):

```
source /software/grit/projects/contamination_screen/conf/contamination_screen.conf
shopt -s expand_aliases
cd {ctx.assembly_curated_dir}
post_process_rc {ctx.ticket_id}
```

`shopt -s expand_aliases` is required because aliases are not expanded in non-interactive shells —
so `post_process_rc` is definitely an **alias**, defined in that conf file. There is no binary, no
path, no module key, and therefore no substitution point of any kind.

### The inputs it is handed

Exactly two, and both are precise:

1. **cwd** = `ctx.assembly_curated_dir` =
   `<...>/assembly/curated/<tol_id>.<release_version>/`, derived by string-replacing
   `assembly/draft` → `assembly/curated` on the draft path (`context.py:159-162`). `require_workdir`
   runs first, so the *workdir* must exist — note it does not check that the curated dir exists.
2. **one positional argument** = `ctx.ticket_id` — the Jira ticket ID (`RC-1234`). This is
   significant: the ticket ID is only useful to something that can *look the ticket up*. So
   `post_process_rc` has its own Jira (or submission-DB) access, with its own credentials, entirely
   outside grit. Any replacement inherits that requirement.

### The directory state it expects

Produced by `finalize-qc` (`finalize_qc.py:222-327`) immediately before, in `assembly_curated_dir`:

- per haplotype: `<name>.primary.curated.fa` — copied from `find_canonical_fa`
- per haplotype: `<name>.{all,additional}_haplotigs.curated.fa` — from `find_canonical_haplotigs`,
  or **`touch`ed empty** when absent (`CORR-06`)
- per haplotype: `<name>.primary.chromosome.list.csv` — from `find_canonical_chr_list`
- `merquryk/` — the QV directory; `finalize-qc` runs `qv` if it is missing

`<name>` comes from `_dest_name`, which mirrors the out-of-repo
`GritJiraIssue.get_curated_file_name_for_type()` (`PORT-13`). Curated Hi-C maps go to NFS
(`curated_pretext_maps_nfs`), *not* into this directory.

Two things a replacement must know about that state: a missing canonical FASTA is a warning +
`continue`, so the directory can be **incomplete** and `post_process_rc` still gets invoked; and a
haplotigs file may be a legitimately empty `touch`ed placeholder rather than absent.

### What grit expects afterwards

Nothing on disk. Exit 0 is the entire success criterion.

- On exit 0: `tracker.finish("post_processing", run_dir, "success")` then
  `RegistryManager().mark_done(ctx.ticket_id)` (`registry.py:110-113` → `update_status(…, "done")`).
- `STEP_TO_STATUS["post_processing"] = "done"` (`manifests.py:114`) — this is the only step that
  maps to `done`.
- There is **no `STEP_MANIFESTS` entry for `post_processing`** (verified: the key is absent), so
  `RunTracker.verify_outputs` returns `not_tracked` for it, and `ARCH-01`'s recovery paths silently
  give up on it. No `_OUTPUT_SPECS`, no `collect_outputs`, no `job_id`, no bsub epilogue.
- On `CalledProcessError`: finish `failed`, re-raise. Any other failure mode — the alias not being
  defined, the conf not existing, a partial run — is not distinguished.

So the contract grit relies on is exactly: *"given a populated curated-release directory and a
ticket ID, do whatever submission preparation is required and exit 0; grit will then declare the
ticket done."* grit verifies none of it.

### What can be said about its content, and what cannot

Sayable: the conf lives under `/software/grit/projects/**contamination_screen**/`, and grit's own
docstring calls the step "contamination screen + submission prep" and "the post-processing Snakemake
pipeline". So: a Snakemake contamination screen plus submission preparation, wrapped in an alias.

*Hypothesis, not a finding:* the author's local ASCC benchmarking (§ blast-contaminants —
`ABNORMAL_CHECK.csv`, FCS-GX/sourmash/Tiara metrics, `error_logs_ascc/`) is consistent with this
internal screen being ASCC or its predecessor, in which case the public replacement for the
screening half already exists and is MIT. The *submission-prep* half — whatever it writes to the
ticket or to a submission system — has no public equivalent and no observable contract at all.

Not sayable, and I will not invent it: what files it produces, whether it mutates the curated
directory, whether it uploads anything, whether it transitions the Jira ticket itself (grit also
marks the ticket done, so there may be a double transition), whether it is idempotent, and whether
it can fail *after* doing irreversible work.

---

## The five `/software/grit/projects/vgp_curation_scripts/*` scripts

| Script | Used by | Kind | Finding |
|---|---|---|---|
| `get_lineage_from_species.rb` | blast-contaminants | **swap** | NCBI taxonomy via `ncbi-datasets-cli` or `taxonkit`. Internal Ruby; licence unknown but irrelevant once swapped |
| `get_nearest_comparator.rb` | find-reference | **reimplement** | NCBI Datasets + taxonomy walk-up. See § find-reference |
| `sex_matcher.py` | sex-matcher | **reimplement** | ~30 lines; contract observable. See § sex-matcher |
| `ragtag_paf2delta.py` | fastga | **swap / vendor** | **Confirmed**: `ragtag_paf2delta.py` exists at the root of `malonge/RagTag`, which is **MIT**. Either depend on `bioconda::ragtag` or vendor the file with its notice. No GPL obligation |
| `dgenies_index.py` | fastga | **reimplement** | **The vendored-GPL suspicion is unconfirmed.** No file of that name exists in `genotoul-bioinfo/dgenies`; upstream's equivalent is `src/dgenies/bin/index.py`. So this is either a renamed copy of GPL-3.0 code or Sanger's own script writing a D-GENIES-format index. Reimplementing the index (a short text file: name, then `seq\tlength` lines) sidesteps the question entirely and is the recommendation |

Also in the same shell script (`grit/scripts/FastGA_dot_dgenies_stats.sh`), reached bare on `$PATH`:
`DotPrep.py` — **confirmed** present at the root of `dnanexus/dot`, **MIT**, no versioned release and
not on conda, so **vendor with the MIT notice**.

**The licence of the `vgp_curation_scripts` tree as a whole is still unknown**, and that is an
organisational question (`TODO/50` § Organisational), not an engineering one. But it is now a
*smaller* question: of the five scripts, three are being replaced by public tools or
reimplementations, one is confirmed MIT-upstream, and only `dgenies_index.py` needs its provenance
established — and even that can be routed around.

---

## Data dependencies and their real cost

| Resource | Needed by | Size | How an outsider obtains it | Optional? |
|---|---|---|---|---|
| **FCS-GX GX database** | blast-contaminants (Tier 1/2) | **470 GiB on disk**, and FCS-GX wants the DB in **512 GiB of shared memory**; NCBI's own guidance is 32–64 CPU / 512 GiB RAM, and warns that insufficient memory degrades performance "potentially 10,000×" | `sync_files.py` from `ncbi/fcs` over FTP, or the AWS Open Data bucket `s3://ncbi-fcs-gx` (`--no-sign-request`, us-east-1). NIH Genomic Data Sharing Policy; no account needed | **No, if you want FCS-GX-grade screening.** Yes, in that the whole step can be skipped |
| **BLAST `core_nt`** | blast-contaminants (Tier 3) | **≈ 220 GB** (84 volumes, mostly ~2.6 GB each) | `update_blastdb.pl core_nt` from `ftp.ncbi.nlm.nih.gov/blast/db/` | Alternative to FCS-GX, not additional |
| **BLAST `nt`** | blast-contaminants (Tier 3, if the internal DB turns out to be `nt`) | **≈ 625 GB** (251 volumes) | same FTP | Prefer `core_nt` |
| Whatever DB `decon_fasta` actually uses | blast-contaminants (today) | **unknown** | **unknown** | Unknowable from the repo |
| **BUSCO lineage datasets** | sex-matcher, busco-curated, busco-synteny | low GB per lineage (`endopterygota`, `lepidoptera`, `diptera`, `nematoda`, plus whichever busco-curated uses) | `busco-data.ezlab.org/v5/data/lineages/`, auto-downloaded by BUSCO, or AWS Open Data `busco-data` | Required for those three steps only. **Pin the version** — today's `latest` symlink makes runs irreproducible |
| **Sex-chromosome BUSCO ID lists** | sex-matcher | **a few KB** — and the hardest artifact in this document | Permission from `da16`, or regenerate from published chromosome-level assemblies (§ sex-matcher) | Step is inert without them |
| **NCBI reference genomes** | find-reference → fastga, busco-synteny | ~0.1–3 GB per genome, transient | `datasets download genome` | Yes — `--local` already bypasses the download entirely |
| **ASCC's remaining databases** (Kraken2 from nt, Diamond nr + UniProt, VecScreen adaptors, NCBI `rankedlineage.dmp`, PacBio barcodes) | blast-contaminants Tier 1 | Diamond nr and a Kraken2-from-nt database are each in the **hundreds of GB**; `rankedlineage.dmp`/taxdump ~0.5 GB; adaptors and barcodes trivial | Each is public, but assembling the full set is an infrastructure project. ASCC lets each screen be switched `off`, so a reduced-database configuration is genuinely possible | **Individually yes** — ASCC's per-tool switches are the mechanism that makes a small-hardware profile expressible |
| **NCBI taxdump** | replacement for `get_lineage_from_species.rb`, `get_nearest_comparator.rb` | ~0.5 GB, or zero if using the Datasets API online | `taxonkit`'s documented taxdump download, or online | Effectively free |
| **TreeVAL telomere BED** | add-telo-track | small | produced upstream by `sanger-tol/treeval` (public); the step already warns and returns if absent | Yes, already optional |

**The product constraint, stated plainly.** `blast-contaminants` cannot be made cheap. FCS-GX is
470 GiB + 512 GiB RAM; `core_nt` is 220 GB; ASCC's full database set is larger than either. A README
claiming "all 21 steps work outside Sanger" is true only if it also says that this one step assumes
either institutional storage and a large-memory node, or a hosted service. The one genuinely
lightweight direction visible anywhere is the author's own sourmash line of work (an order-level
signature database, `sourmash_db_assemblies_with_taxa.csv`, ~97 MB of metadata in his local
workspace) — sourmash sketches are orders of magnitude smaller than a nucleotide database. That is
**live research, not a settled recommendation**, and its measured sensitivity against HiC ground
truth is precisely what `sourmash_hypotheses.md` is still trying to establish. Worth flagging to the
author as the only plausible route to a laptop-scale contamination screen; not something to design
against yet.

---

## Usable by an outsider vs needs institutional infrastructure

"Outsider" = one person, one workstation or a small cluster, no Sanger accounts, willing to install
conda packages and download a few GB. Scheduler portability (`ExecutionBackend`) is assumed solved
by the sibling Phase 2 work; this column is about *capability*, not job submission.

| Step | Verdict | Binding constraint |
|---|---|---|
| `setup` | **outsider** | Only the ToL directory convention (`PORT-09`: `_derive_workdir` requires `assembly/draft` in the path) |
| `pretext-to-asm` (+ `-recurate`, `-recurate-hap2`, `-micro`) | **outsider** | `agp-tpf-utils`, MIT, git install. No data |
| `haplotig-files` | **outsider** | Pure file operations |
| `super-to-scaffold` | **outsider** | Pure file operations |
| `add-bedgraph-track` / `add-telo-track` | **outsider** | `bioconda::pretextgraph`; telo BED already optional |
| `add-gap-track` | **outsider** once `hap_bedgraph.py` is vendored/reimplemented | Currently commented out of the CLI anyway |
| `hic-remapping` | **outsider on a cluster** | `sanger-tol/curationpretext` (MIT) + a non-`sanger` Nextflow profile. Needs real compute (HiC alignment), no reference database |
| `fastga` / `fastga-synteny` / `fastga-stats` | **outsider** | `bioconda::fastga` + vendored `ragtag_paf2delta.py`/`DotPrep.py` + a reimplemented index. Needs a reference FASTA, which `--local` can supply |
| `rename-and-orient` | **outsider** | Already a public package; only `PKG-01` (unpinned personal git URL) to fix |
| `qv` | **outsider** | `bioconda::fastk` + `merquryfk`, both BSD-3-Clause. Reimplement the Sanger wrapper |
| `validate-files` | **outsider** (once registered on the CLI at all — `ARCH-07b`) | — |
| `finalize-qc` | **outsider**, with a caveat | Release filenames come from the out-of-repo `GritJiraIssue` (`PORT-13`); needs the `MetadataSource` port |
| `busco-curated` / `busco-synteny` | **outsider with a few GB** | `bioconda::busco` + a pinned lineage download |
| `find-reference` | **outsider** after the two reimplementations | Only transient per-genome downloads. `--local` works today |
| `sex-matcher` | **outsider only if the ID lists are recovered or regenerated** | Not a hardware constraint — a **data-permission / curation** constraint. Everything else about the step is cheap |
| `microchromosome-second-shot` | **needs a cluster**, and needs the embedded `bsub -K` lifted out first | HiC remapping inside the script; unverified dependency closure |
| `microchromosome-combine` | **outsider** | Pure file merge, once vendored |
| `blast-contaminants` | **institutional infrastructure, unavoidably** | 220–470+ GB database, and 512 GiB RAM for the best option |
| `post-processing` | **Sanger-only for now** | Unknown contract; also reaches Jira/submission systems with its own credentials |

Counting: **12 steps clearly outsider-runnable** on code fixes alone, **3 more** with a
single-GB-scale public download, **1** (`sex-matcher`) gated on data permission rather than
hardware, **2** needing a real cluster, **1** needing institutional storage, **1** unknown.

That is a strong story — provided it is told with the last three named, not averaged away.

---

## post_process_rc: questions for someone with Sanger access

In priority order. Q1–Q3 are the minimum to write a contract at all; Q4–Q9 are needed to write a
replacement; Q10–Q12 are needed to know whether a replacement is even the right shape.

1. **`grep -n "post_process_rc" /software/grit/projects/contamination_screen/conf/contamination_screen.conf`**
   — what does the alias expand to? A Snakemake invocation, a wrapper script, a chain? Paste it
   verbatim. *(Everything else depends on this answer.)*
2. What else does sourcing that conf define or export — other aliases, `PATH`/`PYTHONPATH` changes,
   credentials, database paths, cluster settings? Does grit's step depend on anything from it beyond
   the one alias?
3. Does the conf contain credentials, hostnames, or internal-topology detail? (Bears directly on
   whether it can be quoted in a public design doc.)
4. Given cwd = `assembly/curated/<tol_id>.<release>/` and one argument `RC-1234`: what does it
   **read** from that directory? Which of the six-ish filenames `finalize-qc` writes are load-bearing,
   and what happens when a haplotigs file is a `touch`ed empty placeholder?
5. What does it **write**, and where — into that directory, elsewhere on NFS, into a database, to an
   external submission endpoint (ENA/GenBank)?
6. What does it do with the **ticket ID**? Read the ticket, write a comment, attach files, transition
   its status? grit separately calls `mark_done` in its own registry — is there a double transition,
   and which system is authoritative?
7. Is the contamination screen it runs the same thing as (or the ancestor of) `sanger-tol/ascc`? If
   so, which version, and with which databases?
8. Is it **idempotent**? What happens on a second run? Can it fail partway after doing something
   irreversible (an upload, a ticket transition)?
9. What are its own runtime requirements — databases, memory, wall time, and does it submit its own
   jobs (i.e. does grit's `subprocess.run(["bash"], …)` return before the real work is finished, the
   way `microchr_second_shot_curation.py` does not)?
10. Which parts are **submission-specific to Sanger/ToL** (ENA broker accounts, internal submission
    DB, ToL naming authority) and therefore inherently non-portable, versus which parts are generic
    genome QC an external user would want?
11. Who owns it, and would that owner release it — or release a documented interface for it?
12. If it cannot be released: is grit's `done` transition allowed to be a **no-op with a warning**
    off-Sanger, or does something later depend on `post_process_rc`'s side effects? (This decides
    whether the step becomes a documented extension point or a hard blocker.)

---

## Unknowns and how to settle them

| # | Unknown | How to settle | Who |
|---|---|---|---|
| 1 | What `post_process_rc` is and does | § post_process_rc, Q1–Q12 | anyone with `/software` access; owner of `contamination_screen` |
| 2 | The identity of `decon_fasta`'s BLAST database | Read `~mh6/git_checkouts/reblast` — its config or the `-db` argument in its BLAST call | `mh6` |
| 3 | Provenance and licence of the four `~da16` BUSCO ID lists — internal work product, or transcribed from a publication? | Ask `da16`; if published, cite the paper and the lists become free | `da16` |
| 4 | What `dip_LG6` denotes, and why linkage group 6 is Diptera's sex-linkage proxy | Ask `da16`; a header or README in the file itself may say | `da16` |
| 5 | Licence/ownership of the `vgp_curation_scripts` tree (`/software` and the gitlab repo) | `ls -la` for `LICENSE`/`COPYING`, check file headers, check the gitlab project's licence field | Sanger; `dz11` for the gitlab copy |
| 6 | Origin and licence of `dgenies_index.py` — **not** a file that exists in D-GENIES upstream | Read its header; `diff` against `src/dgenies/bin/index.py`. Recommendation is to reimplement regardless | `dz11` / script author |
| 7 | Everything about `microchr_second_shot_curation.py`'s internals — the 8-point checklist in § microchromosome pair | `head`/`grep bsub` on the farm. `/nfs` is not mounted on the dev machine | `dz11` (his own code) |
| 8 | `reheader`'s exact header-mapping rule | Run it on one NCBI FASTA and diff headers; or read the `grit` module's `bin/` | anyone on the farm |
| 9 | `sex_matcher.py`'s real output filename and location (three assumed variants in grit — `CORR-10`/`CORR-13`) | `ls` a completed sex-matcher run dir | anyone on the farm |
| 10 | Whether the real microchromosome output filenames match grit's six inferred globs | `ls` a completed second-shot run dir | anyone on the farm |
| 11 | The BUSCO version inside `~mh6/singularity/busco.sif` | `singularity exec busco.sif busco --version` | anyone on the farm |
| 12 | Whether the `grit` lmod module contains anything else grit depends on implicitly | `module show grit`; `ls $GRIT_ROOT/bin` | anyone on the farm |
| 13 | `sourmash` on conda-forge (bioconda confirmed); `ncbi-datasets-cli` on bioconda (conda-forge confirmed) | Channel query | trivial |
| 14 | Exact latest versions of `pretextgraph` / `pretextsnapshot` / `ascc` | Direct fetch (mine came via search summaries) | trivial |
| 15 | Whether `agp-tpf-utils` will be published to PyPI/bioconda — today it is git-install only, which is awkward for a packaged grit | Ask `sanger-tol` / open an issue | `sanger-tol` |

**Explicitly not verified, and not assumed:** the contents of any file under `/nfs`, `/software`,
`/lustre` or another user's home directory. None of those paths are reachable from the development
machine (`ls /nfs` and `ls /software` both fail). Every statement in this document about an internal
script is derived from grit's own invocation of it, its docstrings, or its declared output globs, and
is marked as such.

---

## Sources

Contamination screening — tooling and databases:
- NCBI FCS-GX source and licence/requirements: https://github.com/ncbi/fcs-gx
- NCBI FCS suite (caller scripts, licence text): https://github.com/ncbi/fcs
- FCS-GX quickstart (470 GiB DB, 512 GiB shared memory, `--tax-id`, `*.taxonomy.rpt` /
  `*.fcs_gx_report.txt`, EXCLUDE/FIX/TRIM): https://github.com/ncbi/fcs/wiki/FCS-GX-quickstart
- GX database on AWS Open Data (`s3://ncbi-fcs-gx`, NIH Genomic Data Sharing Policy):
  https://registry.opendata.aws/ncbi-fcs-gx/
- FCS-GX paper (709 Gbp of source sequence, 47,754 taxa, sized for a 512 GiB server):
  https://genomebiology.biomedcentral.com/articles/10.1186/s13059-024-03198-7
- bioconda `ncbi-fcs-gx` 0.5.5: https://bioconda.github.io/recipes/ncbi-fcs-gx/README.html and
  https://anaconda.org/bioconda/ncbi-fcs-gx
- BLAST database FTP listing (core_nt 84 volumes ≈ 220 GB; nt 251 volumes ≈ 625 GB):
  https://ftp.ncbi.nlm.nih.gov/blast/db/
- `core_nt` announcement ("less than half the size of nt"):
  https://ncbiinsights.ncbi.nlm.nih.gov/2024/07/18/new-blast-core-nucleotide-database/

Public ToL equivalents:
- `sanger-tol/ascc` (MIT; FCS-GX + Tiara + sourmash + Kraken + BLAST + Diamond + VecScreen + BUSCO):
  https://github.com/sanger-tol/ascc
- ASCC outputs (`autofilter/ABNORMAL_CHECK.csv`, `autofiltered.fasta`,
  `assembly_filtering_removed_sequences.txt`, `fcs-gx_alarm_indicator_file.txt`,
  `*_contamination_check_merged_table.csv`): https://github.com/sanger-tol/ascc/blob/main/docs/output.md
- ASCC required databases and per-tool `off` switches:
  https://github.com/sanger-tol/ascc/blob/main/docs/usage.md
- `sanger-tol/agp-tpf-utils` (MIT; ships the `pretext-to-asm` entry point):
  https://github.com/sanger-tol/agp-tpf-utils
- `sanger-tol/curation-resources` (MIT; `pretext-to-asm`, `telo_finder.py`, `busco_synteny.sh`,
  `busco_synteny_format_and_plot.py`, `rename_and_orient.py`; **no** BUSCO ID lists, **no**
  `sex_matcher`, **no** `get_nearest_comparator`): https://github.com/sanger-tol/curation-resources
- `sanger-tol/rapid-curation` (points at agp-tpf-utils for pretext-to-asm):
  https://github.com/sanger-tol/rapid-curation
- `sanger-tol/curationpretext` (MIT, v1.6.1): https://github.com/sanger-tol/curationpretext
- `sanger-tol` repository index (no public sex-determination tool found):
  https://github.com/orgs/sanger-tol/repositories

BUSCO and sex chromosomes:
- BUSCO user guide, lineage-dataset file inventory (`hmms`, `prfl`, `scores_cutoff`,
  `lengths_cutoff`, `info`, `ancestral`, `ancestral_variants`, `refseq_db.faa.gz`, `dataset.cfg`,
  `links_to_ODB10.txt`) — **no chromosome assignment**: https://busco.ezlab.org/busco_userguide.html
- BUSCO lineage downloads: https://busco-data.ezlab.org/v5/data/lineages/
- BUSCO datasets on AWS Open Data: https://registry.opendata.aws/busco-data/
- BUSCO licence (MIT): https://gitlab.com/ezlab/busco/-/blob/master/LICENSE
- `findZX` — the nearest public sex-chromosome pipeline, but coverage-based and requires male+female
  reads, i.e. a different contract from grit's BUSCO-ID approach:
  https://link.springer.com/article/10.1186/s12864-022-08432-9

Replacement tools, licences and channels (verified against LICENSE files / recipe pages):
- `ncbi/datasets` CLI, US-Government-Work notice; `conda-forge::ncbi-datasets-cli`:
  https://github.com/ncbi/datasets/blob/master/LICENSE.md and
  https://www.ncbi.nlm.nih.gov/datasets/docs/v2/command-line-tools/download-and-install/
- `taxonkit`, MIT, `bioconda::taxonkit`: https://github.com/shenwei356/taxonkit/blob/master/LICENSE
- RagTag, MIT, `bioconda::ragtag`; `ragtag_paf2delta.py` present at repo root:
  https://github.com/malonge/RagTag/blob/master/LICENSE
- D-GENIES, **GPL-3.0**; upstream file is `src/dgenies/bin/index.py`, no `dgenies_index.py`:
  https://github.com/genotoul-bioinfo/dgenies/blob/master/LICENSE.txt
- `dnanexus/dot`, MIT; `DotPrep.py` present at repo root:
  https://github.com/dnanexus/dot/blob/master/LICENSE.md
- FastK, BSD-3-Clause, `bioconda::fastk`: https://github.com/thegenemyers/FASTK/blob/master/LICENSE
- MerquryFK, BSD-3-Clause, `bioconda::merquryfk`:
  https://github.com/thegenemyers/MERQURY.FK/blob/master/LICENSE
- FastGA, custom modified-BSD (non-standard endorsement clause), `bioconda::fastga`:
  https://github.com/thegenemyers/FASTGA/blob/main/LICENSE
- sourmash, BSD-3-Clause, `bioconda::sourmash`:
  https://github.com/sourmash-bio/sourmash/blob/latest/LICENSE
- Tiara, MIT, **`conda-forge::tiara`** (not on bioconda):
  https://github.com/ibe-uw/tiara/blob/main/LICENSE
- BlobToolKit, MIT, `bioconda::blobtoolkit`:
  https://github.com/blobtoolkit/blobtoolkit/blob/main/LICENSE
- PretextGraph / PretextMap / PretextSnapshot / PretextView, MIT, all but PretextView on bioconda:
  https://github.com/sanger-tol/PretextGraph, https://github.com/sanger-tol/PretextMap,
  https://github.com/sanger-tol/PretextSnapshot, https://github.com/sanger-tol/PretextView
- seqkit, MIT, `bioconda::seqkit`: https://github.com/shenwei356/seqkit

Local evidence in the author's own workspace (not published, cited as evidence of direction):
`/Users/dz11/curations/contamination_check/` — `*_ABNORMAL_CHECK.csv` with ASCC's
`fcs_gx_action`/`sourmash_action`/`tiara_action`/`combined_action` columns,
`contamination_check_metrics.csv` (FCS-GX / sourmash / Tiara vs HiC ground truth),
`ground_truth_strategy.md`, `sourmash_hypotheses.md`, `error_logs_ascc/`.
