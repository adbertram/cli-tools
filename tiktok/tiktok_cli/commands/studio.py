"""Prepare, check, and inspect journaled Studio operations; publish or post only with --yes."""
from contextlib import closing
from pathlib import Path

import typer
from cli_tools_shared.output import command, print_json, print_table

from ..config import get_config
from ..studio import parse_response
from ..studio_publishing import StudioPublisher, StudioPublishError, validate_policy

MAX_POLICY_BYTES = 64 * 1024  # Fixed schema plus a 4000-character escaped caption.

app = typer.Typer(help="Prepare, check, publish, and reconcile owned Studio drafts", no_args_is_help=True)
COMMAND_CREDENTIALS = {"prepare": ["browser_session"], "publish": ["browser_session"], "post": ["browser_session"],
                       "reconcile": ["browser_session"], "status": ["no_auth"],
                       "inventory": ["browser_session"], "check": ["browser_session"],
                       "watch": ["browser_session"], "watch-batch": ["browser_session"]}


def _print_operation(result, table):
    if table:
        columns = ["request_id", "state", "draft_id", "item_id", "url"]
        print_table([result], columns, columns)
    else:
        print_json(result)


def _read_policy(policy):
    with policy.open("rb") as stream:
        payload = stream.read(MAX_POLICY_BYTES + 1)
    if len(payload) > MAX_POLICY_BYTES:
        raise StudioPublishError("Studio policy exceeds the 64 KiB input limit.")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        raise StudioPublishError("Studio policy must be UTF-8 JSON.") from None
    return validate_policy(parse_response(text))


def _require_yes(yes):
    if not yes:
        raise StudioPublishError("Refusing Studio public Post without --yes.")


def _publisher():
    """One StudioPublisher for one command, closed however the command ends."""
    return closing(StudioPublisher(get_config()))


@app.command("prepare")
@command
def studio_prepare(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Exact local MP4 to upload privately"),
    policy: Path = typer.Option(..., "--policy", exists=True, dir_okay=False, help="Explicit version 1 Studio policy JSON"),
    request_id: str = typer.Option(..., "--request-id", help="Canonical UUID binding this operation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Upload privately, verify disclosure controls, and retain the owned draft.

    Policy fields: schema_version=1, profile, account_id (string), username,
    caption, audience=Everyone, timing=now, disclosure=branded_content,
    music_rights_confirmed=true. Caption is used verbatim.
    """
    checked = _read_policy(policy)
    with _publisher() as publisher:
        result = publisher.prepare(file, checked, request_id)
    _print_operation(result, table)


@app.command("check")
@command
def studio_check(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Exact local MP4 to check before posting"),
    username: str = typer.Option(..., "--username", help="Exact session owner handle"),
    account_id: str = typer.Option(..., "--account-id", help="Exact numeric session owner ID"),
    timeout: int = typer.Option(900, "--timeout", min=30, max=900, help="Seconds to wait for Studio's checks"),
    table: bool = typer.Option(False, "--table", "-t", help="Display the verdict as table"),
):
    """Read Studio's own pre-post verdict for a file; never posts.

    Uploads the file as a private draft, waits for Studio's automatic Content
    check lite and music copyright check, returns their verdicts, and removes
    that draft. Each run uses one of the account's daily checks. `verdict` is
    `pass`, `restricted`, or null when Studio gave none; see `status`.
    """
    from ..studio_check import check
    with _publisher() as publisher:
        result = check(publisher, file, username=username, account_id=account_id, timeout=timeout)
    if table:
        row = {"status": result["status"], "verdict": result["verdict"],
               "issues": "; ".join(issue["text"] or f"code {issue['code']}" for issue in result["issues"]),
               "music": result["music_copyright"]["verdict"], "seconds": result["timings"]["content_check_seconds"]}
        print_table([row], list(row), list(row))
    else:
        print_json(result)


@app.command("publish")
@command
def studio_publish(
    request_id: str = typer.Argument(..., help="Prepared operation UUID"),
    yes: bool = typer.Option(False, "--yes", help="Explicitly authorize the single public Post action"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Reverify and publish one exact owned draft; never retry unknown outcomes."""
    _require_yes(yes)
    with _publisher() as publisher:
        result = publisher.publish(request_id, before_public_action=lambda _binding: _require_yes(yes))
    _print_operation(result, table)


@app.command("post")
@command
def studio_post(
    file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Exact local MP4 to upload and post"),
    policy: Path = typer.Option(..., "--policy", exists=True, dir_okay=False, help="Explicit version 1 Studio policy JSON"),
    request_id: str = typer.Option(..., "--request-id", help="Canonical UUID binding this operation"),
    yes: bool = typer.Option(False, "--yes", help="Explicitly authorize the single public Post action"),
    dispatch_deadline: float = typer.Option(None, "--dispatch-deadline", help="Epoch seconds after which Post must not dispatch"),
    refuse_if_exists: Path = typer.Option(None, "--refuse-if-exists", help="Abort before Post if this path exists at dispatch time"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Prepare and publish in one process so the owned editor stays open.

    Same policy and request rules as `prepare` and `publish`. A failed prepare
    is retried once on a fresh publisher (never when another operation owns
    the profile). Read `studio status <request-id>` for the journal on error.
    """
    _require_yes(yes)
    checked = _read_policy(policy)

    def authorize(_binding):
        if refuse_if_exists is not None and refuse_if_exists.exists():
            raise StudioPublishError(f"Refusing Studio public Post: {refuse_if_exists} exists.")
        return None if dispatch_deadline is None else {"dispatch_deadline": dispatch_deadline}

    publisher = StudioPublisher(get_config())
    try:
        try:
            prepared = publisher.prepare(file, checked, request_id)
        except Exception as exc:
            if "owns this profile" in str(exc):
                raise
            # A failed editor cannot recover its own draft; a fresh instance
            # recovers the journal-bound request.
            publisher.close()
            publisher = StudioPublisher(get_config())
            prepared = publisher.prepare(file, checked, request_id)
        if prepared["state"] != "prepared":
            raise StudioPublishError(f"Studio prepare ended in state {prepared['state']}; Post refused.")
        result = publisher.publish(request_id, before_public_action=authorize)
    finally:
        publisher.close()
    _print_operation(result, table)


@app.command("status")
@command
def studio_status(
    request_id: str = typer.Argument(..., help="Operation UUID to read locally"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Read the profile's operation journal without remote browser actions."""
    with _publisher() as publisher:
        result = publisher.status(request_id)
    _print_operation(result, table)


@app.command("reconcile")
@command
def studio_reconcile(
    request_id: str = typer.Argument(..., help="Operation UUID to reconcile through verified Studio"),
    table: bool = typer.Option(False, "--table", "-t", help="Display operation as table"),
):
    """Read exact receipt post ID in verified Studio; never guess by caption."""
    with _publisher() as publisher:
        result = publisher.reconcile(request_id)
    _print_operation(result, table)


def _read_inventory_input(path):
    """No blocking special files or symlink traversal for caller manifests."""
    import os
    import stat
    from ..client import ClientError
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_POLICY_BYTES:
            raise ClientError("Studio inventory input must be a regular file of at most 64 KiB.")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            data = stream.read(MAX_POLICY_BYTES + 1)
        if len(data) > MAX_POLICY_BYTES:
            raise ClientError("Studio inventory input exceeds 64 KiB.")
        return parse_response(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError):
        raise ClientError("Studio inventory input cannot be read as a bounded regular UTF-8 JSON file.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


@app.command("inventory")
@command
def studio_inventory(
    manifest: Path = typer.Argument(..., help="Regular JSON file containing 1-1000 unique string video IDs"),
    username: str = typer.Option(..., "--username", help="Exact session owner handle"),
    account_id: str = typer.Option(..., "--account-id", help="Exact numeric session owner ID"),
    continuation: Path = typer.Option(None, "--continuation", help="Prior result's continuation JSON file"),
    max_pages: int = typer.Option(20, "--max-pages", min=1, max=20, help="Page budget, including fresh head"),
    table: bool = typer.Option(False, "--table", "-t", help="Display freshly observed matched records as table"),
):
    """Read exact owned post IDs in one Studio scan; unresolved IDs stay unknown."""
    from ..client import get_web_client
    ids = _read_inventory_input(manifest)
    checkpoint = _read_inventory_input(continuation) if continuation is not None else None
    with closing(get_web_client()) as client:
        result = client.get_studio_videos(username, ids, expected_account_id=account_id,
                                         continuation=checkpoint, max_pages=max_pages)
    if table:
        columns = ["id", "url", "observed_at", "server_timestamp_ms"]
        print_table(result["records"], columns, columns)
    else:
        print_json(result)


@app.command("watch")
@command
def studio_watch(
    video_id: str = typer.Argument(..., help="Exact owned post ID"),
    username: str = typer.Option(..., "--username", help="Exact session owner handle"),
    account_id: str = typer.Option(..., "--account-id", help="Exact numeric session owner ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display watch metrics as table"),
):
    """Read watch time in seconds, completion fraction, and timed retention fractions.

    Read-only. Provider delays, processing, and absent measurements remain null.
    Uses one bounded insight request and verifies both post and account identity.
    """
    from ..client import TikTokWebClient
    with closing(TikTokWebClient(config=get_config())) as client:
        result = client.get_studio_watch_metrics(username, video_id, expected_account_id=account_id)
    if table:
        row = _watch_row(result)
        print_table([row], list(row), list(row))
    else:
        print_json(result)


def _watch_row(record):
    return {"id": record["id"], **{k: v for k, v in record["metrics"].items() if k != "retention"},
            "retention_points": len(record["metrics"]["retention"] or []), "unavailable": record["watch_metrics_error"]}


@app.command("watch-batch")
@command
def studio_watch_batch(
    manifest: Path = typer.Argument(..., help="Regular JSON file containing 1-1000 unique string post IDs"),
    username: str = typer.Option(..., "--username", help="Exact session owner handle"),
    account_id: str = typer.Option(..., "--account-id", help="Exact numeric session owner ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display one row per read post"),
):
    """Read watch metrics for many owned posts in one browser session.

    Same per-post read as `watch`, through one page, with the account identity
    verified once before and once after the batch. A post that fails lands in
    `errors` keyed by its ID; the rest still return in `records`.
    """
    from ..client import TikTokWebClient
    ids = _read_inventory_input(manifest)
    with closing(TikTokWebClient(config=get_config())) as client:
        result = client.get_studio_watch_metrics_many(username, ids, expected_account_id=account_id)
    if table:
        columns = ["id", "average_watch_time_seconds", "total_watch_time_seconds", "completion_rate",
                   "retention_points", "unavailable"]
        print_table([_watch_row(record) for record in result["records"]], columns, columns)
    else:
        print_json(result)
