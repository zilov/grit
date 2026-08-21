#!/usr/bin/env bash
# Farm smoke test — runs all grit commands with --print-only + --yaml.
# Usage: bash tests/local_smoke_test.sh [config_path] [dry_run_ticket]
#
# Requires real farm paths to exist (this fixture ticket's assembly/draft dir,
# and — for the pipeline steps below that check for a prior step's output even
# in --print-only mode (add-gap-track, add-telo-track, fastga,
# blast-contaminants, hic-remapping, rename-and-orient) — those upstream
# outputs to already be on disk. Run this on the farm after a real setup/fastga
# pass, not on a laptop or in CI.
#
# For a hermetic, dependency-free version of this check covering the commands
# that don't require real prior output (setup, find-reference, pretext-to-asm,
# haplotig-files, qv, validate-files, finalize-qc), see tests/test_smoke.py —
# that one runs as part of `pytest tests/`.
#
# Requires:
#   - grit installed (pip install -e .)
#   - Two YAML fixtures in tests/fixtures/
#
# The --dry-run pass near the end exercises the full --dry-run-supported
# command set end to end against the isolated ~/.grit/dry_run/ sandbox — no
# farm/NFS output required for any of it (see CLAUDE.md's --dry-run bullet).
# It runs entirely on a laptop and is the main thing to run after touching
# find_canonical_fa/find_canonical_chr_list/find_canonical_haplotigs, any
# step's dry-run branch, or the flat mtime pool itself — it's real curator
# pipelines run twice, once straight through and once with steps re-run out of
# order, specifically to catch canonical-FASTA collisions (see
# TODO/done/44_canonical_fa_flat_mtime_priority.md) that unit tests, scoped to
# one function at a time, would not surface.
#
# `grit status`'s canonical-file/★ resolution builds its CurationContext from
# the same --yaml FILE given on the group-level flag (threaded through as
# yaml_override), not a live Jira lookup — so the dry-run ticket IDs below can
# be any string; each just needs to be used consistently across the --dry-run
# commands in its own scenario, not be a real Jira key.
#
# Exit code: 0 if all commands print without error and every assertion below
# passes, non-zero otherwise.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES="$SCRIPT_DIR/fixtures"
CONFIG="${1:-$SCRIPT_DIR/fixtures/test_config.yaml}"
DRY_RUN_TICKET="${2:-uoEpiScra1_hap1_hap2}"
HAP_YAML="$FIXTURES/uoEpiScra1_hap1_hap2.yaml"
PRIMARY_YAML="$FIXTURES/xbLimHian1_primary.yaml"

GRIT="grit --config $CONFIG --print-only"

ok() { echo "  OK  $1"; }
fail() { echo "FAIL  $1"; exit 1; }

echo "=== grit local smoke test ==="
echo "Config:  $CONFIG"
echo "hap YAML:     $HAP_YAML"
echo "primary YAML: $PRIMARY_YAML"
echo ""

# --- Global ---
grit --help > /dev/null && ok "grit --help"

# --- Pre-curation (hap1/hap2) ---
$GRIT --yaml "$HAP_YAML" setup --print-only               && ok "setup (hap, --print-only after subcommand)"
$GRIT --yaml "$HAP_YAML" add-gap-track                    && ok "add-gap-track"
$GRIT --yaml "$HAP_YAML" add-telo-track                   && ok "add-telo-track"
$GRIT --yaml "$HAP_YAML" sex-matcher                      && ok "sex-matcher"
$GRIT --yaml "$HAP_YAML" find-reference                   && ok "find-reference"

# --- Pre-curation (primary) ---
$GRIT --yaml "$PRIMARY_YAML" setup                        && ok "setup (primary)"
$GRIT --yaml "$PRIMARY_YAML" find-reference               && ok "find-reference (primary)"

# --- Post-curation ---
$GRIT --yaml "$HAP_YAML" pretext-to-asm                   && ok "pretext-to-asm"
$GRIT --yaml "$HAP_YAML" haplotig-files                   && ok "haplotig-files"
$GRIT --yaml "$HAP_YAML" hic-remapping                    && ok "hic-remapping"
$GRIT --yaml "$HAP_YAML" qv                               && ok "qv"
$GRIT --yaml "$HAP_YAML" validate-files                   && ok "validate-files"
$GRIT --yaml "$HAP_YAML" finalize-qc                      && ok "finalize-qc"

# --- Optional ---
$GRIT --yaml "$HAP_YAML" fastga                           && ok "fastga"
$GRIT --yaml "$HAP_YAML" blast-contaminants               && ok "blast-contaminants"
$GRIT --yaml "$HAP_YAML" rename-and-orient                && ok "rename-and-orient"
$GRIT --yaml "$HAP_YAML" busco-synteny --lineage stramenopiles_odb10 && ok "busco-synteny"

# =============================================================================
# --- Dry-run mode: canonical-FASTA pipeline scenarios ---
# =============================================================================
# Everything below runs against the isolated ~/.grit/dry_run/ sandbox — no
# farm/NFS access required. Each scenario uses its own ticket ID so they never
# interfere with each other.

GRIT_DRY="grit --config $CONFIG --yaml $HAP_YAML"
GRIT_DRY_PRIMARY="grit --config $CONFIG --yaml $PRIMARY_YAML"

# assert_canonical STATUS_OUTPUT HAP TYPE_SUBSTR STEP_DIR_SUBSTR DESCRIPTION
#   Greps the "Canonical files" table (Hap | Type | File | Found) for a row
#   matching HAP and TYPE_SUBSTR, and asserts its File column contains
#   STEP_DIR_SUBSTR (a run_dir directory name, e.g. "blast_contaminants/" —
#   include the trailing slash so "pretext_to_asm/" doesn't also match
#   "pretext_to_asm_recurate/", and so "rename_and_orient/" doesn't also match
#   "rename_and_orient_hap2/").
assert_canonical() {
    local status_output="$1" hap="$2" type_substr="$3" step_substr="$4" desc="$5"
    echo "$status_output" | grep "$hap" | grep "$type_substr" | grep -q "$step_substr" \
        && ok "$desc" \
        || fail "$desc — expected '$step_substr' in $hap's $type_substr row:
$(echo "$status_output" | grep "$hap" | grep "$type_substr")"
}

# ---------------------------------------------------------------------------
# Scenario 1: a real curation pipeline, straight through
#   pretext-to-asm -> blast-contaminants -> hic-remapping ->
#   pretext-to-asm-recurate -> rename-and-orient -> hic-remapping ->
#   finalize-qc
# Asserts canonical_fa lands on the expected step after every transition,
# for both haplotypes.
# ---------------------------------------------------------------------------
echo ""
echo "--- Scenario 1: real curation pipeline (straight through) ---"
T1="dry_run_pipeline_1"

$GRIT_DRY setup -t "$T1" --dry-run                          && ok "[S1] setup"
$GRIT_DRY pretext-to-asm -t "$T1" --dry-run                 && ok "[S1] pretext-to-asm"
s1=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s1" hap1 "assembly FA" "pretext_to_asm/" "[S1] hap1 canonical = pretext_to_asm after pretext-to-asm"
assert_canonical "$s1" hap2 "assembly FA" "pretext_to_asm/" "[S1] hap2 canonical = pretext_to_asm after pretext-to-asm"

$GRIT_DRY blast-contaminants -t "$T1" --dry-run             && ok "[S1] blast-contaminants"
s1=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s1" hap1 "assembly FA" "blast_contaminants/" "[S1] hap1 canonical = blast_contaminants"
assert_canonical "$s1" hap2 "assembly FA" "blast_contaminants/" "[S1] hap2 canonical = blast_contaminants"

$GRIT_DRY hic-remapping -t "$T1" --dry-run                  && ok "[S1] hic-remapping (hap1)"
$GRIT_DRY hic-remapping -t "$T1" --dry-run --hap2           && ok "[S1] hic-remapping (hap2, exclusive flag)"
s1=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s1" hap1 "assembly FA" "blast_contaminants/" "[S1] hic-remapping doesn't change canonical_fa (hap1)"

$GRIT_DRY pretext-to-asm-recurate -t "$T1" --dry-run        && ok "[S1] pretext-to-asm-recurate (hap1)"
$GRIT_DRY pretext-to-asm-recurate -t "$T1" --dry-run --hap2 && ok "[S1] pretext-to-asm-recurate (hap2, exclusive flag)"
s1=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s1" hap1 "assembly FA" "pretext_to_asm_recurate/" "[S1] hap1 canonical = pretext_to_asm_recurate"
assert_canonical "$s1" hap2 "assembly FA" "pretext_to_asm_recurate_hap2/" "[S1] hap2 canonical = pretext_to_asm_recurate_hap2"

$GRIT_DRY rename-and-orient -t "$T1" --dry-run --hap2       && ok "[S1] rename-and-orient (hap1+hap2, additive flag)"
s1=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s1" hap1 "assembly FA" "rename_and_orient/" "[S1] hap1 canonical = rename_and_orient (chain forward from recurate)"
assert_canonical "$s1" hap2 "assembly FA" "rename_and_orient_hap2/" "[S1] hap2 canonical = rename_and_orient_hap2 (chain forward from recurate)"

$GRIT_DRY hic-remapping -t "$T1" --dry-run                  && ok "[S1] 2nd hic-remapping (hap1)"
$GRIT_DRY hic-remapping -t "$T1" --dry-run --hap2           && ok "[S1] 2nd hic-remapping (hap2)"

finalize_output=$($GRIT_DRY finalize-qc -t "$T1" --dry-run) && ok "[S1] finalize-qc"
echo "$finalize_output"
curated_dir=$(echo "$finalize_output" | grep -A1 "Curated dir" | tail -1 | tr -d ' ')
[ -n "$curated_dir" ] && [ -d "$curated_dir" ] \
    && ok "[S1] finalize-qc wrote into a real, discoverable curated dir" \
    || fail "[S1] finalize-qc's curated dir not found on disk: '$curated_dir'"
case "$curated_dir" in
    */.grit/dry_run/*) ok "[S1] finalize-qc's curated dir is sandboxed under ~/.grit/dry_run/, not a real NFS path" ;;
    *) fail "[S1] finalize-qc's curated dir escaped the dry-run sandbox: $curated_dir" ;;
esac

# ---------------------------------------------------------------------------
# Scenario 2: re-run blast-contaminants, rename-and-orient, and
# pretext-to-asm-recurate again, out of their "natural" order, on top of the
# already-finalized Scenario 1 ticket — the collision-hunting case. Recency
# wins by design (see TODO/done/44_canonical_fa_flat_mtime_priority.md), so
# canonical_fa must bounce to whichever of these ran most recently every time,
# with no crash and no stale/fabricated files left behind.
# ---------------------------------------------------------------------------
echo ""
echo "--- Scenario 2: duplicate re-runs on top of Scenario 1 (collision hunt) ---"

$GRIT_DRY blast-contaminants -t "$T1" --dry-run             && ok "[S2] re-run blast-contaminants (after rename_and_orient was canonical)"
s2=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s2" hap1 "assembly FA" "blast_contaminants/" "[S2] hap1 canonical bounces back to blast_contaminants"
assert_canonical "$s2" hap2 "assembly FA" "blast_contaminants/" "[S2] hap2 canonical bounces back to blast_contaminants"

$GRIT_DRY rename-and-orient -t "$T1" --dry-run --hap2       && ok "[S2] re-run rename-and-orient"
s2=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s2" hap1 "assembly FA" "rename_and_orient/" "[S2] hap1 canonical bounces back to rename_and_orient"
assert_canonical "$s2" hap2 "assembly FA" "rename_and_orient_hap2/" "[S2] hap2 canonical bounces back to rename_and_orient_hap2"

$GRIT_DRY pretext-to-asm-recurate -t "$T1" --dry-run        && ok "[S2] re-run pretext-to-asm-recurate (hap1)"
$GRIT_DRY pretext-to-asm-recurate -t "$T1" --dry-run --hap2 && ok "[S2] re-run pretext-to-asm-recurate (hap2)"
s2=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s2" hap1 "assembly FA" "pretext_to_asm_recurate/" "[S2] hap1 canonical bounces back to pretext_to_asm_recurate"
assert_canonical "$s2" hap2 "assembly FA" "pretext_to_asm_recurate_hap2/" "[S2] hap2 canonical bounces back to pretext_to_asm_recurate_hap2"

# One more full lap: blast-contaminants again should still displace the
# freshest recurate output, with no accumulated state from prior laps leaking
# through (e.g. a stale run_dir being picked up instead of the newest one).
$GRIT_DRY blast-contaminants -t "$T1" --dry-run             && ok "[S2] re-run blast-contaminants a second time"
s2=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s2" hap1 "assembly FA" "blast_contaminants/" "[S2] hap1 canonical bounces to blast_contaminants again"
assert_canonical "$s2" hap2 "assembly FA" "blast_contaminants/" "[S2] hap2 canonical bounces to blast_contaminants again"

# ---------------------------------------------------------------------------
# Scenario 3: single-hap (primary/alternate) regression check.
#   A single-hap ticket must never get a fabricated "alternate"/hap2 output
#   anywhere on disk — not just excluded from the tracker. write_fake_outputs
#   always writes both _OUTPUT_SPECS entries; every dry-run branch that pops
#   the hap2 key from the tracked outputs dict must also delete that file.
# ---------------------------------------------------------------------------
echo ""
echo "--- Scenario 3: single-hap ticket never fabricates a second haplotype ---"
T3="dry_run_pipeline_primary"

$GRIT_DRY_PRIMARY setup -t "$T3" --dry-run                          && ok "[S3] setup (primary)"
$GRIT_DRY_PRIMARY pretext-to-asm -t "$T3" --dry-run                 && ok "[S3] pretext-to-asm (primary)"
$GRIT_DRY_PRIMARY blast-contaminants -t "$T3" --dry-run             && ok "[S3] blast-contaminants (primary)"
$GRIT_DRY_PRIMARY rename-and-orient -t "$T3" --dry-run              && ok "[S3] rename-and-orient (primary)"
$GRIT_DRY_PRIMARY pretext-to-asm-recurate -t "$T3" --dry-run        && ok "[S3] pretext-to-asm-recurate (primary)"
$GRIT_DRY_PRIMARY finalize-qc -t "$T3" --dry-run                    && ok "[S3] finalize-qc (primary)"

s3=$($GRIT_DRY_PRIMARY --dry-run status -t "$T3")
# Only check the "Canonical files" table's Hap column for a fabricated
# "alternate" row — the curation-summary line above it legitimately says
# "Assembly type: primary/alternate" for every primary/alternate ticket.
echo "$s3" | sed -n '/Canonical files/,/Step history/p' | grep -q "│ alternate " \
    && fail "[S3] a single-hap ticket's canonical-files table has a fabricated 'alternate' row" \
    || ok "[S3] canonical-files table shows only 'primary', no fabricated 'alternate' row"

primary_workdir="$HOME/.grit/dry_run/$T3"  # dry-run workdirs are keyed by ticket_id
[ -d "$primary_workdir" ] || fail "[S3] could not locate the primary ticket's sandbox workdir: $primary_workdir"
leftover=$(find "$primary_workdir" \( -iname "*hap2*" -o -iname "*alternate*" \) 2>/dev/null || true)
[ -z "$leftover" ] \
    && ok "[S3] no hap2/alternate files anywhere on disk for the single-hap ticket" \
    || fail "[S3] found leftover hap2/alternate files for a single-hap ticket:
$leftover"

# ---------------------------------------------------------------------------
# Scenario 4: untrack / undo round-trip mid-chain.
#   Untracking the currently-canonical step must fall through to the next-
#   freshest tracked output; --undo must bring it back.
# ---------------------------------------------------------------------------
echo ""
echo "--- Scenario 4: untrack/undo round-trip ---"

# From Scenario 2, hap1's canonical is currently blast_contaminants (its
# second re-run, which ran after rename_and_orient's re-run and after
# pretext_to_asm_recurate's re-run) — so untracking it must fall back to the
# next-freshest tracked output, pretext_to_asm_recurate, NOT all the way back
# to rename_and_orient (which is older than the recurate re-run).
$GRIT_DRY --dry-run untrack -t "$T1" --step blast_contaminants && ok "[S4] untrack blast_contaminants (hap1)"
s4=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s4" hap1 "assembly FA" "pretext_to_asm_recurate/" "[S4] hap1 canonical falls back to pretext_to_asm_recurate after untracking blast_contaminants"

$GRIT_DRY --dry-run untrack -t "$T1" --step blast_contaminants --undo && ok "[S4] undo the untrack"
s4=$($GRIT_DRY --dry-run status -t "$T1")
assert_canonical "$s4" hap1 "assembly FA" "blast_contaminants/" "[S4] hap1 canonical returns to blast_contaminants after --undo"

# The dry-run sandbox is keyed by ticket_id, not tol_id — two --dry-run
# "tickets" that share a YAML fixture (hence the same tol_id, exactly what
# every scenario above does) each still get their own isolated workdir/tracker
# history, so a fresh scenario could use its own ticket ID here. Every
# scenario above reuses $T1 anyway, since Scenarios 1/2/4 are deliberately
# chained on top of each other. The $DRY_RUN_TICKET CLI argument is still
# accepted for backward compatibility but is no longer used by this script.

rm -rf ~/.grit/dry_run
ok "dry-run sandbox cleaned up"

echo ""
echo "=== All passed ==="
