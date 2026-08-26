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
    """Pull adam-server's shared ledger and crops into the local workspace."""
    report = db_sync.pull()
    print_json(report)
    if not report["ok"]:
        raise typer.Exit(1)


@app.command("push")
@command
def push():
    """Push the local ledger/crops, then deploy code if sync succeeded."""
    sync = db_sync.push()
    if not sync["ok"]:
        print_json({"ok": False, "sync": sync, "code_deployed": False})
        raise typer.Exit(1)
    try:
        result = release.deploy_code()
    except Exception as exc:
        # The sync legs already succeeded; their outcomes stay visible so a
        # code-deploy failure never hides completed work.
        print_json(
            {
                "ok": False,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "sync": sync,
                "code_deployed": False,
            }
        )
        raise typer.Exit(1) from exc
    print_json(
        {
            "ok": True,
            "sync": sync,
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
