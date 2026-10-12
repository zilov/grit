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


COMPLETION_SNIPPET = (
    "# grit tab completion\n"
    'command -v grit >/dev/null && eval "$(_GRIT_COMPLETE=bash_source grit)"\n'
)


def enable_completion(bashrc: Path | None = None) -> bool:
    """Append the completion snippet to ~/.bashrc unless present; True if it was added."""
    bashrc = bashrc or Path.home() / ".bashrc"
    text = bashrc.read_text() if bashrc.exists() else ""
    if "_GRIT_COMPLETE=bash_source grit" in text:
        return False
    with bashrc.open("a") as f:
        f.write(("\n" if text and not text.endswith("\n") else "") + COMPLETION_SNIPPET)
    return True
