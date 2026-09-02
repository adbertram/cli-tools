"""Every path this tool reads or writes. Nothing else hardcodes one.

The project root is `$MICROWORKER_ROOT` when set (tests point it at a temp
directory) and the real MicroWorker project otherwise. Per-run site envelopes
land under `agent_workspaces/discovery/<run_id>/` and are disposable; the
durable store is the SQLite database at `data/tasks.db`.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ROOT = Path("/Users/adam/Dropbox/GitRepos/Agents/MicroWorker")
ROOT_ENV = "MICROWORKER_ROOT"


def project_root() -> Path:
    if ROOT_ENV in os.environ:
        return Path(os.environ[ROOT_ENV])
    return DEFAULT_ROOT


def config_path() -> Path:
    return project_root() / "config.json"


def run_dir(run_id: str) -> Path:
    return project_root() / "agent_workspaces" / "discovery" / run_id


def envelope_path(run_id: str, site: str) -> Path:
    return run_dir(run_id) / f"{site}.json"


def db_path() -> Path:
    return project_root() / "data" / "tasks.db"
