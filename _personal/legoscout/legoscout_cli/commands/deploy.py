"""`legoscout deploy` -- sync the ledger and code to adam-server.

`pull-db` and `push` bookend a run (see `legoscout-orchestrator`): pull the
adam-server ledger down before a run touches anything, push the local
working copy plus a code deploy back up after it finishes. `status` and
`rollback` are manual, ad hoc recovery tools.
"""
from __future__ import annotations

import typer
from cli_tools_shared.output import command, print_json

from ..deploy import db_sync, release

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(help="Sync the ledger and app code to adam-server", no_args_is_help=True)


@app.command("pull-db")
@command
def pull_db():
    """Snapshot adam-server's shared ledger down to the local working copy."""
    db_sync.pull()
    print_json({"ok": True})


@app.command("push")
@command
def push():
    """Push the local ledger to adam-server, then deploy code if it changed."""
    db_sync.push()
    result = release.deploy_code()
    print_json(
        {
            "ok": True,
            "db_pushed": True,
            "code_deployed": not result.skipped,
            "release_name": result.release_name,
        }
    )


@app.command("status")
@command
def status():
    """Whether adam-server's code is in sync, release list, pm2 status."""
    print_json(release.status())


@app.command("rollback")
@command
def rollback(
    target: str = typer.Argument(
        "1", help="Releases to go back (a number) or an explicit release directory name"
    ),
):
    """Roll adam-server back to an earlier release and restart it."""
    target_name = release.rollback(target)
    print_json({"ok": True, "release_name": target_name})
