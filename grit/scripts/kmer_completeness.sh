#!/bin/bash
# MerquryFK QV + k-mer completeness of a curated release, written into the current dir.
# usage: kmer_completeness.sh <tol_id> <version> <curated_dir> <draft_dir>

source ~mh6/sing.bash
set -eo pipefail

tolid=$1
version=$2
curated_dir=$3
draft_dir=$4
species_path=${draft_dir%%/assembly/draft*}

kmerdb=""
for tech in pacbio ont; do
    if [ -d "$species_path/genomic_data/$tolid/$tech/kmer/k31" ]; then
        kmerdb="$species_path/genomic_data/$tolid/$tech/kmer/k31/fastk"
        echo "Using $tech kmer db: $kmerdb"
        break
    fi
done
if [ -z "$kmerdb" ]; then
    echo "ERROR: no kmer db for $tolid under $species_path/genomic_data/$tolid/{pacbio,ont}/kmer/k31" >&2
    exit 1
fi
echo "curated_dir: $curated_dir"
echo "draft_dir: $draft_dir"

# the copied kmer db and assemblies are big; never leave them in the workdir
trap 'Fastrm fastk .*MQY* 2>/dev/null || true; rm -f hap1.fa hap2.fa' EXIT

hap1=$(ls "$curated_dir"/*.hap1."$version".primary.curated.fa 2>/dev/null | head -1 || true)
hap2=$(ls "$curated_dir"/*.hap2."$version".primary.curated.fa 2>/dev/null | head -1 || true)
if [ -s "$hap1" ] && [ -s "$hap2" ]; then
    echo "hap1/hap2 mode"
    cp "$hap1" hap1.fa
    cp "$hap2" hap2.fa
else
    echo "primary/alt mode"
    cp "$curated_dir"/*.primary.curated.fa hap1.fa
    cat "$curated_dir"/*.additional_haplotigs.curated.fa > hap2.fa 2>/dev/null || true
    zcat "$draft_dir"/*.haplotigs.decontaminated.fa.gz >> hap2.fa 2>/dev/null || true
fi

# MerquryFK writes no .completeness.stats for an empty hap2
hap2_param=hap2.fa
if [ ! -s hap2.fa ]; then
    hap2_param=""
    echo "Warning: hap2.fa is empty, proceeding without it"
fi

Fastcp "$kmerdb" .
bsub -K -J "$tolid.merqury" -o merqury.out -e merqury.err -q normal -n16 -M40G \
    -R 'select[type==X86_64 && mem>40G] rusage[mem=40G] span[hosts=1]' \
    MerquryFK -T16 fastk hap1.fa $hap2_param "$tolid"
