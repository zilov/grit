#!/bin/bash
# Run sanger-tol/curationpretext in the current directory, in the foreground.
#
# Same as the module's curationpretext.sh minus its own `bsub`, so the job grit
# submits is the nextflow head job and its -Ep epilogue fires on completion.
# main.nf and the usage-tracking call are read from the loaded wrapper, so a
# curationpretext version bump in the grit module needs no change here.
#
# Usage: curationpretext.sh <pipeline args...>   (module providing it must be loaded)
set -euo pipefail

wrapper=$(command -v curationpretext.sh) || {
    echo "grit: curationpretext.sh not on PATH — is the grit module loaded?" >&2
    exit 1
}
main_nf=$(grep -oE '/[^ ]+/main[.]nf' "$wrapper" | head -1 || true)
if [[ ! -f "$main_nf" ]]; then
    echo "grit: cannot locate curationpretext main.nf in $wrapper" >&2
    exit 1
fi

export NXF_DISABLE_CHECK_LATEST=1
export NXF_OPTS='-Xms128m -Xmx1024m'

args=(
    -profile sanger,singularity
    -ansi-log false
    -with-weblog http://logstash.tol.sanger.ac.uk/http
    "$@"
)

# Team usage metric, best effort: never fails the run.
tracking=$(grep -oE '/[^ ]+/tracking_usage[.]sh +/[^ ]+' "$wrapper" | head -1 || true)
if [[ -n "$tracking" ]]; then
    $tracking 'nextflow run' "$main_nf" "${args[@]}" >/dev/null 2>&1 || true
fi

echo "grit: nextflow run $main_nf ${args[*]}"
exec nextflow run "$main_nf" "${args[@]}"
