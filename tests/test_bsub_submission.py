"""Every step that submits a bsub job attaches the epilogue and never strands a `started` record."""

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from grit.core.manifests import STEP_MANIFESTS
from grit.core.registry import RegistryManager
from grit.core.run_tracker import RunTracker
from grit.utils.helpers import BsubSubmissionError, CommandError, _get_step_specs

_STEPS_DIR = Path(__file__).parent.parent / "grit" / "steps"

# every step name a step passes to _state_update_epilogue, literal or computed
_EPILOGUE_STEPS = {
    "busco_curated",
    "busco_synteny",
    "fastga",
    "fastga_synteny",
    "hic_remapping",
    "hic_remapping_hap2",
    "rename_and_orient",
    "rename_and_orient_hap2",
    "sex_matcher",
}


def _calls(func_name):
    """Yield (path, call, enclosing Try nodes) for each call to *func_name* under grit/steps."""
    for path in sorted(_STEPS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())

        def walk(node, tries):
            for child in ast.iter_child_nodes(node):
                inner = tries
                if isinstance(node, ast.Try) and child in node.body:
                    inner = [*tries, node]
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == func_name
                ):
                    yield path, child, inner
                yield from walk(child, inner)

        yield from walk(tree, [])


def _submit_sites():
    sites = list(_calls("_submit_bsub"))
    assert sites, "found no _submit_bsub call sites"
    return sites


@pytest.mark.parametrize("site", _submit_sites(), ids=lambda s: f"{s[0].name}:{s[1].lineno}")
def test_every_submit_bsub_call_passes_an_epilogue(site):
    path, call, _ = site
    assert "epilogue_cmd" in {kw.arg for kw in call.keywords}, f"{path}:{call.lineno}"


@pytest.mark.parametrize("site", _submit_sites(), ids=lambda s: f"{s[0].name}:{s[1].lineno}")
def test_every_submit_bsub_call_finishes_the_run_when_submission_fails(site):
    path, call, tries = site
    handled = [
        t
        for t in tries
        for handler in t.handlers
        if any(isinstance(n, ast.Attribute) and n.attr == "finish" for n in ast.walk(handler))
        and any(isinstance(n, ast.Raise) for n in ast.walk(handler))
    ]
    assert handled, f"{path}:{call.lineno} can strand a started record"


def test_every_epilogue_step_has_a_completion_criterion():
    literal = {
        call.args[1].value
        for _, call, _ in _calls("_state_update_epilogue")
        if len(call.args) > 1 and isinstance(call.args[1], ast.Constant)
    }
    assert literal <= _EPILOGUE_STEPS
    for step in _EPILOGUE_STEPS:
        assert _get_step_specs(step) or step in STEP_MANIFESTS, step


# ---------------------------------------------------------------------------
# behaviour: a rejected submission finishes the run failed and re-raises
# ---------------------------------------------------------------------------


def _ctx(mock_ctx, tmp_path, untracked):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "original.fa").write_text(">s\nACGT\n")
    reg = RegistryManager(registry_dir=tmp_path / "reg")
    reg.add_ticket(mock_ctx.ticket_id, "ilHelSara1", mock_ctx.species, workdir)
    mock_ctx.workdir = workdir
    mock_ctx.tol_id = "ilHelSara1"
    mock_ctx.print_only = False
    mock_ctx.untracked = untracked
    mock_ctx.tracker = RunTracker(workdir, registry=reg)
    return mock_ctx


def _run_busco_curated(ctx, tmp_path):
    from grit.steps.optional.busco_curated import run_busco_curated

    fa = tmp_path / "curated.fa"
    fa.write_text(">s\nACGT\n")
    with patch("grit.steps.optional.busco_curated.find_canonical_fa", return_value=fa):
        run_busco_curated(ctx, "insecta_odb10")


def _run_busco_synteny(ctx, tmp_path):
    from grit.steps.optional.busco_synteny import run_busco_synteny

    with (
        patch("grit.steps.optional.busco_synteny.find_canonical_fa", return_value=tmp_path / "q"),
        patch(
            "grit.steps.optional.busco_synteny.find_reheadered_reference",
            return_value=tmp_path / "r",
        ),
    ):
        run_busco_synteny(ctx, "insecta_odb10")


def _run_fastga_synteny(ctx, tmp_path):
    from grit.steps.optional.fastga_synteny import run_fastga_synteny

    fastga_dir = tmp_path / "fastga"
    fastga_dir.mkdir()
    (fastga_dir / "x.FastGA.paf").write_text("")
    with patch("grit.steps.optional.fastga_synteny.find_latest_dir", return_value=fastga_dir):
        run_fastga_synteny(ctx)


def _run_sex_matcher(ctx, tmp_path):
    from grit.steps.pre_curation.sex_matcher import run_sex_matcher

    run_sex_matcher(ctx)


_STEPS = {
    "busco_curated": ("grit.steps.optional.busco_curated", _run_busco_curated),
    "busco_synteny": ("grit.steps.optional.busco_synteny", _run_busco_synteny),
    "fastga_synteny": ("grit.steps.optional.fastga_synteny", _run_fastga_synteny),
    "sex_matcher": ("grit.steps.pre_curation.sex_matcher", _run_sex_matcher),
}


@pytest.mark.parametrize("error", [BsubSubmissionError("no job id"), CommandError(255, "bsub")])
@pytest.mark.parametrize(("untracked", "expected"), [(False, "failed"), (True, "untracked")])
@pytest.mark.parametrize("step", sorted(_STEPS))
def test_rejected_submission_finishes_the_run_and_reraises(
    mock_ctx, tmp_path, step, untracked, expected, error
):
    module, run = _STEPS[step]
    ctx = _ctx(mock_ctx, tmp_path, untracked)

    with patch(f"{module}._submit_bsub", side_effect=error), pytest.raises(type(error)):
        run(ctx, tmp_path)

    history = ctx.tracker.history(step)
    assert len(history) == 2
    assert history[-1]["status"] == expected
    assert history[-1]["run_dir"] == history[0]["run_dir"]
