"""Parsers for curation step output files used in `grit status -t`."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class CurationResults:
    chromosomes_total: int | None = None
    sex_chromosomes: list[str] = field(default_factory=list)
    cuts: int | None = None
    breaks: int | None = None
    joins: int | None = None
    sex_matches: list[tuple[str, str]] = field(default_factory=list)  # (scaffold, count)
    qv_text: str | None = None          # raw file content including header
    completeness_text: str | None = None  # raw file content including header

    def has_any(self) -> bool:
        return any([
            self.chromosomes_total is not None,
            self.cuts is not None,
            self.sex_matches,
            self.qv_text,
            self.completeness_text,
        ])


# ---------------------------------------------------------------------------
# Individual parsers
# ---------------------------------------------------------------------------

def parse_chromosome_list(path: Path) -> tuple[int, list[str]]:
    """Return (total_chromosomes, [sex_chromosome_scaffold_names])."""
    total = 0
    sex = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        total += 1
        chrom_id = parts[1].strip().upper()
        if any(c in chrom_id for c in ("X", "Y", "Z", "W")):
            sex.append(parts[0].strip())
    return total, sex


def parse_pta_log(path: Path) -> tuple[int, int, int] | None:
    """Return (cuts, breaks, joins) from pretext_to_asm log, or None if not found."""
    m = re.search(
        r"Curation made (\d+) cuts? in contigs?,\s*(\d+) breaks? at gaps? and (\d+) joins?",
        path.read_text(),
    )
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None


def parse_sex_matcher(path: Path, n: int = 5) -> list[tuple[str, str]]:
    """Return top-n (scaffold, count) pairs from a Best_match* file."""
    lines = path.read_text().splitlines()
    results = []
    for line in lines[1:]:  # skip header
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) >= 2:
            results.append((parts[0].strip(), parts[1].strip()))
        if len(results) >= n:
            break
    return results


def read_tabular(path: Path) -> str:
    """Return file content with whitespace-only lines stripped."""
    return "\n".join(
        line for line in path.read_text().splitlines() if line.strip()
    )


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------

def collect_curation_results(
    tracker,
    workdir: Path,
    tol_id: str,
    curated_dir: Path | None = None,
) -> CurationResults:
    """
    Gather all available curation result data for a ticket workdir.

    Searches pretext_to_asm and sex_matcher run dirs (via tracker).
    QV / completeness files are looked up in:
      1. curated_dir/merquryk/  (assembly curated dir, passed from ctx)
      2. workdir/merquryk/      (fallback)
    """
    r = CurationResults()

    pta_dir = tracker.latest_run_dir("pretext_to_asm") if tracker else None
    sex_dir = tracker.latest_run_dir("sex_matcher") if tracker else None

    # --- chromosome list ---
    for d in [d for d in (pta_dir, workdir) if d and d.exists()]:
        csv_files = list(d.glob(f"{tol_id}*.chromosome.list.csv"))
        if csv_files:
            try:
                r.chromosomes_total, r.sex_chromosomes = parse_chromosome_list(csv_files[0])
            except Exception:
                pass
            break

    # --- pretext_to_asm log (cuts / breaks / joins) ---
    if pta_dir and pta_dir.exists():
        log_files = list(pta_dir.glob(f"{tol_id}*.log"))
        if log_files:
            try:
                parsed = parse_pta_log(log_files[0])
                if parsed:
                    r.cuts, r.breaks, r.joins = parsed
            except Exception:
                pass

    # --- sex matcher ---
    for d in [d for d in (sex_dir, workdir) if d and d.exists()]:
        best_files = list(d.glob("Best_match*"))
        if best_files:
            try:
                r.sex_matches = parse_sex_matcher(best_files[0])
            except Exception:
                pass
            break

    # --- QV and completeness: always in curated_dir/merquryk ---
    if curated_dir:
        mdir = curated_dir / "merquryk"
        if mdir.exists():
            qv_files = list(mdir.glob(f"{tol_id}.qv"))
            if qv_files:
                try:
                    r.qv_text = read_tabular(qv_files[0])
                except Exception:
                    pass

            comp_files = list(mdir.glob("*.completeness.stats"))
            if comp_files:
                try:
                    r.completeness_text = read_tabular(comp_files[0])
                except Exception:
                    pass

    return r
