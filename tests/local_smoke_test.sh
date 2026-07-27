#!/usr/bin/env bash
# Farm smoke test — runs all grit commands with --print-only + --yaml.
# Usage: bash tests/local_smoke_test.sh [config_path]
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
# Exit code: 0 if all commands print without error, non-zero otherwise.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURES="$SCRIPT_DIR/fixtures"
CONFIG="${1:-$SCRIPT_DIR/fixtures/test_config.yaml}"
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

echo ""
echo "=== All passed ==="
