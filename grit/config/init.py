"""Generates the default ~/.grit_curation_config.yaml for a new user."""

from importlib import resources
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".grit" / "grit_curation_config.yaml"


def render_config(username: str) -> str:
    """Return the Sanger config template with the username filled in."""
    template = resources.files("grit.config").joinpath("sanger_template.yaml").read_text()
    return template.format(username=username)


def write_default_config(username: str, config_path: Path = DEFAULT_CONFIG_PATH) -> bool:
    """Write the default config to config_path unless it already exists.

    Returns True if the file was written, False if it already existed.
    """
    if config_path.exists():
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(render_config(username))
    return True
