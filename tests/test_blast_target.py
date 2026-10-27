"""Tests for blast-target: headers parsing, unknown headers, BED verdicts, canonical untouched."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import rich_click as click

from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.steps.optional.blast_target import parse_headers, run_blast_target

_FAI = (
    "HAP1_SCAFFOLD_1\t500\t0\t60\t61\nHAP1_SCAFFOLD_2\t700\t0\t60\t61\n"
    "HAP2_SCAFFOLD_3\t900\t0\t60\t61\n"
)
_TAXONOMY = (
    "HAP1_SCAFFOLD_1\t99.1\tEukaryota; Metazoa; Chordata; Chordata; Vertebrata\n"
    "HAP1_SCAFFOLD_2\t98.0\tBacteria; Pseudomonadati; Pseudomonadota; Gammaproteobacteria\n"
    "HAP1_SCAFFOLD_2\t50.0\tEukaryota; Metazoa; Chordata; Chordata; Vertebrata\n"
)


def _setup(ctx, tmp_path):
    ctx.workdir = tmp_path
    reg = RegistryManager(registry_dir=tmp_path / ".grit_reg")
    reg.add_ticket(ctx.ticket_id, ctx.tol_id, ctx.species, tmp_path)
    ctx.tracker = RunTracker(tmp_path, registry=reg)
    (tmp_path / "original.fa").write_text(">HAP1_SCAFFOLD_1\nACGT\n")


def _fake_run(cmd, print_only=False):
    """Write the .fai on indexing and taxonomy.txt on decon_fasta."""
    if cmd.endswith("original.fa"):
        Path(cmd.split()[-1] + ".fai").write_text(_FAI)
    elif "--outdir" in cmd:
        out = Path(cmd.split("--outdir ")[1].strip())
        out.mkdir(parents=True, exist_ok=True)
        (out / "taxonomy.txt").write_text(_TAXONOMY)
    return ""


def test_parse_headers_string_and_file(tmp_path):
    assert parse_headers("HAP1_SCAFFOLD_1, HAP2_SCAFFOLD_3 ,") == [
        "HAP1_SCAFFOLD_1",
        "HAP2_SCAFFOLD_3",
    ]
    f = tmp_path / "targets.txt"
    f.write_text("# suspects\nHAP1_SCAFFOLD_1\n\n  HAP2_SCAFFOLD_3  \n")
    assert parse_headers(str(f)) == ["HAP1_SCAFFOLD_1", "HAP2_SCAFFOLD_3"]


@patch("grit.steps.optional.blast_target.target_phylum", return_value="Chordata")
@patch("grit.steps.optional.blast_target._run", side_effect=_fake_run)
def test_bed_verdicts_and_unknown_header(mock_run, _phylum, mock_ctx, tmp_path, caplog):
    _setup(mock_ctx, tmp_path)
    from grit.utils.helpers import find_canonical_fa

    try:
        before = find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix)
    except FileNotFoundError:
        before = None

    with caplog.at_level(logging.WARNING):
        run_blast_target(
            mock_ctx, ["HAP1_SCAFFOLD_1", "HAP1_SCAFFOLD_2", "HAP2_SCAFFOLD_3", "HAP1_SCAFFOLD_99"]
        )

    assert "HAP1_SCAFFOLD_99" in caplog.text
    extract = next(c.args[0] for c in mock_run.call_args_list if "targets.fa" in c.args[0])
    assert "HAP1_SCAFFOLD_99" not in extract and "HAP2_SCAFFOLD_3" in extract

    last = mock_ctx.tracker.history("blast_target")[-1]
    assert last["status"] == "success"
    bed = open(last["outputs"]["bed"]).read().splitlines()
    assert bed == [
        "HAP1_SCAFFOLD_1\t0\t500\tKEEP",
        "HAP1_SCAFFOLD_2\t0\t700\tREMOVE",
        "HAP2_SCAFFOLD_3\t0\t900\tNO_HIT",
    ]
    assert open(last["outputs"]["taxonomy"]).read() == _TAXONOMY

    try:
        after = find_canonical_fa(mock_ctx, mock_ctx.hap1_prefix)
    except FileNotFoundError:
        after = None
    assert before == after


@patch("grit.steps.optional.blast_target._run", side_effect=_fake_run)
def test_all_unknown_starts_no_run(mock_run, mock_ctx, tmp_path, caplog):
    _setup(mock_ctx, tmp_path)
    with caplog.at_level(logging.WARNING):
        run_blast_target(mock_ctx, ["NOPE_1"])
    assert "nothing to blast" in caplog.text
    assert mock_ctx.tracker.history("blast_target") == []


@patch("grit.steps.optional.blast_target.target_phylum", return_value="Chordata")
@patch("grit.steps.optional.blast_target._run", side_effect=_fake_run)
def test_failure_finishes_failed(mock_run, _phylum, mock_ctx, tmp_path):
    _setup(mock_ctx, tmp_path)
    mock_run.side_effect = lambda cmd, p=False: (
        _fake_run(cmd) if cmd.endswith("original.fa") else ""
    )
    with pytest.raises(FileNotFoundError):
        run_blast_target(mock_ctx, ["HAP1_SCAFFOLD_1"])
    assert mock_ctx.tracker.history("blast_target")[-1]["status"] == "failed"


def test_missing_original_fa(mock_ctx, tmp_path):
    mock_ctx.workdir = tmp_path
    with pytest.raises(click.UsageError, match="grit setup"):
        run_blast_target(mock_ctx, ["HAP1_SCAFFOLD_1"])
