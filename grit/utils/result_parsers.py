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
    autosomes: int | None = None      # non-sex, non-unloc chromosomes
    allosomes: str = ""               # e.g. "ZW", "XY", "Z1W1W2"
    cuts: int | None = None
    breaks: int | None = None
    joins: int | None = None
    sex_matches: list[tuple[str, str]] = field(default_factory=list)  # (scaffold, count)
    qv_text: str | None = None
    completeness_text: str | None = None

    def has_any(self) -> bool:
        return any([
            self.autosomes is not None,
            self.cuts is not None,
            self.sex_matches,
            self.qv_text,
            self.completeness_text,
        ])


# ---------------------------------------------------------------------------
# Individual parsers
# ---------------------------------------------------------------------------

def parse_chromosome_list(path: Path) -> tuple[int, list[str]]:
    """Return (autosome_count, [sex_chrom_ids]) from one haplotype CSV.

    Unlocalized scaffolds (_unloc_) are excluded from both counts.
    sex_chrom_ids are the raw chromosome IDs (e.g. "Z", "W", "Z1", "W1").
    """
    autosomes = 0
    sex_ids = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        chrom_id = parts[1].strip()
        if "_unloc_" in chrom_id.lower():
            continue
        if re.search(r'[XYZW]', chrom_id, re.IGNORECASE):
            sex_ids.append(chrom_id.strip())
        else:
            autosomes += 1
    return autosomes, sex_ids


_SEX_SORT_ORDER = {"Z": 0, "X": 0, "W": 1, "Y": 1}


def _build_allosome_string(sex_ids: list[str]) -> str:
    """Build canonical allosome string from sex chrom IDs across all haplotypes.

    Single sex chrom found → append "O" (e.g. "Z" → "ZO").
    Multiple → sort Z/X before W/Y, then join (e.g. ["W", "Z"] → "ZW").
    """
    if not sex_ids:
        return ""
    if len(sex_ids) == 1:
        return sex_ids[0] + "O"

    def sort_key(s: str) -> tuple:
        letter = re.sub(r'\d', '', s).upper()
        num = int(m.group()) if (m := re.search(r'\d+', s)) else 0
        return (_SEX_SORT_ORDER.get(letter, 2), num, letter)

    return "".join(sorted(sex_ids, key=sort_key))


def parse_pta_log(path: Path) -> tuple[int, int, int] | None:
    """Return (cuts, breaks, joins) from pretext_to_asm log, or None if not found."""
    m = re.search(
        r"Curation made (\d+) cuts? in (?:\w+\s+)?contigs?,\s*"
        r"(\d+) breaks? at (?:\w+\s+)?gaps? and (\d+) joins?",
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

    # --- chromosome list (aggregate across all haplotype CSVs) ---
    for d in [d for d in (pta_dir, workdir) if d and d.exists()]:
        csv_files = sorted(d.glob(f"{tol_id}*.chromosome.list.csv"))
        if csv_files:
            try:
                all_sex_ids: list[str] = []
                for i, csv_path in enumerate(csv_files):
                    autosomes, sex_ids = parse_chromosome_list(csv_path)
                    if i == 0:
                        r.autosomes = autosomes  # use first hap for autosome count
                    all_sex_ids.extend(sex_ids)
                r.allosomes = _build_allosome_string(all_sex_ids)
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

    # --- QV and completeness: tracker outputs first, curated_dir/merquryk fallback ---
    qv_path = Path(tracker.get_output("qv", "qv")) if tracker and tracker.get_output("qv", "qv") else None
    comp_path = (
        Path(tracker.get_output("qv", "completeness_stats"))
        if tracker and tracker.get_output("qv", "completeness_stats")
        else None
    )

    if curated_dir:
        mdir = curated_dir / "merquryk"
        if qv_path is None:
            qv_path = mdir / f"{tol_id}.qv"
        if comp_path is None:
            comp_path = mdir / f"{tol_id}.completeness.stats"

    if qv_path and qv_path.exists():
        try:
            r.qv_text = read_tabular(qv_path)
        except Exception:
            pass

    if comp_path and comp_path.exists():
        try:
            r.completeness_text = read_tabular(comp_path)
        except Exception:
            pass

    return r
