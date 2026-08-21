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
# The --dry-run pass near the end exercises setup/pretext-to-asm/
# blast-contaminants/rename-and-orient/status/untrack end to end against the
# isolated ~/.grit/dry_run/ sandbox — no farm/NFS output required for those
# commands themselves. `grit status`'s canonical-file/★ resolution still does
# a live Jira lookup for whatever ticket you pass as the second argument
# (dry_run_ticket) independent of --yaml/--dry-run, so pass a real ticket ID
# to exercise that path for real; see the comment at that section for a
# known gap that currently makes it a no-op regardless.
#
# Exit code: 0 if all commands print without error, non-zero otherwise.

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

# --- Dry-run mode ---
# Chains a real sequence through the CLI against the isolated
# ~/.grit/dry_run/ sandbox (see CLAUDE.md's --dry-run bullet). No real farm
# output is required for setup/pretext-to-asm/blast-contaminants/
# rename-and-orient below — each writes placeholder outputs directly.
GRIT_DRY="grit --config $CONFIG --yaml $HAP_YAML"

$GRIT_DRY setup -t "$DRY_RUN_TICKET" --dry-run              && ok "setup --dry-run"
$GRIT_DRY pretext-to-asm -t "$DRY_RUN_TICKET" --dry-run     && ok "pretext-to-asm --dry-run"
$GRIT_DRY blast-contaminants -t "$DRY_RUN_TICKET" --dry-run && ok "blast-contaminants --dry-run"
$GRIT_DRY rename-and-orient -t "$DRY_RUN_TICKET" --dry-run  && ok "rename-and-orient --dry-run"

# status/untrack are plain @cli.command, not GritCommand-based — --dry-run
# only takes effect for them as a GROUP-level flag, before the subcommand
# name (`grit --dry-run status ...`), never after it.
#
# KNOWN GAP (not fixed here — out of this task's scope): show_global_status
# and show_ticket_history (grit/core/status.py) build their RunTracker via
# `RunTracker(workdir)`, which defaults to the real ~/.grit/grit_registry.json
# instead of threading through the dry-run registry that grit status already
# selected. So the step-history table below currently comes back empty for a
# dry-run ticket — the ★ marker this section is meant to demonstrate moving
# from rename_and_orient to blast_contaminants cannot be observed via `grit
# status` today, regardless of Jira access. Printing the output here anyway
# so a human can confirm/refute that once status.py's registry threading is
# fixed in a follow-up task.
echo ""
echo "--- grit --dry-run status (before untrack) ---"
$GRIT_DRY --dry-run status -t "$DRY_RUN_TICKET"

$GRIT_DRY --dry-run untrack -t "$DRY_RUN_TICKET" --step rename_and_orient && ok "untrack rename_and_orient --dry-run"

echo ""
echo "--- grit --dry-run status (after untrack) ---"
$GRIT_DRY --dry-run status -t "$DRY_RUN_TICKET"

rm -rf ~/.grit/dry_run
ok "dry-run sandbox cleaned up"

echo ""
echo "=== All passed ==="
