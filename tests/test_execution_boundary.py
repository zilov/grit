"""Boundary tests for the execution seam: _run, _submit_bsub, build_bsub_opts,
_state_update_epilogue and the hidden `_state-update` command.

These run the real shell (and a fake `bsub`/`grit` on $PATH) instead of
mocking `_run`, so a mis-quoted command line fails here.
"""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from grit.core.click_cli import cli
from grit.core.registry import RegistryManager
from grit.utils.helpers import (
    _run,
    _state_update_epilogue,
    _submit_bsub,
    build_bsub_opts,
    write_fake_outputs,
)

BANNER = "Job <4242> is submitted to queue <normal>."


def _executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _argv(record: Path) -> list[str]:
    """Return the argv a fake executable recorded, one NUL-terminated arg each."""
    return record.read_bytes().decode().split("\0")[:-1]


@pytest.fixture
def fake_bsub(tmp_path, monkeypatch):
    """Put a `bsub` on $PATH that records its argv and prints $FAKE_BSUB_STDOUT."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    record = tmp_path / "bsub.argv"
    _executable(
        bindir / "bsub",
        f"#!/bin/sh\nprintf '%s\\0' \"$@\" > {record}\n"
        'printf "%s\\n" "$FAKE_BSUB_STDOUT"\n'
        'printf "%s" "$FAKE_BSUB_STDERR" >&2\n'
        'exit "${FAKE_BSUB_EXIT:-0}"\n',
    )
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_BSUB_STDOUT", BANNER)
    return record


@pytest.fixture
def fake_grit(tmp_path, monkeypatch):
    """Point sys.argv[0] (the epilogue's grit binary) at a script that records its argv."""
    record = tmp_path / "grit.argv"
    script = _executable(tmp_path / "fake-grit", f"#!/bin/sh\nprintf '%s\\0' \"$@\" > {record}\n")
    monkeypatch.setattr(sys, "argv", [str(script)])
    return script, record


# ---------------------------------------------------------------------------
# _run — the subprocess branch, unmocked
# ---------------------------------------------------------------------------


def test_run_returns_stripped_stdout():
    assert _run("printf '  hello  \\n\\n'") == "hello"


def test_run_executes_through_a_shell():
    assert _run("echo a && echo b | tr b c") == "a\nc"


def test_run_raises_on_nonzero_exit():
    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        _run("exit 3")
    assert excinfo.value.returncode == 3


def test_run_print_only_does_not_execute(tmp_path):
    target = tmp_path / "touched"
    assert _run(f"touch {target}", print_only=True) == ""
    assert not target.exists()


def test_run_uncaptured_executes_and_returns_empty(tmp_path):
    target = tmp_path / "touched"
    assert _run(f"touch {target} && echo visible", capture=False) == ""
    assert target.exists()


def test_run_uncaptured_raises_on_nonzero_exit():
    with pytest.raises(subprocess.CalledProcessError):
        _run("exit 4", capture=False)


# ---------------------------------------------------------------------------
# build_bsub_opts
# ---------------------------------------------------------------------------


def test_build_bsub_opts_defaults():
    assert build_bsub_opts() == (
        "-q normal -o lsf.log -M 4000 -R'select[mem>4000] rusage[mem=4000] span[hosts=1]'"
    )


def test_build_bsub_opts_every_option():
    opts = build_bsub_opts(
        queue="long",
        memory_mb=50000,
        cores=8,
        output="out.log",
        error="err.log",
        group="grit-grp",
        wait=True,
    )
    assert opts == (
        "-q long -n 8 -G grit-grp -K -o out.log -e err.log -M 50000 "
        "-R'select[mem>50000] rusage[mem=50000] span[hosts=1]'"
    )


def test_build_bsub_opts_prefixes_relative_logs_with_run_dir(tmp_path):
    opts = build_bsub_opts(output="job.out", error="job.err", run_dir=tmp_path)
    assert f"-o {tmp_path}/job.out" in opts
    assert f"-e {tmp_path}/job.err" in opts


def test_build_bsub_opts_leaves_log_paths_with_a_slash_alone(tmp_path):
    opts = build_bsub_opts(output="/abs/job.out", error="sub/job.err", run_dir=tmp_path)
    assert "-o /abs/job.out" in opts
    assert "-e sub/job.err" in opts


def test_build_bsub_opts_omits_cores_flag_for_one_core():
    assert "-n" not in build_bsub_opts(cores=1).split()


# ---------------------------------------------------------------------------
# _submit_bsub — through the real shell into a fake bsub
# ---------------------------------------------------------------------------


def test_submit_bsub_passes_opts_then_inner_cmd_as_one_argument(fake_bsub, tmp_path):
    inner = "cd /work && tool --in a.fa | gzip > out.gz; echo 'done'"
    opts = build_bsub_opts(memory_mb=1000, output="lsf.log", run_dir=tmp_path)

    job_id = _submit_bsub(inner, opts)

    assert job_id == "4242"
    assert _argv(fake_bsub) == [
        "-q",
        "normal",
        "-o",
        f"{tmp_path}/lsf.log",
        "-M",
        "1000",
        "-Rselect[mem>1000] rusage[mem=1000] span[hosts=1]",
        inner,
    ]


def test_submit_bsub_passes_the_epilogue_as_one_unexpanded_argument(fake_bsub, fake_grit, tmp_path):
    epilogue = _state_update_epilogue(tmp_path / "wd", "fastga", tmp_path / "wd" / "run")

    _submit_bsub("true", "-q normal", epilogue_cmd=epilogue)

    argv = _argv(fake_bsub)
    assert argv[:2] == ["-Ep", epilogue]
    assert "$LSB_JOBEXIT_STAT" in argv[1]
    assert argv[2:] == ["-q", "normal", "true"]


def test_submit_bsub_expands_unescaped_dollar_vars_at_submit_time(fake_bsub, monkeypatch):
    monkeypatch.setenv("SUBMIT_SIDE", "login-node")

    _submit_bsub("echo $SUBMIT_SIDE \\$JOB_SIDE", "-q normal")

    assert _argv(fake_bsub)[-1] == "echo login-node $JOB_SIDE"


def test_submit_bsub_parses_job_id_after_a_preceding_line(fake_bsub, monkeypatch):
    monkeypatch.setenv("FAKE_BSUB_STDOUT", f"Info: using default project\n{BANNER}")
    assert _submit_bsub("true", "-q normal") == "4242"


def test_submit_bsub_print_only_submits_nothing(fake_bsub):
    assert _submit_bsub("true", "-q normal", print_only=True) == ""
    assert not fake_bsub.exists()


def test_submit_bsub_raises_when_bsub_rejects_the_job(fake_bsub, monkeypatch):
    monkeypatch.setenv("FAKE_BSUB_STDOUT", "")
    monkeypatch.setenv("FAKE_BSUB_EXIT", "255")
    with pytest.raises(subprocess.CalledProcessError):
        _submit_bsub("true", "-q normal")


# ---------------------------------------------------------------------------
# _state_update_epilogue
# ---------------------------------------------------------------------------


def test_epilogue_string_shape(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/opt/grit/bin/grit"])
    epilogue = _state_update_epilogue(Path("/wd"), "fastga", Path("/wd/fastga/run1"))
    assert epilogue == (
        "/opt/grit/bin/grit _state-update --workdir /wd --step fastga "
        "--run-dir /wd/fastga/run1 "
        "--status $([ $LSB_JOBEXIT_STAT -eq 0 ] && echo success || echo failed)"
    )


def test_epilogue_appends_untracked_flag(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["/opt/grit/bin/grit"])
    epilogue = _state_update_epilogue(Path("/wd"), "fastga", Path("/wd/r"), untracked=True)
    assert epilogue.endswith(" --untracked")


def _run_epilogue(epilogue: str, exit_stat: str | None) -> None:
    env = {k: v for k, v in os.environ.items() if k != "LSB_JOBEXIT_STAT"}
    if exit_stat is not None:
        env["LSB_JOBEXIT_STAT"] = exit_stat
    subprocess.run(["sh", "-c", epilogue], env=env, check=True, capture_output=True)


@pytest.mark.parametrize(
    ("exit_stat", "untracked", "expected_tail"),
    [
        ("0", False, ["--status", "success"]),
        ("256", False, ["--status", "failed"]),
        ("0", True, ["--status", "success", "--untracked"]),
        ("9", True, ["--status", "failed", "--untracked"]),
        (None, False, ["--status", "failed"]),
    ],
)
def test_epilogue_run_by_lsf_calls_state_update_with_the_job_outcome(
    fake_bsub, fake_grit, tmp_path, exit_stat, untracked, expected_tail
):
    """Submit through the real shell, then run the -Ep argument bsub received as LSF would."""
    _, grit_record = fake_grit
    workdir, run_dir = tmp_path / "wd", tmp_path / "wd" / "fastga" / "run1"
    _submit_bsub(
        "true",
        "-q normal",
        epilogue_cmd=_state_update_epilogue(workdir, "fastga", run_dir, untracked=untracked),
    )

    _run_epilogue(_argv(fake_bsub)[1], exit_stat)

    assert _argv(grit_record) == [
        "_state-update",
        "--workdir",
        str(workdir),
        "--step",
        "fastga",
        "--run-dir",
        str(run_dir),
        *expected_tail,
    ]


# ---------------------------------------------------------------------------
# `grit _state-update` — current behaviour
# ---------------------------------------------------------------------------


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    """A ticket in a tmp default registry with one started rename_and_orient run."""
    monkeypatch.setattr("grit.core.registry._DEFAULT_DIR", tmp_path / "reg")
    workdir = tmp_path / "wd"
    run_dir = workdir / "rename_and_orient" / "2026-01-01T00_00_00"
    run_dir.mkdir(parents=True)
    reg = RegistryManager()
    reg.add_ticket("RC-1234", "sDipInt39", "species", workdir)
    reg.append_step(
        workdir,
        {"step": "rename_and_orient", "status": "started", "run_dir": str(run_dir)},
    )
    return reg, workdir, run_dir


def _state_update(workdir, run_dir, *extra):
    return CliRunner().invoke(
        cli,
        [
            "_state-update",
            "--workdir",
            str(workdir),
            "--step",
            "rename_and_orient",
            "--run-dir",
            str(run_dir),
            *extra,
        ],
    )


def _last_record(reg, workdir):
    return reg.get_steps(workdir, "rename_and_orient")[-1]


def test_state_update_success_records_outputs_found_on_disk(seeded):
    reg, workdir, run_dir = seeded
    written = write_fake_outputs("rename_and_orient", run_dir, "sDipInt39")

    result = _state_update(workdir, run_dir, "--status", "success", "--job-id", "77")

    assert result.exit_code == 0, result.output
    record = _last_record(reg, workdir)
    assert record["status"] == "success"
    assert record["job_id"] == "77"
    assert record["run_dir"] == str(run_dir)
    assert record["outputs"] == written


def test_state_update_success_with_no_outputs_still_records_success(seeded):
    """Current behaviour, pending CORR-03: an empty glob does not downgrade the status."""
    reg, workdir, run_dir = seeded

    result = _state_update(workdir, run_dir, "--status", "success")

    assert result.exit_code == 0, result.output
    record = _last_record(reg, workdir)
    assert record["status"] == "success"
    assert "outputs" not in record


def test_state_update_failed_does_not_collect_outputs(seeded):
    reg, workdir, run_dir = seeded
    write_fake_outputs("rename_and_orient", run_dir, "sDipInt39")

    result = _state_update(workdir, run_dir, "--status", "failed")

    assert result.exit_code == 0, result.output
    record = _last_record(reg, workdir)
    assert record["status"] == "failed"
    assert "outputs" not in record


def test_state_update_untracked_keeps_the_marker_and_records_outputs(seeded):
    reg, workdir, run_dir = seeded
    written = write_fake_outputs("rename_and_orient", run_dir, "sDipInt39")

    result = _state_update(workdir, run_dir, "--status", "success", "--untracked")

    assert result.exit_code == 0, result.output
    record = _last_record(reg, workdir)
    assert record["status"] == "untracked"
    assert record["outputs"] == written


def test_state_update_for_an_unregistered_workdir_writes_nothing(seeded, tmp_path):
    reg, workdir, _ = seeded
    stray = tmp_path / "elsewhere"

    result = _state_update(stray, stray / "run", "--status", "success")

    assert result.exit_code == 0, result.output
    assert reg.get_steps(stray) == []
    assert _last_record(reg, workdir)["status"] == "started"


def test_state_update_rejects_an_unknown_status(seeded):
    _, workdir, run_dir = seeded
    result = _state_update(workdir, run_dir, "--status", "done")
    assert result.exit_code == 2


def test_state_update_is_hidden_from_help():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "_state-update" not in result.output
