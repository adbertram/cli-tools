"""Message publishing and subscription commands."""

from typing import Optional

import typer
from cli_tools_shared import apply_limit
from cli_tools_shared.output import command, print_json, print_table

from ..client import get_client
from .common import usage_error


app = typer.Typer(help="Publish and receive ntfy messages", no_args_is_help=True)


def _append(args: list[str], flag: str, value: Optional[str]) -> None:
    if value is not None:
        args.extend((flag, value))


def _message_args(topic: str, *, config: Optional[str], title: Optional[str], priority: Optional[str], tags: Optional[str], delay: Optional[str], click: Optional[str], icon: Optional[str], actions: Optional[str], attach: Optional[str], markdown: bool, template: Optional[str], filename: Optional[str], sequence_id: Optional[str], file: Optional[str], email: Optional[str], user: Optional[str], token: Optional[str], wait_pid: Optional[int], no_cache: bool, no_firebase: bool, quiet: bool) -> list[str]:
    if user and token:
        usage_error("Use either --user or --token, never both")
    args: list[str] = []
    for flag, value in (("--config", config), ("--title", title), ("--priority", priority), ("--tags", tags), ("--delay", delay), ("--click", click), ("--icon", icon), ("--actions", actions), ("--attach", attach), ("--template", template), ("--filename", filename), ("--sequence-id", sequence_id), ("--file", file), ("--email", email), ("--user", user), ("--token", token), ("--wait-pid", str(wait_pid) if wait_pid else None)):
        _append(args, flag, value)
    if markdown:
        args.append("--markdown")
    if no_cache:
        args.append("--no-cache")
    if no_firebase:
        args.append("--no-firebase")
    if quiet:
        args.append("--quiet")
    args.append(topic)
    return args


def _subscription_args(*, config: Optional[str], since: Optional[str], scheduled: bool, user: Optional[str], token: Optional[str]) -> list[str]:
    """Build shared poll/subscribe options after validating auth selection."""
    if user and token:
        usage_error("Use either --user or --token, never both")
    args: list[str] = []
    for flag, value in (("--config", config), ("--since", since), ("--user", user), ("--token", token)):
        _append(args, flag, value)
    if scheduled:
        args.append("--scheduled")
    return args


@app.command("publish", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@command
def publish(ctx: typer.Context, topic: str, body: Optional[str] = typer.Argument(None, help="Message body; sent to upstream stdin"), config: Optional[str] = typer.Option(None, "--config", "-c"), message: Optional[str] = typer.Option(None, "--message", "-m", help="Message body; sent to upstream stdin"), title: Optional[str] = typer.Option(None, "--title", "-t"), priority: Optional[str] = typer.Option(None, "--priority", "-p"), tags: Optional[str] = typer.Option(None, "--tags", "-T"), delay: Optional[str] = typer.Option(None, "--delay", "--at", "--in", "-D"), click: Optional[str] = typer.Option(None, "--click", "-U"), icon: Optional[str] = typer.Option(None, "--icon", "-i"), actions: Optional[str] = typer.Option(None, "--actions", "-A"), attach: Optional[str] = typer.Option(None, "--attach", "-a"), markdown: bool = typer.Option(False, "--markdown", "--md"), template: Optional[str] = typer.Option(None, "--template", "--tpl"), filename: Optional[str] = typer.Option(None, "--filename", "-n"), sequence_id: Optional[str] = typer.Option(None, "--sequence-id", "-S"), file: Optional[str] = typer.Option(None, "--file", "-f"), email: Optional[str] = typer.Option(None, "--email", "-e"), user: Optional[str] = typer.Option(None, "--user", "-u"), token: Optional[str] = typer.Option(None, "--token", "-k"), wait_pid: Optional[int] = typer.Option(None, "--wait-pid", "--pid"), wait_cmd: bool = typer.Option(False, "--wait-cmd", "--cmd", "--done"), no_cache: bool = typer.Option(False, "--no-cache", "-C"), no_firebase: bool = typer.Option(False, "--no-firebase", "-F"), quiet: bool = typer.Option(False, "--quiet", "-q"), table: bool = typer.Option(False, "--table")) -> None:
    """Publish a message with current upstream ntfy publish options."""
    if message is not None:
        if body is not None:
            usage_error("Use BODY or --message, never both")
        body = message
    upstream_args = _message_args(topic, config=config, title=title, priority=priority, tags=tags, delay=delay, click=click, icon=icon, actions=actions, attach=attach, markdown=markdown, template=template, filename=filename, sequence_id=sequence_id, file=file, email=email, user=user, token=token, wait_pid=wait_pid, no_cache=no_cache, no_firebase=no_firebase, quiet=quiet)
    if wait_cmd:
        if body is None:
            usage_error("--wait-cmd requires a command after TOPIC")
        upstream_args.insert(0, "--wait-cmd")
        upstream_args.extend((body, *ctx.args))
        body = None
    value = get_client().publish(upstream_args, body)
    if table:
        print_table([value], list(value), [key.replace("_", " ").title() for key in value])
    else:
        print_json(value)


@app.command("trigger")
@command
def trigger(topic: str) -> None:
    """Send ntfy's topic-only trigger message."""
    print_json(get_client().publish((topic,), None))


@app.command("poll")
@command
def poll(topic: str, config: Optional[str] = typer.Option(None, "--config", "-c"), since: Optional[str] = typer.Option(None, "--since", "-s"), scheduled: bool = typer.Option(False, "--scheduled", "-S"), user: Optional[str] = typer.Option(None, "--user", "-u"), token: Optional[str] = typer.Option(None, "--token", "-k"), limit: int = typer.Option(100, "--limit", "-l"), table: bool = typer.Option(False, "--table", "-t")) -> None:
    """Fetch cached messages and return a JSON array."""
    args = _subscription_args(config=config, since=since, scheduled=scheduled, user=user, token=token)
    rows = apply_limit(get_client().poll((*args, topic)), limit)
    if table:
        columns = ["id", "time", "topic", "title", "message", "priority"]
        print_table(rows, columns, [column.title() for column in columns])
    else:
        print_json(rows)


@app.command("subscribe")
@command
def subscribe(topic: str, config: Optional[str] = typer.Option(None, "--config", "-c"), since: Optional[str] = typer.Option(None, "--since", "-s"), scheduled: bool = typer.Option(False, "--scheduled", "-S"), user: Optional[str] = typer.Option(None, "--user", "-u"), token: Optional[str] = typer.Option(None, "--token", "-k")) -> None:
    """Stream upstream NDJSON without buffering or normalization."""
    args = ["subscribe", *_subscription_args(config=config, since=since, scheduled=scheduled, user=user, token=token)]
    raise typer.Exit(get_client().passthrough([*args, topic]))


@app.command("subscribe-config")
@command
def subscribe_config(config: Optional[str] = typer.Option(None, "--config", "-c")) -> None:
    """Run subscriptions defined in upstream client configuration."""
    args = ["subscribe", "--from-config"]
    _append(args, "--config", config)
    raise typer.Exit(get_client().passthrough(args))
