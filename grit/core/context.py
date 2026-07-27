"""
CurationContext — central state object for the curation pipeline.

Created via CurationContext.from_ticket(ticket_id, user_config) and passed to
all step functions. Holds no global state.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from grit.core.run_tracker import RunTracker


@dataclass
class UserConfig:
    """Curator user config (loaded from ~/.grit_curation_config.yaml)."""

    username: str
    pretext_maps_nfs: Path
    curated_pretext_maps_nfs: Path
    curation_savestates_nfs: Path
    farm_host: str
    email: str
    gritjiraissue_path: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UserConfig":
        return cls(
            username=d["username"],
            pretext_maps_nfs=Path(d["pretext_maps_nfs"]),
            curated_pretext_maps_nfs=Path(d["curated_pretext_maps_nfs"]),
            curation_savestates_nfs=Path(d["curation_savestates_nfs"]),
            farm_host=d["farm_host"],
            email=d["email"],
            gritjiraissue_path=d["gritjiraissue_path"],
        )


@dataclass
class CurationContext:
    """
    Full context for a single curation ticket.

    All paths are computed; all fields from the Jira YAML are parsed.
    Created via CurationContext.from_ticket() or CurationContext.from_yaml().
    """

    # --- identifiers ---
    ticket_id: str
    tol_id: str
    species: str

    # --- assembly type ---
    assembly_type: str  # 'hap1' | 'primary' | 'paternal'
    hap1_prefix: str  # 'hap1' | 'primary' | 'paternal'
    hap2_prefix: str  # 'hap2' | 'alternate' | 'maternal'
    combine_for_curation: bool  # merged map flag

    # --- sequencing data ---
    hic_dir: Path
    long_reads_dir: Path
    read_type: str  # 'hifi' | 'ont'

    # --- assembly paths ---
    assembly_draft_dir: Path  # .../assembly/draft/<tol_id.date>/
    assembly_curated_dir: Path  # .../assembly/curated/<tol_id.release>/

    # --- working directory ---
    workdir: Path  # .../working/<username>_curation/<tol_id>/

    # --- NFS paths (from user config) ---
    pretext_maps_nfs: Path
    curated_pretext_maps_nfs: Path
    curation_savestates_nfs: Path

    # --- farm access ---
    farm_host: str
    username: str
    email: str

    # --- optional fields ---
    teloseq: str = ""  # "--teloseq TTAGG" or ""
    release_version: int = 1  # release version from the ticket
    print_only: bool = False  # if True, print commands instead of running them
    untracked: bool = False  # if True, tracker.start() marks runs as non-canonical
    bsub_ram: int | None = None  # if set, overrides a step's default LSF memory limit (MB)

    # --- raw data ---
    yaml_data: dict[str, Any] = field(default_factory=dict)

    # --- run tracking (populated by from_yaml) ---
    tracker: RunTracker | None = field(default=None, repr=False, compare=False)

    @property
    def tol_id_versioned(self) -> str:
        """Example: sDipInt39.1"""
        return f"{self.tol_id}.{self.release_version}"

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(
        cls,
        ticket_id: str,
        yaml_data: dict[str, Any],
        user_config: dict[str, Any],
        *,
        teloseq: str = "",
        print_only: bool = False,
        untracked: bool = False,
        bsub_ram: int | None = None,
    ) -> "CurationContext":
        """
        Build a CurationContext directly from a parsed YAML dict and user config.

        This is the canonical constructor — all field derivation lives here.
        """
        cfg = UserConfig.from_dict(user_config)

        assembly_type, hap1_prefix, hap2_prefix = _detect_assembly_type(yaml_data)

        tol_id: str = yaml_data["specimen"]
        species: str = yaml_data.get("species", "")
        hic_dir = Path(yaml_data["hic_read_dir"])

        pacbio_dir_raw: str = yaml_data.get("pacbio_read_dir") or ""
        ont_dir_raw: str = yaml_data.get("ont_read_dir") or ""
        pacbio_read_type: str = yaml_data.get("pacbio_read_type") or ""

        if pacbio_dir_raw:
            long_reads_dir = Path(pacbio_dir_raw)
            read_type = "hifi" if pacbio_read_type else "hifi"
        elif ont_dir_raw:
            long_reads_dir = Path(ont_dir_raw.replace("fasta", ""))
            read_type = "ont"
        else:
            raise ValueError(f"No long reads found in YAML for ticket {ticket_id}")

        # assembly_draft_dir = versioned subdir, e.g. .../assembly/draft/sDipInt39.1/
        assembly_draft_dir = Path(yaml_data[assembly_type]).parent

        combine_for_curation: bool = bool(yaml_data.get("combine_for_curation", False))
        release_version: int = int(yaml_data.get("release_version", 1))

        assembly_curated_dir = (
            Path(str(assembly_draft_dir.parent).replace("assembly/draft", "assembly/curated"))
            / f"{tol_id}.{release_version}"
        )

        workdir = _derive_workdir(assembly_draft_dir.parent, cfg.username, tol_id)

        from grit.core.run_tracker import RunTracker

        return cls(
            ticket_id=ticket_id,
            tol_id=tol_id,
            species=species,
            assembly_type=assembly_type,
            hap1_prefix=hap1_prefix,
            hap2_prefix=hap2_prefix,
            combine_for_curation=combine_for_curation,
            hic_dir=hic_dir,
            long_reads_dir=long_reads_dir,
            read_type=read_type,
            assembly_draft_dir=assembly_draft_dir,
            assembly_curated_dir=assembly_curated_dir,
            workdir=workdir,
            pretext_maps_nfs=cfg.pretext_maps_nfs,
            curated_pretext_maps_nfs=cfg.curated_pretext_maps_nfs,
            curation_savestates_nfs=cfg.curation_savestates_nfs,
            farm_host=cfg.farm_host,
            username=cfg.username,
            email=cfg.email,
            teloseq=teloseq,
            release_version=release_version,
            print_only=print_only,
            untracked=untracked,
            bsub_ram=bsub_ram,
            yaml_data=yaml_data,
            tracker=RunTracker(workdir, print_only=print_only),
        )

    @classmethod
    def from_ticket(
        cls,
        ticket_id: str,
        user_config: dict[str, Any],
        *,
        gritjiraissue_module=None,
        yaml_override: dict[str, Any] | None = None,
        print_only: bool = False,
        untracked: bool = False,
        bsub_ram: int | None = None,
    ) -> "CurationContext":
        """
        Fetch YAML from Jira (or use yaml_override for tests) and build context.
        """
        cfg = UserConfig.from_dict(user_config)

        if yaml_override is not None:
            yaml_data = yaml_override
            teloseq_raw = ""
        else:
            if gritjiraissue_module is None:
                sys.path.insert(0, os.path.expanduser(cfg.gritjiraissue_path))
                import GritJiraIssue as gritjiraissue_module  # noqa: N811

            jira_issue = gritjiraissue_module.GritJiraIssue(ticket_id)
            yaml_data = jira_issue.yaml
            teloseq_raw = jira_issue.issue_json["fields"].get("customfield_11650") or ""

        teloseq = f"--teloseq {teloseq_raw}" if teloseq_raw else ""

        return cls.from_yaml(
            ticket_id,
            yaml_data,
            user_config,
            teloseq=teloseq,
            print_only=print_only,
            untracked=untracked,
            bsub_ram=bsub_ram,
        )


def _detect_assembly_type(
    yaml_data: dict[str, Any],
) -> tuple[str, str, str]:
    """
    Detects assembly type from YAML keys.

    Returns:
        (assembly_type, hap1_prefix, hap2_prefix)
    """
    if "hap1" in yaml_data:
        return "hap1", "hap1", "hap2"
    elif "primary" in yaml_data:
        return "primary", "primary", "alternate"
    else:
        raise ValueError(f"Cannot detect assembly type from YAML keys: {list(yaml_data.keys())}")


def _derive_workdir(assembly_draft_dir: Path, username: str, tol_id: str) -> Path:
    """
    Derives the working directory from the draft assembly path.

    Logic: replace 'assembly/draft' with 'working', append /<username>_curation/<tol_id>/

    Example:
        .../Dipturus_intermedius/assembly/draft/sDipInt39.1/
        → .../Dipturus_intermedius/working/<username>_curation/sDipInt39/
    """
    draft_str = str(assembly_draft_dir)
    if "assembly/draft" not in draft_str:
        raise ValueError(f"Expected 'assembly/draft' in draft path, got: {assembly_draft_dir}")
    working_base = draft_str.replace("assembly/draft", "working")
    # strip version suffix from tol_id if present (sDipInt39.1 → sDipInt39)
    tol_id_base = tol_id.split(".")[0] if "." in tol_id else tol_id
    return Path(working_base) / f"{username}_curation" / tol_id_base
