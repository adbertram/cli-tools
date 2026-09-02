"""The site registry: `config.json` in the MicroWorker project.

Every site entry must carry exactly `cli` (str|null), `account` (bool),
`lastpass_item` (str|null) and `auth_command` (str|null). A missing key, an
unexpected key or a wrong type is a `ConfigError`; nothing is defaulted.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from cli_tools_shared.exceptions import ConfigError

from . import paths


@dataclass(frozen=True)
class SiteConfig:
    name: str
    cli: str | None
    account: bool
    lastpass_item: str | None
    auth_command: str | None


# key -> accepted Python types
SITE_KEYS = {
    "cli": (str, type(None)),
    "account": (bool,),
    "lastpass_item": (str, type(None)),
    "auth_command": (str, type(None)),
}


def load_sites() -> dict[str, SiteConfig]:
    """Every site in config.json, keyed by name, in file order."""
    path = paths.config_path()
    if not path.is_file():
        raise ConfigError(f"config.json not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "sites" not in data:
        raise ConfigError(f"{path} must be an object with a top-level 'sites' key")
    entries = data["sites"]
    if not isinstance(entries, dict) or not entries:
        raise ConfigError(f"{path}: 'sites' must be a non-empty object keyed by site name")
    return {name: _site_config(path, name, entry) for name, entry in entries.items()}


def get_site(name: str) -> SiteConfig:
    sites = load_sites()
    if name not in sites:
        raise ConfigError(
            f"unknown site '{name}'; config.json defines: {', '.join(sites)}")
    return sites[name]


def site_row(site: SiteConfig) -> dict:
    """The `sites list` / `sites get` record."""
    return asdict(site)


def _site_config(path, name: str, entry) -> SiteConfig:
    if not isinstance(entry, dict):
        raise ConfigError(f"{path}: site '{name}' must be an object")
    missing = [key for key in SITE_KEYS if key not in entry]
    if missing:
        raise ConfigError(
            f"{path}: site '{name}' is missing keys: {', '.join(missing)}")
    unexpected = sorted(set(entry) - set(SITE_KEYS))
    if unexpected:
        raise ConfigError(
            f"{path}: site '{name}' has unexpected keys: {', '.join(unexpected)}")
    for key, types in SITE_KEYS.items():
        if not isinstance(entry[key], types):
            raise ConfigError(
                f"{path}: site '{name}' key '{key}' must be "
                f"{' or '.join(t.__name__ for t in types)}, "
                f"got {type(entry[key]).__name__}")
    return SiteConfig(name=name, **entry)
