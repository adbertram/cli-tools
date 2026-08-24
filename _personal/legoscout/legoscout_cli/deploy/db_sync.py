"""Sync `found_deals.db` between the local run's working copy and
adam-server's persistent copy.

`ledger_db.connect()` runs the database in WAL mode, so a raw file copy of
`found_deals.db` alone can miss committed pages still sitting in the
`-wal` file. Both directions go through SQLite's own online-backup command
(`sqlite3 <path> ".backup <dest>"`) instead, which snapshots a live,
WAL-mode database into one consistent plain file.

Adam's Reject/Inquired/Bid/favorite clicks on the deployed page write
directly to adam-server's copy. `pull()` must run before a run reads or
writes anything, so the run's "preserve the existing status" logic sees the
latest truth instead of clobbering a remote click on push. See the
`legoscout-orchestrator` skill for where `pull()`/`push()` bookend a run.
"""
from __future__ import annotations

import os
import shlex
import tempfile

from . import config
from .ssh import run_local, run_remote_script


def pull() -> None:
    """Snapshot adam-server's shared ledger down to the local working copy."""
    remote_tmp = "/tmp/legoscout-pull-%d.db" % os.getpid()
    run_remote_script(
        "set -euo pipefail\n"
        "sqlite3 %s '.backup %s'\n"
        % (shlex.quote(config.REMOTE_SHARED_DB), shlex.quote(remote_tmp))
    )
    try:
        run_local(["scp", "-q", "%s:%s" % (config.REMOTE_HOST, remote_tmp), config.LOCAL_DB])
    finally:
        run_remote_script("rm -f %s\n" % shlex.quote(remote_tmp))


def push() -> None:
    """Snapshot the local working copy up to adam-server's shared ledger."""
    with tempfile.TemporaryDirectory() as tmp:
        local_snapshot = os.path.join(tmp, "found_deals.db")
        run_local(["sqlite3", config.LOCAL_DB, ".backup %s" % local_snapshot])
        remote_tmp = "/tmp/legoscout-push-%d.db" % os.getpid()
        run_local(["scp", "-q", local_snapshot, "%s:%s" % (config.REMOTE_HOST, remote_tmp)])
    # `mv` on the same filesystem is atomic -- the running server never sees a
    # half-written file mid-copy.
    run_remote_script(
        "set -euo pipefail\n"
        "mkdir -p %s\n"
        "mv %s %s\n"
        % (
            shlex.quote(config.REMOTE_SHARED_DIR),
            shlex.quote(remote_tmp),
            shlex.quote(config.REMOTE_SHARED_DB),
        )
    )
