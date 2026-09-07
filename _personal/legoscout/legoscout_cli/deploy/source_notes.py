"""Append run learnings to the authoritative source registry over SSH."""
from __future__ import annotations

import json
import shlex
from datetime import datetime, timezone

from . import config, ssh


def add(source: str, text: str, date: str | None = None) -> dict:
    """Keep run baselines immutable and send note content through stdin."""
    when = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {"source": source, "text": text, "date": when}
    program = (
        "import json, sys; from legoscout_cli.sources import registry; "
        "note = json.load(sys.stdin); "
        "print(json.dumps(registry.sources.append_note("
        "note['source'], note['text'], note['date'])))"
    )
    remote = shlex.join([
        "env", "LEGOSCOUT_DB_PATH=" + config.REMOTE_SHARED_DB,
        config.REMOTE_TOOL_PYTHON, "-c", program,
    ])
    result = json.loads(ssh.run_local(
        ["ssh", config.REMOTE_HOST, remote], input=json.dumps(payload)))
    if (not isinstance(result, dict)
            or set(result) != {"id", "date", "text", "supersedes"}
            or not isinstance(result["id"], str) or not result["id"]
            or result["date"] != when or result["text"] != text
            or result["supersedes"] is not None):
        raise ValueError("server returned an invalid source-note receipt")
    return result
