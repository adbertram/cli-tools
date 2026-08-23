"""Main entry point for Jira CLI."""

from __future__ import annotations

from typing import Optional

import requests
import typer
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.oauth import oauth_login
from cli_tools_shared.output import print_error

from . import __version__
from .commands import projects, tickets
from .config import (
    OAUTH_3LO_AUTH_TYPE,
    SCOPED_API_TOKEN_AUTH_TYPE,
    SITE_BASIC_AUTH_TYPE,
    Config,
    get_config,
    migrate_legacy_profiles,
)

migrate_legacy_profiles()

app = create_app(name="jira", help="CLI interface for Jira Cloud tickets and projects", version=__version__)


def _normalized_site_url(site_url: Optional[str]) -> Optional[str]:
    if not site_url:
        return None
    normalized = site_url.rstrip("/")
    if "your-domain.atlassian.net" in normalized:
        return None
    return normalized


def _fetch_accessible_resources(access_token: str) -> list[dict]:
    response = requests.get(
        "https://api.atlassian.com/oauth/token/accessible-resources",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if response.status_code != 200:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        raise typer.BadParameter(
            f"Failed to resolve Jira Cloud resources from Atlassian OAuth grant: {payload}"
        )
    payload = response.json()
    if not isinstance(payload, list):
        raise typer.BadParameter("Atlassian accessible-resources returned an unexpected response shape.")
    resources = [
        item
        for item in payload
        if isinstance(item, dict)
        and isinstance(item.get("url"), str)
        and item.get("url", "").endswith(".atlassian.net")
    ]
    if not resources:
        raise typer.BadParameter(
            "No Jira Cloud resources were returned for this Atlassian OAuth grant."
        )
    return resources


def _select_accessible_resource(config: Config, resources: list[dict]) -> dict:
    desired_cloud_id = (config.cloud_id or "").strip()
    if desired_cloud_id:
        for resource in resources:
            if str(resource.get("id")) == desired_cloud_id:
                return resource

    desired_site_url = _normalized_site_url(config.base_url)
    if desired_site_url is not None:
        for resource in resources:
            if _normalized_site_url(resource.get("url")) == desired_site_url:
                return resource

    if len(resources) == 1:
        return resources[0]

    resource_list = ", ".join(
        f"{resource.get('name') or resource.get('url')} [{resource.get('url')}]"
        for resource in resources
    )
    raise typer.BadParameter(
        "Multiple Jira Cloud resources were granted to this OAuth app and the CLI could not "
        f"choose one automatically. Set BASE_URL to the target site and rerun 'jira auth login --profile {config.get_active_profile_name()} --force'. "
        f"Granted resources: {resource_list}"
    )


def _ensure_oauth_resource_binding(config: Config) -> None:
    resources = _fetch_accessible_resources(config.access_token or "")
    resource = _select_accessible_resource(config, resources)
    config._set("CLOUD_ID", str(resource["id"]))
    if _normalized_site_url(config.base_url) is None:
        config._set("BASE_URL", str(resource["url"]).rstrip("/"))


def _jira_login_handler(config: Config, force: bool) -> None:
    auth_type = config.auth_type
    if auth_type == SITE_BASIC_AUTH_TYPE:
        return

    if auth_type == SCOPED_API_TOKEN_AUTH_TYPE:
        return

    if auth_type == OAUTH_3LO_AUTH_TYPE:
        oauth_login(config, force)
        _ensure_oauth_resource_binding(config)
        return

    print_error(
        "Unknown Jira auth profile type. Create the profile with "
        "'jira auth profiles create <name> --auth-type "
        f"{SITE_BASIC_AUTH_TYPE}|{OAUTH_3LO_AUTH_TYPE}|{SCOPED_API_TOKEN_AUTH_TYPE}'."
    )
    raise typer.Exit(1)


app.add_typer(create_auth_app(get_config, tool_name="jira", login_handler=_jira_login_handler), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")
register_commands(app, get_config, tickets, name="tickets", help="Manage Jira tickets")
register_commands(app, get_config, projects, name="projects", help="Manage Jira projects")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
