"""Tests for grit/__init__.py's backward-compatibility re-exports (ARCH-20)."""

import grit


def test_grit_package_does_not_reexport_private_helpers():
    """Private helpers must not leak into the public `grit.` surface — a rename
    in helpers.py would otherwise silently be a breaking change to unenumerated
    importers who never should have relied on a private name in the first place."""
    for name in ("_run", "_submit_bsub", "_clean_species_name", "_find_pretext_map_in_workdir"):
        assert not hasattr(grit, name), f"grit.{name} should not be publicly re-exported"


def test_grit_package_still_exports_its_intended_public_surface():
    """The genuinely public re-exports must still work after removing the private ones."""
    for name in (
        "cli",
        "CurationContext",
        "build_bsub_opts",
        "module_cmd",
        "console",
        "print_done",
        "print_next_step",
        "print_step_header",
    ):
        assert hasattr(grit, name), f"grit.{name} should still be re-exported"
