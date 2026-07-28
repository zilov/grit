#!/bin/bash

# Scaffold IDs need to be in final tol format.
# Query and ref short IDs need to be two letter codes eg. "Ac".
# Query and ref fasta files need to be in working dir.
# Must be run in curation_v2 for plotting to complete (python dependencies - matplotlib, seaborn)

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

source /nfs/users/nfs_m/mh6/sing.bash

IMAGE=/nfs/treeoflife-01/teams/grit/users/mh6/singularity/busco.sif

myReference=''
myQuery=''
myDirPath=''
buscoLineage=''
ref_short_id='Rf'
query_short_id='Qu'
filesKeep=''

usage() {
cat << EOF
Usage: $0 -r reference_species.fasta -q query_species.fasta -l busco_lineage -p wd_path [OPTIONAL -u Query_ID, -f Ref_ID, -k]

Note that both reference and query fasta headers must have chromsomes names as 'SUPER_n'

REQUIRED:
  -r [file] Reference species Fasta file
  -q [file] Query species fasta file
  -l [text] Name of BUSCO lineage to test against
  -p [dir] Path to directory containing files (and where output is written)
OPTIONAL:
  -f [text] reF short ID - two letter abbreviation for reference species (default = $ref_short_id)
  -u [text] qUery short ID - two letter abbreviation for query species (default = $query_short_id)
  -k  add this flag to keep BUSCO output files - all BUSCO files other than the flattened full_table/short_summary will be removed by default
EOF
        exit 1
}

while getopts "r:q:l:f:u:p:kh" opt
   do
     case $opt in
        r ) myReference=$OPTARG
        if [ ! -f $myReference ] ; then echo "File $myReference does not exist"; usage; fi
        ;;
        q ) myQuery=$OPTARG
        if [ ! -f $myQuery ] ; then echo "File $myQuery does not exist"; usage; fi
        ;;
        l ) buscoLineage=$OPTARG
        if [ ! -l ]; then echo "No BUSCO lineage provided"; usage; fi
        ;;
        f ) ref_short_id=$OPTARG;;
        p ) myDirPath=$OPTARG;;
        u ) query_short_id=$OPTARG;;
        k ) filesKeep='-k';;
        h | *) usage;;
     esac
done

if [ -z "$myDirPath" ]; then echo "No output directory provided (-p is required)"; usage; fi

# ---------------------------------------------------------------------------
# Run BUSCO for one fasta, reusing a prior run's flattened output if present.
#
# Flattens both the full table and the short summary out of the (heavy)
# busco5_mini{id}/ working directory immediately after the BUSCO call, then
# deletes that directory (unless -k/filesKeep) — this both keeps the flat
# full-table file as the "already done" marker for next time, and avoids
# leaving the heavy busco5_mini{id}/ tree (busco_sequences/, logs/, hmmer
# intermediates, etc.) sitting on disk, which matters on farm due to the
# per-user file count limit.
# ---------------------------------------------------------------------------
run_busco_if_needed() {
    local fasta=$1 id=$2
    local flat_table="${myDirPath}/${id}_BUSCO_full_table.tsv"
    local flat_summary="${myDirPath}/${id}_BUSCO_short_summary.txt"
    if [ -f "$flat_table" ]; then
        echo "BUSCO already run for ${id} (${buscoLineage}), reusing ${flat_table}"
        return
    fi
    local outdir="busco5_mini${id}"
    singularity exec -B /lustre $IMAGE busco -i "$fasta" -o "$outdir" -m genome \
        -l /lustre/scratch122/tol/resources/busco/latest/lineages/$buscoLineage -c 32
    mv "${outdir}/run_${buscoLineage}/full_table.tsv" "$flat_table"
    # TODO: verify this short-summary filename against a real BUSCO v5 run —
    # BUSCO v5 is documented to write
    # short_summary.specific.<lineage>.<outdir>.txt directly inside <outdir>,
    # but this hasn't been confirmed against actual cluster output for this
    # image/version. If the mv below fails silently in practice, check the
    # actual filename BUSCO produced under "${outdir}/" and fix this line.
    mv "${outdir}/short_summary.specific.${buscoLineage}.${outdir}.txt" "$flat_summary"
    if [ -z "$filesKeep" ]; then
        rm -rf "$outdir"
    fi
}

run_busco_if_needed "$myReference" "$ref_short_id"
run_busco_if_needed "$myQuery" "$query_short_id"

# Run circos plotting
python "$SCRIPT_DIR/busco_synteny_format_and_plot.py" \
    -r "$myReference" -q "$myQuery" -ri "$ref_short_id" -qi "$query_short_id" -p "$myDirPath" $filesKeep
