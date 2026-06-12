"""Output file manifests for each step — used by RunTracker.verify_outputs()."""

from __future__ import annotations

# Glob patterns to verify a step's outputs.
# {tol_id} is substituted at verification time.
# Steps without a manifest entry are not verified on disk.
# Steps with an empty list are considered verified when their exit code is 0.
#
# Two special keys control where to look:
#   "run_dir" (default): check inside the timestamped run_dir
#   "workdir":           check inside ctx.workdir (for non-timestamped steps)
STEP_MANIFESTS: dict[str, dict] = {
    # Non-timestamped: output goes directly to workdir
    "setup_curation": {
        "dir": "workdir",
        "files": ["original.fa"],
    },
    # bsub job, outputs go to workdir (cd workdir before running)
    "sex_matcher": {
        "dir": "workdir",
        "files": ["Best_match*.txt"],
    },
    # script cd-s to workdir/reference, output stays there
    "find_reference": {
        "dir": "workdir",
        "files": ["reference/*.fa"],
    },
    "pretext_to_asm": {
        "dir": "run_dir",
        "files": ["{tol_id}*.curated.fa", "{tol_id}*.agp"],
    },
    "haplotig_files": {
        "dir": "run_dir",
        "files": ["{tol_id}*haplotigs*.fa"],
    },
    "hic_remapping": {
        "dir": "run_dir",
        "files": ["pretext_maps_processed/{tol_id}*hr.pretext"],
    },
    "qv": {
        "dir": "run_dir",
        "files": [],  # output goes to assembly_curated_dir; just track exit code
    },
    "validate_files": {
        "dir": "run_dir",
        "files": [],  # no output files; success = exit 0
    },
    "finalize_qc": {
        "dir": "run_dir",
        "files": [],
    },
}

# Maps last-successful step to registry status label.
STEP_TO_STATUS: dict[str, str] = {
    "setup_curation": "in_curation",
    "sex_matcher": "in_curation",
    "add_gap_track": "in_curation",
    "add_telo_track": "in_curation",
    "microchromosome": "in_curation",
    "agp_copied": "post_curation",
    "find_reference": "post_curation",
    "pretext_to_asm": "post_curation",
    "haplotig_files": "post_curation",
    "hic_remapping": "remapping",
    "qv": "ready_for_qc",
    "validate_files": "ready_for_qc",
    "finalize_qc": "post_processing",
}
