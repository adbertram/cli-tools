"""Data-driven market presets: a preset name maps to a Kalshi series ticker."""

import json
from functools import lru_cache
from importlib import resources
from typing import Optional

from cli_tools_shared.exceptions import ClientError


@lru_cache(maxsize=1)
def load_presets() -> dict:
    """Return the preset registry from presets.json (name -> preset fields)."""
    return json.loads(resources.files("kalshi_cli").joinpath("presets.json").read_text(encoding="utf-8"))


def resolve_series(name_or_series: str) -> tuple[str, Optional[dict]]:
    """Resolve a preset name or a raw series ticker to (series_ticker, preset_or_None)."""
    presets = load_presets()
    key = name_or_series.strip().lower()
    if key in presets:
        preset = presets[key]
        return preset["series_ticker"], preset
    for preset in presets.values():
        if preset["series_ticker"].lower() == key:
            return preset["series_ticker"], preset
    ticker = name_or_series.strip().upper()
    if not ticker:
        raise ClientError("A preset name or series ticker is required.")
    return ticker, None
