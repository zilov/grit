#!/bin/bash

source /nfs/users/nfs_m/mh6/sing.bash
IMAGE=/nfs/treeoflife-01/teams/grit/users/mh6/singularity/busco.sif

myDirPath=`pwd`
myFasta=$myDirPath/original.fa
myDir=$1
myTolPrefix2=`echo ${myDir:1:1}`
myTolPrefix1=`echo ${myDir:0:1}`

beetle_X_buscos=/nfs/users/nfs_d/da16/vgp_curation_scripts/coleop_X_buscos
lep_Z_buscos=/nfs/users/nfs_d/da16/vgp_curation_scripts/lep_Z_buscos
nematode_X_buscos=/nfs/users/nfs_d/da16/vgp_curation_scripts/nematode_X_buscos

if [ $myTolPrefix1 == "i" ]; then
    myTolPrefix=$myTolPrefix2
    if [ $myTolPrefix2 == "c" ]; then
        echo "genome of a beetle"
        singularity exec -B /lustre $IMAGE busco -i $myFasta -o busco5 -m genome -l /lustre/scratch122/tol/resources/busco/latest/lineages/endopterygota_odb10 -c 32
        sexFile=/nfs/users/nfs_d/da16/vgp_curation_scripts/coleop_X_buscos
    elif [ $myTolPrefix2 == "l" ]; then
        echo "genome of a lep"
        singularity exec -B /lustre $IMAGE busco -i $myFasta -o busco5 -m genome -l /lustre/scratch122/tol/resources/busco/latest/lineages/lepidoptera_odb10 -c 32
        sexFile=/nfs/users/nfs_d/da16/vgp_curation_scripts/lep_Z_buscos
    elif [ $myTolPrefix2 == "d" ]; then
        echo "genome of a diptera"
        singularity exec -B /lustre $IMAGE busco -i $myFasta -o busco5 -m genome -l /lustre/scratch122/tol/resources/busco/latest/lineages/diptera_odb10 -c 32
        sexFile=/nfs/users/nfs_d/da16/vgp_curation_scripts/dip_LG6
    fi
elif [ $myTolPrefix1 == "n" ]; then
    myTolPrefix=$myTolPrefix1
    echo "genome of a nematode"
    singularity exec -B /lustre $IMAGE busco -i $myFasta -o busco5 -m genome -l /lustre/scratch122/tol/resources/busco/latest/lineages/nematoda_odb10 -c 32
    sexFile=/nfs/users/nfs_d/da16/vgp_curation_scripts/nematode_X_buscos
else
    echo "Not a nematode, lepidoptera or coleoptera"
fi

wait

mv $myDirPath/busco5/run_*/full_table.tsv $myDirPath
wait
grep -f $sexFile $myDirPath/full_table.tsv > sex_table.tsv
wait
/software/grit/projects/vgp_curation_scripts/sex_matcher.py -p $myDirPath -i $myTolPrefix
wait
rm -r $myDirPath/busco*
