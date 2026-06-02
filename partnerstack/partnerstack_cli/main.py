"""Main entry point for PartnerStack CLI."""
from typing import Optional

import typer

from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.credentials import mask_value
from cli_tools_shared.output import print_json

app = create_app(name="partnerstack", help="CLI interface for PartnerStack Partner API", version=__version__)

# Register command modules
from .commands import applications, form_templates, marketplace, partnerships, rewards
register_commands(app, get_config, rewards, name="rewards", help="List PartnerStack rewards")
register_commands(
    app,
    get_config,
    marketplace,
    name="marketplace",
    help="Browse PartnerStack marketplace programs (discovery)",
)
register_commands(
    app,
    get_config,
    form_templates,
    name="form-templates",
    help="List PartnerStack form templates using Basic auth",
)
register_commands(
    app,
    get_config,
    applications,
    name="applications",
    help="Create PartnerStack partner applications using Basic auth",
)
register_commands(
    app,
    get_config,
    partnerships,
    name="partnerships",
    help="List PartnerStack partnerships (post-approval relationships)",
)

# Register shared apps
auth_app = create_auth_app(get_config, tool_name="partnerstack")


@auth_app.command("login-basic")
def auth_login_basic(
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p", help="Profile name to save Basic credentials to"
    ),
    public_key: str = typer.Option(
        ...,
        "--public-key",
        help="PartnerStack Basic public key",
    ),
    secret_key: str = typer.Option(
        ...,
        "--secret-key",
        help="PartnerStack Basic secret key",
    ),
):
    """Configure PartnerStack Basic auth public/secret keys."""
    config = get_config(profile=profile)
    if not public_key.strip():
        raise typer.BadParameter("PartnerStack Basic public key cannot be empty")
    if not secret_key.strip():
        raise typer.BadParameter("PartnerStack Basic secret key cannot be empty")
    config.save_basic_credentials(public_key.strip(), secret_key.strip())
    typer.echo("Basic credentials saved successfully")


@auth_app.command("basic-status")
def auth_basic_status(
    profile: Optional[str] = typer.Option(
        None, "--profile", "-p", help="Profile name to inspect"
    ),
):
    """Show whether PartnerStack Basic auth credentials are configured."""
    config = get_config(profile=profile)
    print_json(
        {
            "profile": config.get_active_profile_name(),
            "username_saved": bool(config.username),
            "password_saved": bool(config.password),
            "username": mask_value(config.username) if config.username else None,
        }
    )


app.add_typer(auth_app, name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
