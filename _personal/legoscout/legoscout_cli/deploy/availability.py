"""Run availability verification where the authoritative ledger is stored."""
from __future__ import annotations

import json

from . import config, ssh


def expire() -> dict:
    result = json.loads(ssh.run_remote([
        "env", "LEGOSCOUT_DB_PATH=" + config.REMOTE_SHARED_DB,
        config.REMOTE_TOOL_PYTHON, "-m", __name__, "--apply",
    ]))
    if not isinstance(result, dict):
        raise ValueError("remote availability sweep must return a JSON object")
    return result


if __name__ == "__main__":
    from .. import paths
    from ..invalidate import sweep

    if paths.DB_PATH != config.REMOTE_SHARED_DB:
        raise ValueError("availability deployment command requires the authoritative server ledger")
    raise SystemExit(sweep.main())
