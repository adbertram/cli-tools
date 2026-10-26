"""Captured sessions, cloud reads, and explicit experimental start/pause."""
import json
from pathlib import Path
import subprocess

import typer
from cli_tools_shared.output import print_json, print_error, command

from ..client import ClientError
from ..cloud import ROUTES, ROBOT_RESOURCES, TARGETED_RESOURCES, read_resource, validate_credentials, validate_template
from ..config import get_config
from ..cloud_session import secret, session_path, save_session, load_session


# Cloud commands validate their separate keychain session themselves; the legacy
# custom credential verifier checks LAN robots and must not gate cloud access.
COMMAND_CREDENTIALS = {"import-capture": ["no_auth"], "read": ["no_auth"], "select": ["no_auth"], "robots": ["no_auth"], "favorites": ["no_auth"], "shadow": ["no_auth"], "status": ["no_auth"], "schedules": ["no_auth"], "refresh": ["no_auth"], "auth-status": ["no_auth"], "start": ["no_auth"], "pause": ["no_auth"], "list": ["no_auth"], "get": ["no_auth"]}

SHADOW_RESOURCES = {"robot-settings": "rw-settings", "config": "ro-configinfo", "stats": "ro-stats", "software": "rw-software"}

app = typer.Typer(help="Cloud reads and explicit start/pause using an authorized app session")


def import_capture(config, path, robot=None, additional_paths=None):
    try:
        result = subprocess.run(["uv", "tool", "run", "--python", "3.13", "--from", "mitmproxy==12.2.3", "python", str(Path(__file__).resolve().parents[1] / "capture_session.py"), str(path), *[str(extra) for extra in (additional_paths or [])]], capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise ClientError("Capture decoding failed; no cloud session imported")
        captured = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ClientError("Capture decoder unavailable or invalid capture") from None
    if not isinstance(captured, dict) or not isinstance(captured.get("requests"), list):
        raise ClientError("Capture decoder returned an invalid session shape")
    credentials = captured.get("credentials")
    from ..cloud_auth import expiry_timestamp
    if not isinstance(credentials, dict) or any(not isinstance(credentials.get(key), str) or not credentials[key] for key in ("AccessKeyId", "SecretKey", "SessionToken", "Expiration")) or expiry_timestamp(credentials) is None:
        raise ClientError("Capture contains invalid cloud credentials")
    robots = captured.get("robots")
    if not isinstance(robots, list) or not robots or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"] for r in robots):
        raise ClientError("Capture contains no valid cloud robot inventory")
    templates = {}
    shared = {}
    for item in captured["requests"]:
        if not isinstance(item, dict) or item.get("region") != "us-east-1":
            continue
        for kind in ROUTES:
            for entry in robots:
                try:
                    validate_template(kind, item, entry["id"])
                except ClientError:
                    continue
                if kind in TARGETED_RESOURCES:
                    templates.setdefault(entry["id"], {})[kind] = item
                else:
                    shared[kind] = item
                    break
    if not templates and not shared:
        raise ClientError("Capture contains no supported reads for its cloud robots")
    prior = load_session(config) if session_path(config).exists() else {}
    initial = {"robots": robots, "default_robot_id": prior.get("default_robot_id")}
    default = resolve_robot(config, initial, robot, require=False)
    # Temporary AWS/MQTT tokens and the verified reusable Gigya session are
    # secret-managed. Passwords and captured login proofs are never retained.
    from ..cloud_mqtt import validate_connection_token
    tokens = captured.get("connection_tokens", [])
    if tokens:
        for token in tokens:
            validate_connection_token(token, now=0)
        credentials = dict(credentials, connection_tokens=tokens)
    deployments = captured.get("deployments", {})
    if not isinstance(deployments, dict):
        raise ClientError("Capture contains invalid cloud deployment routing")
    metadata = {"robots": robots, "templates": templates, "shared": shared, "default_robot_id": default, "deployments": deployments}
    from ..cloud_auth import prepare_refresh_material, credentials_due, renew_credentials, profile_lock
    if captured.get("refresh_material") is not None:
        identity = captured.get("account_identity")
        if not isinstance(identity, str) or not identity:
            raise ClientError("Captured refresh session has no verified cloud account identity")
        material = prepare_refresh_material(captured["refresh_material"])
        credentials = dict(credentials, account_identity=identity, refresh_material=material)
    with profile_lock(config, "mqtt"), profile_lock(config, "refresh"):
        if credentials.get("refresh_material") and credentials_due(credentials, metadata):
            credentials = renew_credentials(credentials, metadata)
        validate_credentials(credentials)
        for token in credentials.get("connection_tokens", []):
            validate_connection_token(token)
        secret(config, "set", credentials)
        save_session(config, metadata)
    return {"imported": True, "robot_count": len(robots), "resources": sorted(set(shared) | {kind for resources in templates.values() for kind in resources}), "expires_at": credentials["Expiration"], "automatic_refresh_configured": bool(credentials.get("refresh_material")), "device_status": "not_observed"}


def resolve_robot(config, data, selector=None, require=True):
    robots = data["robots"]
    if selector:
        matches = [r for r in robots if selector in (r["id"], r.get("name"))]
        if len(matches) != 1:
            raise ClientError("Cloud robot selection is missing or ambiguous; use its exact ID")
        return matches[0]["id"]
    default = data.get("default_robot_id")
    if default and any(r["id"] == default for r in robots):
        return default
    local_name = config.get_default_robot()
    local = config.get_robot(local_name) if local_name else None
    if local and any(r["id"] == local.get("blid") for r in robots):
        return local["blid"]
    if len(robots) == 1:
        return robots[0]["id"]
    if require:
        raise ClientError("Multiple cloud robots; specify --robot or use cloud select")
    return None


def run_read(config, resource, timeout, robot=None):
    data = load_session(config)
    robot_id = resolve_robot(config, data, robot)
    if resource in SHADOW_RESOURCES:
        from ..cloud_mqtt import get_shadow
        robot_data = next(entry for entry in data["robots"] if entry["id"] == robot_id)
        if robot_data.get("sku") != "c975020":
            raise ClientError("This named shadow resource is only verified for the Combo j9+")
        from ..cloud_auth import authenticated_read
        return authenticated_read(config, lambda credentials: get_shadow(data, credentials, robot_id, timeout, SHADOW_RESOURCES[resource]), mqtt=True)
    templates = data.get("templates", {}).get(robot_id, {})
    template = templates.get(resource) if resource in TARGETED_RESOURCES else data.get("shared", {}).get(resource)
    if not template:
        raise ClientError("This resource was not captured for the selected cloud robot")
    from ..cloud_auth import authenticated_read
    result = authenticated_read(config, lambda credentials: read_resource(resource, template, credentials, template["region"], robot_id, timeout))
    result["robot_id"] = robot_id if resource in ROBOT_RESOURCES else None
    result["scope"] = "household" if resource == "schedule" else "robot" if resource in ROBOT_RESOURCES else "account"
    return result


@app.command("import-capture")
@command
def cloud_import_capture(
    path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, readable=True, help="Private mitmproxy .flows capture containing successful login and reads"),
    additional_capture: list[Path] | None = typer.Option(None, "--additional-capture", exists=True, file_okay=True, dir_okay=False, readable=True, help="Additional private capture to merge; exact login access key must match"),
    robot: str | None = typer.Option(None, "--robot", help="Cloud robot name or ID to use as default; preserves every robot"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
):
    """Import a verified app session and observed reads; renew expired tokens if session proof exists."""
    try:
        print_json(import_capture(get_config(profile=profile), path, robot, additional_capture))
    except ClientError as error:
        print_error(str(error)); raise typer.Exit(1)


@app.command("read")
@command
def cloud_read(
    resource: str = typer.Argument(..., help="Captured resource name; see cloud robots list resources and README"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    timeout: float = typer.Option(15, "--timeout", min=1, max=60, help="Response timeout in seconds"),
    robot: str | None = typer.Option(None, "--robot", help="Cloud robot name or ID"),
):
    """Make one signed GET for an evidenced resource. Cloud data is not live robot telemetry."""
    try:
        print_json(run_read(get_config(profile=profile), resource, timeout, robot))
    except ClientError as error:
        print_error(str(error)); raise typer.Exit(1)


robots_app = typer.Typer(help="Inspect captured cloud inventory")
app.add_typer(robots_app, name="robots")


@robots_app.command("list")
@command
def cloud_robots_list(
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum robots"),
    filter: list[str] | None = typer.Option(None, "--filter", "-f", help="Filter field:operator:value"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List cloud robots from the imported login, without inventing LAN configuration."""
    from cli_tools_shared.filters import apply_filters, apply_properties_filter, FilterValidationError
    from cli_tools_shared.output import print_table
    try:
        config = get_config(profile=profile)
        data = load_session(config)
        default = resolve_robot(config, data, require=False)
        rows = [dict(robot, selected=robot["id"] == default, resources=sorted(data.get("templates", {}).get(robot["id"], {}))) for robot in data["robots"]]
        rows = apply_properties_filter(apply_filters(rows, filter, allowed_fields=["id", "name", "sku", "software_version", "selected", "resources"])[:limit], properties)
        print_table(rows) if table else print_json(rows)
    except (ClientError, FilterValidationError) as error:
        print_error(str(error)); raise typer.Exit(1)


@app.command("select")
@command
def cloud_select(
    robot: str = typer.Argument(..., help="Cloud robot name or exact ID"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
):
    """Select the default cloud robot locally; does not change the robot or LAN configuration."""
    try:
        config = get_config(profile=profile)
        data = load_session(config)
        data["default_robot_id"] = resolve_robot(config, data, robot)
        save_session(config, data)
        print_json({"selected": True})
    except ClientError as error:
        print_error(str(error)); raise typer.Exit(1)


@robots_app.command("get")
@command
def cloud_robot_get(
    robot: str = typer.Argument(..., help="Cloud robot name or exact ID"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get one robot from the imported cloud inventory without contacting the device."""
    from cli_tools_shared.output import print_table
    config = get_config(profile=profile)
    data = load_session(config)
    selected = resolve_robot(config, data, robot)
    row = next(entry for entry in data["robots"] if entry["id"] == selected)
    row = dict(row, selected=resolve_robot(config, data, require=False) == selected, resources=sorted(data.get("templates", {}).get(selected, {})))
    print_table([row]) if table else print_json(row)


favorites_app = typer.Typer(help="Read favorites for the selected cloud robot")
app.add_typer(favorites_app, name="favorites")


def robot_favorites(config, robot=None, timeout=15):
    data = load_session(config)
    robot_id = resolve_robot(config, data, robot)
    result = run_read(config, "favorites", timeout, robot_id)
    if not isinstance(result["data"], list):
        raise ClientError("Cloud favorites returned an unsupported JSON shape")
    favorites = []
    for favorite in result["data"]:
        if not isinstance(favorite, dict) or not isinstance(favorite.get("commanddefs"), list):
            raise ClientError("Cloud favorite is missing its command definitions")
        commands = favorite["commanddefs"]
        if any(not isinstance(command, dict) or not isinstance(command.get("robot_id"), str) for command in commands):
            raise ClientError("Cloud favorite has invalid robot bindings")
        if any(command["robot_id"] == robot_id for command in commands):
            if not isinstance(favorite.get("favorite_id"), str) or not favorite["favorite_id"]:
                raise ClientError("Cloud favorite is missing its ID")
            favorites.append(favorite)
    return robot_id, favorites


def find_favorite(config, favorite_id, robot=None, timeout=15):
    robot_id, favorites = robot_favorites(config, robot, timeout)
    matches = [favorite for favorite in favorites if favorite["favorite_id"] == favorite_id]
    if len(matches) != 1:
        raise ClientError("Favorite was not found unambiguously for the selected cloud robot")
    return robot_id, matches[0]


@favorites_app.command("list")
@command
def cloud_favorites_list(
    robot: str | None = typer.Option(None, "--robot", help="Cloud robot name or exact ID"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum favorites"),
    filter: list[str] | None = typer.Option(None, "--filter", "-f", help="Filter field:operator:value"),
    properties: str | None = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
    timeout: float = typer.Option(15, "--timeout", min=1, max=60, help="Response timeout in seconds"),
):
    """List live favorites bound to this robot, including disabled/deleted flags."""
    from cli_tools_shared.filters import apply_filters, apply_properties_filter
    from cli_tools_shared.output import print_table
    robot_id, favorites = robot_favorites(get_config(profile=profile), robot, timeout)
    rows = [{"id": favorite["favorite_id"], "name": favorite.get("name"), "robot_id": robot_id,
             "cloud_capable": favorite.get("cloud_capable"), "deleted": favorite.get("deleted"),
             "hidden": favorite.get("hidden"), "command_count": sum(c["robot_id"] == robot_id for c in favorite["commanddefs"]),
             "multiple_robots": len({c["robot_id"] for c in favorite["commanddefs"]}) > 1} for favorite in favorites]
    fields = ["id", "name", "robot_id", "cloud_capable", "deleted", "hidden", "command_count", "multiple_robots"]
    rows = apply_properties_filter(apply_filters(rows, filter, allowed_fields=fields)[:limit], properties)
    print_table(rows) if table else print_json(rows)


@favorites_app.command("get")
@command
def cloud_favorite_get(
    favorite_id: str = typer.Argument(..., help="Exact cloud favorite ID"),
    robot: str | None = typer.Option(None, "--robot", help="Cloud robot name or exact ID"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    timeout: float = typer.Option(15, "--timeout", min=1, max=60, help="Response timeout in seconds"),
):
    """Get the actual live favorite payload after validating selected-robot membership."""
    from cli_tools_shared.output import print_table
    robot_id, favorite = find_favorite(get_config(profile=profile), favorite_id, robot, timeout)
    result = {"source": "live_cloud", "robot_id": robot_id, "favorite": favorite}
    print_table([result]) if table else print_json(result)


@app.command("shadow")
@command
def cloud_shadow(
    robot: str | None = typer.Option(None, "--robot", help="Cloud robot name or exact ID"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    partition: str | None = typer.Option(None, "--partition", help="Combo read probe: ro-currentstate or rw-constatus; omitted for Classic"),
    timeout: float = typer.Option(15, "--timeout", min=1, max=60, help="Total MQTT operation deadline in seconds"),
):
    """Read the selected robot's Classic AWS shadow once; cloud state can be stale."""
    from ..cloud_mqtt import get_shadow
    config = get_config(profile=profile)
    data = load_session(config)
    robot_id = resolve_robot(config, data, robot)
    from ..cloud_auth import authenticated_read
    print_json(authenticated_read(config, lambda credentials: get_shadow(data, credentials, robot_id, timeout, partition), mqtt=True))


@app.command("status")
@command
def cloud_status(
    robot: str | None = typer.Option(None, "--robot", help="Cloud robot name or exact ID"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    timeout: float = typer.Option(20, "--timeout", min=1, max=60, help="Total status-read deadline in seconds"),
    table: bool = typer.Option(False, "--table", "-t", help="Display fields with metadata ages"),
):
    """Read observed battery, mission and connectivity with per-field source ages."""
    from ..cloud_observations import observed_status
    from cli_tools_shared.output import print_table
    config = get_config(profile=profile)
    session = load_session(config)
    target = resolve_robot(config, session, robot)
    from ..cloud_auth import authenticated_read
    result = authenticated_read(config, lambda credentials: observed_status(session, credentials, target, timeout), mqtt=True)
    if table:
        print_table([dict(field=field, **value) for field, value in result["fields"].items()], max_columns=0)
    else:
        print_json(result)


@app.command("schedules")
@command
def cloud_schedules(
    robot: str | None = typer.Option(None, "--robot", help="Cloud robot name or exact ID"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    timeout: float = typer.Option(20, "--timeout", min=1, max=60, help="Total schedule-read deadline in seconds"),
):
    """Read household schedules plus the selected robot's stored shadow schedules."""
    import time
    from ..cloud_observations import robot_schedules
    config = get_config(profile=profile)
    session = load_session(config)
    target = resolve_robot(config, session, robot)
    from ..cloud_auth import authenticated_read
    template = session.get("templates", {}).get(target, {}).get("schedule")
    if template is None:
        raise ClientError("A household schedule read was not captured for this robot")
    def read_all(credentials):
        deadline = time.monotonic() + timeout
        household = read_resource("schedule", template, credentials, template["region"], target, timeout)
        data = household["data"]
        if not isinstance(data, dict) or not isinstance(data.get("household_schedules"), list):
            raise ClientError("Household schedule response has an unsupported shape")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ClientError("Cloud schedule-read deadline expired")
        stored = robot_schedules(session, credentials, target, remaining)
        return {"robot_id": target, "household": {"source": "live_cloud", "scope": "household", "data": data}, "robot": stored}
    print_json(authenticated_read(config, read_all, mqtt=True))


@app.command("auth-status")
@command
def cloud_auth_status(
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
):
    """Show saved session expiry and renewal readiness without exposing secrets or logging in."""
    from ..cloud_auth import auth_status
    print_json(auth_status(get_config(profile=profile)))


@app.command("refresh")
@command
def cloud_refresh(
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
):
    """Renew AWS and MQTT tokens using the saved Gigya session; no password or robot action."""
    from ..cloud_auth import auth_status, refresh_auth, profile_lock
    config = get_config(profile=profile)
    with profile_lock(config, "mqtt"):
        credentials, refreshed = refresh_auth(config, force=True)
    print_json(dict(auth_status(config, credentials), refreshed=refreshed))


def _control(action, robot, profile, timeout):
    from ..cloud_control import run_control
    result = run_control(get_config(profile=profile), robot, action, timeout)
    print_json(result)
    if not result["robot_confirmed"]:
        raise typer.Exit(1)


@app.command("start")
@command
def cloud_start(
    robot: str = typer.Option(..., "--robot", help="Exact cloud robot name or ID to start cleaning"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    timeout: float = typer.Option(30, "--timeout", min=1, max=60, help="Total command and confirmation deadline"),
):
    """Start cleaning once through experimental cloud control; moves the selected robot."""
    _control("start", robot, profile, timeout)


@app.command("pause")
@command
def cloud_pause(
    robot: str = typer.Option(..., "--robot", help="Exact cloud robot name or ID to pause cleaning"),
    profile: str | None = typer.Option(None, "--profile", help="CLI profile"),
    timeout: float = typer.Option(30, "--timeout", min=1, max=60, help="Total command and confirmation deadline"),
):
    """Pause cleaning once through experimental cloud control; no automatic retry."""
    _control("pause", robot, profile, timeout)
