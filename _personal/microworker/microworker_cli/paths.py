"""Every path this tool reads or writes. Nothing else hardcodes one.

The project root is `$MICROWORKER_ROOT` when set (tests point it at a temp
directory) and the real MicroWorker project otherwise. Per-run site envelopes
land under `agent_workspaces/discovery/<run_id>/` and are disposable; the
durable store is the SQLite database at `data/tasks.db`.

A run id and a site name are both operands this tool accepts from an agent and
then interpolates straight into a filesystem path, so both are constrained here
and nowhere else:

  run id     `^[0-9]{8}T[0-9]{6}Z$` -- the exact shape the documented
             `date -u +%Y%m%dT%H%M%SZ` produces, and the shape `runs list`
             sorts as a timestamp.
  site name  `^[a-z0-9][a-z0-9-]*$` -- one lowercase path segment.

Neither pattern can contain a separator or a `..`, so neither can walk out of
the project. Because a validated-shape check is easy to widen later by accident,
every constructed path is also asserted to resolve inside `project_root()`: a
run directory or envelope outside the project is a `ClientError`, not a write.
Without that, a site named `../../../../tmp/evil` writes its envelope wherever
it likes, and `merge ../../../../tmp/mwtrav` reads envelopes from an arbitrary
directory and stores the traversal string as a `runs.run_id`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from cli_tools_shared.exceptions import ClientError

DEFAULT_ROOT = Path("/Users/adam/Dropbox/GitRepos/Agents/MicroWorker")
ROOT_ENV = "MICROWORKER_ROOT"

RUN_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
SITE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def project_root() -> Path:
    if ROOT_ENV in os.environ:
        return Path(os.environ[ROOT_ENV])
    return DEFAULT_ROOT


def config_path() -> Path:
    return project_root() / "config.json"


def run_dir(run_id: str) -> Path:
    return _under_root(
        project_root() / "agent_workspaces" / "discovery" / check_run_id(run_id))


def envelope_path(run_id: str, site: str) -> Path:
    return _under_root(run_dir(run_id) / f"{check_site(site)}.json")


def db_path() -> Path:
    return project_root() / "data" / "tasks.db"


def board_path() -> Path:
    """The board store: `data/board.db`, beside the ledger but a separate file.

    The ledger's only writer is `merge` on the discovery machine; the board's
    only writer is the board service on adam-server. Two files, one writer
    each, so the two never contend for one SQLite file.
    """
    return project_root() / "data" / "board.db"


def delegation_log_dir() -> Path:
    """Where each delegation's agent output lands: `data/delegation_logs/`."""
    return project_root() / "data" / "delegation_logs"


def check_run_id(run_id: str) -> str:
    """The run id, or a `ClientError` naming the shape it has to have."""
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        raise ClientError(
            f"invalid run id {run_id!r}: a run id is a UTC timestamp of the form "
            "20260902T140000Z, as produced by `date -u +%Y%m%dT%H%M%SZ`")
    return run_id


def check_site(site: str) -> str:
    """The site name, or a `ClientError`; it becomes one path segment."""
    if not isinstance(site, str) or not SITE_RE.match(site):
        raise ClientError(
            f"invalid site name {site!r}: a site name is lowercase letters, "
            "digits and hyphens, starting with a letter or digit")
    return site


def _under_root(path: Path) -> Path:
    """The path itself once it is proven to resolve inside the project root."""
    root = project_root().resolve()
    if not path.resolve().is_relative_to(root):
        raise ClientError(
            f"{path} resolves outside the MicroWorker project root {root}")
    return path
