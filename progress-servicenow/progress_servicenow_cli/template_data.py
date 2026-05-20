"""Packaged ticket template data."""

import json
from importlib.resources import files


def load_ticket_template() -> dict:
    """Load the packaged ServiceNow ticket template."""
    resource = files("progress_servicenow_cli").joinpath("ticket_template.json")
    with resource.open("r", encoding="utf-8") as handle:
        return json.load(handle)
