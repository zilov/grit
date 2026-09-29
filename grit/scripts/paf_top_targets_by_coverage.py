#!/usr/bin/env python3
"""
Usage: python paf_top_targets_by_coverage.py <file.paf> --top1-out <path> [--min-length N]

For every query contig in the PAF, finds its best reference target by total
non-overlapping alignment length (query coordinates).

PAF records shorter than --min-length (default 3000bp) are dropped before
merging, so a handful of short spurious hits can't distort the coverage
totals or the best-target pick below.

--top1-out PATH  Write a curated_fa_chr/ref_fa_chr/aligned_length/
                 prc_of_ref_length table (one row per query: the target with
                 the largest non-overlapping aligned length, and what percent
                 of that target's length the aligned length covers) to PATH.
                 Queries with no alignment surviving --min-length are
                 omitted.
--min-length N   Drop PAF records shorter than N bp (query-side block
                 length) before merging. Default 3000.
"""

import sys
from collections import defaultdict


def _arg_value(flag, default=None):
    if flag not in sys.argv:
        return default
    return sys.argv[sys.argv.index(flag) + 1]


def merge_intervals(intervals):
    """Sum the non-overlapping bp covered by a list of (start, end) query intervals."""
    if not intervals:
        return 0
    sorted_ivs = sorted(intervals)
    merged = [sorted_ivs[0]]
    for start, end in sorted_ivs[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(e - s for s, e in merged)


def parse_paf(paf_path, min_length):
    """
    Read a PAF file, dropping records shorter than min_length (query-side block length).

    Returns:
        query_order:    list of query names in first-seen order
        pair_intervals: (query, target) -> list of (q_start, q_end)
        target_lengths: target name -> target_length (bp), from PAF column 7
    """
    query_order = []
    seen_queries = set()
    pair_intervals = defaultdict(list)
    target_lengths = {}

    with open(paf_path) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.split("\t")
            if len(cols) < 12:
                continue

            q_name = cols[0]
            if q_name not in seen_queries:
                seen_queries.add(q_name)
                query_order.append(q_name)

            q_start = int(cols[2])
            q_end = int(cols[3])
            t_name = cols[5]
            t_length = int(cols[6])
            length = q_end - q_start

            if length < min_length:
                continue

            target_lengths.setdefault(t_name, t_length)
            pair_intervals[(q_name, t_name)].append((q_start, q_end))

    return query_order, pair_intervals, target_lengths


def best_targets_by_coverage(query_order, pair_intervals, target_lengths):
    """
    For each query, pick the target with the largest non-overlapping aligned length.

    Returns a dict of query -> (best_target, aligned_length, prc_of_ref_length),
    omitting queries with no surviving (post-filter) alignment.
    """
    best = {}
    for query_name in query_order:
        coverage = {
            t_name: merge_intervals(ivs)
            for (q_name, t_name), ivs in pair_intervals.items()
            if q_name == query_name
        }
        if not coverage:
            continue
        best_target = max(coverage, key=coverage.get)
        aligned_length = coverage[best_target]
        target_length = target_lengths[best_target]
        prc_of_ref_length = (aligned_length / target_length) * 100 if target_length else 0.0
        best[query_name] = (best_target, aligned_length, prc_of_ref_length)
    return best


def main():
    top1_out = _arg_value("--top1-out")
    if len(sys.argv) < 2 or not top1_out:
        usage = f"Usage: {sys.argv[0]} <file.paf> --top1-out <path> [--min-length N]"
        print(usage, file=sys.stderr)
        sys.exit(1)

    paf_path = sys.argv[1]
    min_length = int(_arg_value("--min-length", "3000"))

    query_order, pair_intervals, target_lengths = parse_paf(paf_path, min_length)

    if not query_order:
        print(f"No alignments found in: {paf_path}", file=sys.stderr)
        sys.exit(0)

    best = best_targets_by_coverage(query_order, pair_intervals, target_lengths)

    with open(top1_out, "w") as fh:
        fh.write("curated_fa_chr\tref_fa_chr\taligned_length\tprc_of_ref_length\n")
        for query_name in query_order:
            if query_name not in best:
                continue
            target, aligned_length, pct = best[query_name]
            fh.write(f"{query_name}\t{target}\t{aligned_length}\t{pct:.2f}\n")


if __name__ == "__main__":
    main()
