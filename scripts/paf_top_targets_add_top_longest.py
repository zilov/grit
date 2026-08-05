#!/usr/bin/env python3
"""
Usage: python paf_top_targets.py <file.paf> [--top_longest]

For every query contig in the PAF, finds its top-10 reference targets by
total non-overlapping alignment length (query coordinates).

--top_longest  Also show the top-5 longest alignments per target.
"""

import sys
from collections import defaultdict


def merge_intervals(intervals):
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


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.paf> [--top_longest]", file=sys.stderr)
        sys.exit(1)

    paf_path = sys.argv[1]
    top_longest = "--top_longest" in sys.argv[2:]

    query_order = []
    seen_queries = set()
    # (query, target) -> list of (q_start, q_end)
    pair_intervals = defaultdict(list)
    # (query, target) -> list of (length, q_start, q_end, t_start, t_end)
    pair_alns = defaultdict(list)
    # query -> (length, target) of the single longest alignment seen for that query
    query_best_aln = {}

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
            q_end   = int(cols[3])
            t_name  = cols[5]
            t_start = int(cols[7])
            t_end   = int(cols[8])
            length  = q_end - q_start

            pair_intervals[(q_name, t_name)].append((q_start, q_end))
            if top_longest:
                pair_alns[(q_name, t_name)].append((length, q_start, q_end, t_start, t_end))

            if length > query_best_aln.get(q_name, (-1, None))[0]:
                query_best_aln[q_name] = (length, t_name)

    if not query_order:
        print(f"No alignments found in: {paf_path}", file=sys.stderr)
        sys.exit(0)

    print("##TOP_LONGEST_TABLE##")
    print("super\ttop_longest_ref_chr\tlen")
    for query_name in query_order:
        length, target = query_best_aln[query_name]
        print(f"{query_name}\t{target}\t{length}")
    print("##END_TOP_LONGEST_TABLE##")

    for query_name in query_order:
        coverage = {
            t_name: merge_intervals(ivs)
            for (q_name, t_name), ivs in pair_intervals.items()
            if q_name == query_name
        }
        top10 = sorted(coverage.items(), key=lambda x: x[1], reverse=True)[:10]

        print(f"\n{'#'*80}")
        print(f"Query: {query_name}")
        print(f"{'#'*80}")

        for rank, (target, cov) in enumerate(top10, 1):
            print(f"{'='*80}")
            print(f"#{rank}  {target}")
            print(f"    Total non-overlapping coverage: {cov:,} bp")

            if top_longest:
                top5 = sorted(
                    pair_alns[(query_name, target)], key=lambda x: x[0], reverse=True
                )[:5]
                print(
                    f"    {'Aln':<6} {'Length (bp)':>12}  {'Query start':>12} "
                    f"{'Query end':>12}  {'Target start':>13} {'Target end':>12}"
                )
                print(f"    {'-'*70}")
                for i, (length, qs, qe, ts, te) in enumerate(top5, 1):
                    print(f"    {i:<6} {length:>12,}  {qs:>12,} {qe:>12,}  {ts:>13,} {te:>12,}")

    print("=" * 80)


if __name__ == "__main__":
    main()
