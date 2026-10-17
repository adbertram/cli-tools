"""Packaged ticket template data."""

import json
from importlib.resources import files
from pathlib import Path

TEMPLATE_FILENAME = "ticket_template.json"


def template_path() -> Path:
    """Return the on-disk path of the packaged ticket template registry."""
    return Path(str(files("progress_servicenow_cli").joinpath(TEMPLATE_FILENAME)))


def load_ticket_template() -> dict:
    """Load the packaged ticket template registry."""
    resource = files("progress_servicenow_cli").joinpath(TEMPLATE_FILENAME)
    with resource.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_ticket_template(data: dict) -> Path:
    """Write the ticket template registry back to the packaged location."""
    path = template_path()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
