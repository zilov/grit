#!/bin/bash

## Wrapper script to run FastGA alignment and generate input files for visualisation in Dot (sandbox )https://dot.sandbox.bio/).
## Uses RagTag python script to convert from paf to delta (https://github.com/malonge/RagTag/wiki/file-utilities#paf2delta)
## Need to be in curation_v2 env.

## Usage: sh /software/grit/projects/vgp_curation_scripts/FastGA_dot.sh <ref.fa> <query.fa> <out_prefix> <outdir> <top_targets_script>

if [ "$#" -ne 5 ]; then
    echo "Usage: $0 <ref.fa> <query.fa> <out_prefix> <outdir> <top_targets_script>"
    exit 1
fi

ref=$(realpath "$1")
query=$(realpath "$2")
prefix=$3
outdir=$4
top_targets_script=$5

# Create output directory if it doesn't exist
mkdir -p ${outdir}

# Get filenames without paths for indexing
ref_name=$(basename ${ref} .fa)
query_name=$(basename ${query} .fa)

# Index genomes with dgenies_index.py
echo "Indexing reference genome..."
/software/grit/projects/vgp_curation_scripts/dgenies_index.py -i ${ref} -n ${ref_name} -o ${outdir}/${ref_name}.idx
echo "Indexing query genome..."
/software/grit/projects/vgp_curation_scripts/dgenies_index.py -i ${query} -n ${query_name} -o ${outdir}/${query_name}.idx

# Change to output directory
cd ${outdir}

# Set prefix for output files
module load fastga/1.1-c1

# Align with FastGA
echo "Running FastGA alignment..."
FastGA ${query} ${ref} -vk -1:${prefix}_FastGA

# Chain
echo "Chaining alignments..."
ALNchain ${prefix}_FastGA.1aln -o${prefix}_chained

## Convert raw alignment

# Covert to paf with fastGA tool.
echo "Converting raw alignment to PAF..."
ALNtoPAF -m ${prefix}_FastGA.1aln > ${prefix}_FastGA.paf

# Top-targets summary, generated right away since the raw PAF is on disk in this job
echo "Generating top-targets summary..."
python3 ${top_targets_script} ${prefix}_FastGA.paf --top1-out ${prefix}.top1_targets.tsv --top_longest > ${prefix}.top_targets_summary.txt

# Add NM tag to cigar string
cut -f14 ${prefix}_FastGA.paf  | sed 's/df/NM/g' > tmp; cut -f1-14 ${prefix}_FastGA.paf  | paste - tmp > tmp2; cut -f15 ${prefix}_FastGA.paf  | paste tmp2 - > ${prefix}_FastGA_add_NM.paf

# Convert to delta with script from RagTag
echo "Converting to delta format..."
python /software/grit/projects/vgp_curation_scripts/ragtag_paf2delta.py ${prefix}_FastGA_add_NM.paf > ${prefix}_FastGA_add_NM.delta

# Run dot prep.
echo "Running DotPrep for raw alignment..."
DotPrep.py --overview 10000000 --delta ${prefix}_FastGA_add_NM.delta --out ${prefix}_FastGA_add_NM  

## Convert chained alignment

# Covert to paf with fastGA tool.
echo "Converting chained alignment to PAF..."
ALNtoPAF -m ${prefix}_chained.1aln > ${prefix}_chained.paf 

# Add NM tag to cigar string
cut -f14 ${prefix}_chained.paf  | sed 's/df/NM/g' > tmp; cut -f1-14 ${prefix}_chained.paf  | paste - tmp > tmp2; cut -f15 ${prefix}_chained.paf  | paste tmp2 - > ${prefix}_chained_add_NM.paf

# Convert to delta with script from RagTag
echo "Converting to delta format..."
python /software/grit/projects/vgp_curation_scripts/ragtag_paf2delta.py ${prefix}_chained_add_NM.paf > ${prefix}_chained_add_NM.delta

# Run dot prep.
echo "Running DotPrep for chained alignment..."
DotPrep.py --overview 10000000 --delta ${prefix}_chained_add_NM.delta --out ${prefix}_chained_add_NM 

# Clean up
echo "Cleaning up temporary files..."
rm tmp
rm tmp2

echo "All steps completed. Results are in ${outdir}"
