"""The site registry: `config.json` in the MicroWorker project.

Every site entry must carry exactly `cli` (str|null), `account` (bool),
`lastpass_item` (str|null), `auth_command` (str|null) and `disabled` (bool).
A missing key, an unexpected key or a wrong type is a `ConfigError`; nothing
is defaulted.

`disabled: true` is the deterministic off-switch for a site's worker. Discovery
runs skip disabled sites entirely: `discover` refuses them (exit 2, no
envelope), `merge` neither expects nor accepts their envelopes, and the
discovery agent fetches the roster with `--filter disabled:eq:false` so it
never spawns their workers. Re-enabling is editing config.json back to
`disabled: false` -- no agent, skill or code change.

A config.json that is not parseable JSON is a `ConfigError` too, naming the path
and the decode position. Left unwrapped, the `json.JSONDecodeError` escapes the
CLI's contract-error handler and exits 1 with a message that names no file at
all -- and the discovery agent's recovery branch keys on exit 2 meaning "your
inputs are wrong", so a truncated config would read to it as an internal crash.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from cli_tools_shared.exceptions import ConfigError

from . import jsonio, paths


@dataclass(frozen=True)
class SiteConfig:
    name: str
    cli: str | None
    account: bool
    lastpass_item: str | None
    auth_command: str | None
    disabled: bool


# key -> accepted Python types
SITE_KEYS = {
    "cli": (str, type(None)),
    "account": (bool,),
    "lastpass_item": (str, type(None)),
    "auth_command": (str, type(None)),
    "disabled": (bool,),
}


def load_sites() -> dict[str, SiteConfig]:
    """Every site in config.json, keyed by name, in file order."""
    path = paths.config_path()
    if not path.is_file():
        raise ConfigError(f"config.json not found at {path}")
    try:
        data = jsonio.read_file(path)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"{path} is not valid JSON: {exc.msg} "
            f"(line {exc.lineno}, column {exc.colno})") from exc
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
