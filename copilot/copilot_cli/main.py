"""Main entry point for Copilot CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app, ConfigError
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.output import command

from .client import ClientError
from .config import get_config

# Create main Typer app
app = create_app(
    name="copilot",
    help="CLI interface for Microsoft Copilot Studio agents via Dataverse API",
    version=__version__,
)


# Import and register command modules


def _copilot_login_handler(config, force):
    """Custom login handler for Azure CLI authentication.

    Enforces the active profile's AZURE_CLI_EXPECTED_USER (when set):
    if the current ``az`` identity does not match, runs ``az login`` to
    switch identities and verifies the post-login identity matches.

    Fails loudly (SystemExit, non-zero) when the expected identity cannot
    be obtained — never prints "complete" unless credentials would actually
    pass ``config.has_credentials()``.
    """
    import json
    import subprocess
    from cli_tools_shared import print_info, print_success, print_error
    from .client import _resolve_az_command

    # Resolve Azure CLI binary
    try:
        az = _resolve_az_command()
        subprocess.run([az, "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print_error("Azure CLI is not installed. Install it: brew install azure-cli")
        raise SystemExit(2)

    expected_user = config.expected_user
    expected_tenant = config.tenant_id

    def _current_az_user():
        """Return the active az account user name, or None if not logged in."""
        result = subprocess.run(
            [az, "account", "show", "-o", "json"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return None
        try:
            account = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        return account.get("user", {}).get("name") or None

    def _build_login_cmd():
        # Note: do NOT pass --username. Doing so triggers az's legacy ROPC
        # (username/password) flow, which fails on MFA-enforced tenants
        # (AADSTS50076). The default browser flow handles MFA correctly,
        # and post-login _identity_ok(actual_user) enforces the expected user.
        cmd = [az, "login"]
        if expected_tenant:
            cmd.extend(["--tenant", expected_tenant])
        return cmd

    def _identity_ok(actual):
        if not expected_user:
            return actual is not None
        return actual is not None and actual.lower() == expected_user.lower()

    # If --force, log out first so the next az login is clean
    if force:
        print_info("Clearing existing Azure CLI session...")
        subprocess.run([az, "logout"], capture_output=True)

    actual_user = _current_az_user()

    if not _identity_ok(actual_user):
        if expected_user and actual_user:
            print_info(
                f"Azure CLI is logged in as '{actual_user}' but profile "
                f"'{config.get_active_profile_name()}' requires '{expected_user}'. "
                f"Switching identities..."
            )
        elif expected_user:
            print_info(
                f"Azure CLI not logged in — running 'az login' as '{expected_user}'..."
            )
        else:
            print_info("Azure CLI not logged in — running 'az login'...")

        login_result = subprocess.run(_build_login_cmd())
        if login_result.returncode != 0:
            print_error("'az login' failed")
            raise SystemExit(1)

        actual_user = _current_az_user()

    if not _identity_ok(actual_user):
        if expected_user:
            print_error(
                f"Azure CLI identity mismatch after login: expected '{expected_user}', "
                f"got '{actual_user or 'no active account'}'.\n"
                f"  Run: az login --tenant {expected_tenant or '<tenant-id>'} "
                f"--username {expected_user}"
            )
        else:
            print_error("Azure CLI is not logged in after 'az login'.")
        raise SystemExit(1)

    print_success(f"Azure CLI logged in as: {actual_user}")

    # Verify required profile fields are saved before the live API probe.
    if not config.has_credentials():
        missing = config.get_missing_credentials()
        if missing:
            print_error(
                f"Profile '{config.get_active_profile_name()}' is missing required "
                f"fields: {', '.join(missing)}"
            )
        else:
            print_error(
                f"Credentials saved for profile '{config.get_active_profile_name()}' "
                f"but verification failed."
            )
        raise SystemExit(1)

    # Confirm Dataverse API is actually reachable with these credentials.
    api_result = _copilot_test_handler(config)
    api_status = api_result.get("api_test", "skipped")
    if api_status != "passed":
        print_error(f"Authentication test failed: {api_status}")
        raise SystemExit(1)

    print_success("Authentication setup complete!")


def _copilot_test_handler(config):
    """Test handler for auth status verification.

    ``get_client`` caches the Dataverse client globally, so when the auth
    status / auth test loop iterates profile-by-profile we MUST reset the
    cache before each invocation — otherwise every profile's "live probe"
    runs against the FIRST profile's URL and access token, masking real
    credential failures and reporting bogus DNS errors for everything else.
    """
    if not config.dataverse_url:
        return {"api_test": "failed: DATAVERSE_URL not configured"}

    try:
        from .client import get_client, reset_client
        # Drop any client cached from an earlier profile in the same loop.
        reset_client()
        client = get_client(dataverse_url=config.dataverse_url)
        whoami = client.whoami()
        return {"api_test": "passed", "user_id": whoami.get("UserId", "")}
    except Exception as e:
        return {"api_test": f"failed: {e}"}


# Auth commands
from cli_tools_shared import create_auth_app

auth_app = create_auth_app(
    get_config_fn=get_config,
    tool_name="copilot",
    login_handler=_copilot_login_handler,
    test_handler=_copilot_test_handler,
)
app.add_typer(auth_app, name="auth", help="Manage CLI authentication (login, status, logout)")


app.add_typer(create_cache_app(get_config), name="cache")

# Config commands (paths, profiles, set-secret)
from .commands import config as _config_cmd
app.add_typer(_config_cmd.app, name="config", help="Manage copilot configuration paths, profiles, and secrets.")

import importlib

# Data-driven registration: (module name, CLI command name, help text).
# Imports are intentionally NOT wrapped in try/except — a missing or broken
# command module is a real bug and must fail loudly at startup.
COMMAND_GROUPS = [
    ("agent", "agent", "Manage Copilot Studio agents"),
    ("solution", "solution", "Manage solutions and solution components"),
    ("powerautomate_flow", "powerautomate-flow", "Manage Power Automate cloud flows"),
    ("agent_flow", "agent-flow", "Manage Copilot Studio agent flows"),
    ("tool", "tool", "Manage agent tools (REST APIs, MCP, connectors)"),
    ("prompt", "prompt", "Manage AI Builder prompts"),
    ("model", "model", "Manage AI Builder models"),
    ("managed_connector", "managed-connector", "List and inspect managed (Microsoft) connectors"),
    ("custom_connector", "custom-connector", "Create, manage, and inspect custom connectors"),
    ("connections", "connections", "Manage Power Platform connections (credentials)"),
    ("connection_references", "connection-references", "Manage connection references (solution-aware)"),
    ("environment", "environment", "Manage Power Platform environments"),
    ("user_licenses", "user-licenses", "Check user license assignments via Microsoft Graph"),
]

for module_name, cli_command_name, help_text in COMMAND_GROUPS:
    module = importlib.import_module(f".commands.{module_name}", package=__package__)
    register_commands(
        app,
        get_config,
        module,
        name=cli_command_name,
        help=help_text,
        cli_name="copilot",
    )

# Knowledge commands moved to: copilot agent knowledge
# Use: copilot agent knowledge upload/list/get/download/remove


@app.command("whoami")
@command
def whoami_command():
    """
    Get information about the current authenticated user.

    Returns the current user's ID, business unit, and organization information
    from the Dataverse environment.

    Examples:
        copilot whoami
    """
    from .client import get_client
    from cli_tools_shared.output import print_json

    client = get_client()
    result = client.whoami()
    print_json(result)


def main():
    """Main entry point for the CLI application."""
    run_app(app, error_types=(ClientError, ConfigError))


if __name__ == "__main__":
    main()
