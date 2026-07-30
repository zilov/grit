#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pandas",
#     "seaborn",
#     "python-circos",
#     "requests>=2.28",
# ]
# ///
"""Circos-style synteny plot from a FastGA PAF alignment."""

import argparse
import random
from datetime import datetime
from pathlib import Path

import pandas as pd
import pycircos
import seaborn as sns

PAF_COLUMNS = [
    "qname",
    "qlen",
    "qstart",
    "qend",
    "strand",
    "tname",
    "tlen",
    "tstart",
    "tend",
    "matches",
    "alnlen",
    "mapq",
]

parser = argparse.ArgumentParser()
parser.add_argument("-paf", "--paf", required=True, help="FastGA PAF alignment file")
parser.add_argument(
    "-min-len",
    "--min_len",
    type=int,
    default=10_000,
    help="Minimum alignment block length (bp) to plot (default: 10000)",
)
parser.add_argument("-p", "--path", required=True, help="Output directory")
parser.add_argument("-ri", "--ref_id", default="Rf")
parser.add_argument("-qi", "--query_id", default="Qu")
args = parser.parse_args()

sp1 = args.ref_id
sp2 = args.query_id
base_path = f"{args.path}/"

paf = pd.read_csv(args.paf, sep="\t", header=None, usecols=range(12), names=PAF_COLUMNS)
paf = paf[paf["alnlen"] >= args.min_len]
if paf.empty:
    raise SystemExit(f"No alignment blocks >= {args.min_len} bp found in {args.paf}")

################## CHROMOSOMES + LINKS FROM PAF ##################

# Chrom lengths come straight from the PAF's own qlen/tlen columns, and chroms
# are derived from the same (already length-filtered) alignment rows used for
# links - so every chr referenced by a link is guaranteed to have an arc.
ref_chroms = (
    paf[["tname", "tlen"]].drop_duplicates().rename(columns={"tname": "chr", "tlen": "end"})
)
query_chroms = (
    paf[["qname", "qlen"]].drop_duplicates().rename(columns={"qname": "chr", "qlen": "end"})
)
ref_chroms["start"] = 1
query_chroms["start"] = 1
chroms = pd.concat([query_chroms, ref_chroms], axis=0, ignore_index=True)

links = paf[["tname", "tstart", "tend", "qname", "qstart", "qend"]].rename(
    columns={
        "tname": "chr1",
        "tstart": "start1",
        "tend": "end1",
        "qname": "chr2",
        "qstart": "start2",
        "qend": "end2",
    }
)

################ PLOTTING ##############

now = datetime.now()
current_time = now.strftime("%Y-%m-%d_%H.%M.%S")
Garc = pycircos.Garc
Gcircle = pycircos.Gcircle
c = chroms

chr1_count = len(ref_chroms)
chr2_count = len(query_chroms)

if chr1_count > 12:
    palette_scheme = "Spectral"
else:
    palette_scheme = "Paired"

palette = sns.color_palette(palette_scheme, chr1_count)
chroms1_colours = list(sns.color_palette(palette))
random.shuffle(chroms1_colours)

chroms2_colours = ["#CDC9C9"] * chr2_count
colour_list = chroms2_colours + chroms1_colours

c["colour"] = colour_list

colour_map = c.set_index("chr")["colour"].to_dict()
links["color"] = links["chr1"].map(colour_map)

circle = Gcircle(figsize=(8, 8))

for i, row in c.iterrows():
    arc = Garc(
        arc_id=row["chr"],
        size=row["end"],
        interspace=2,
        raxis_range=(935, 985),
        labelposition=80,
        label_visible=True,
        facecolor=row["colour"],
    )
    circle.add_garc(arc)

circle.set_garcs()

paf_name = Path(args.paf).stem
circle.ax.set_title(f"{sp1}_vs_{sp2}_{paf_name}", pad=40)

for i, row in links.iterrows():
    source = (row["chr1"], row["start1"], row["end1"], 920)
    destination = (row["chr2"], row["start2"], row["end2"], 920)
    circle.chord_plot(source, destination, facecolor=row["color"])

circle.figure.savefig(
    f"{base_path}/{sp1}_vs_{sp2}_{paf_name}.{current_time}.png",
    dpi=300,
    bbox_inches="tight",
    pad_inches=0.4,
)
