"""Provision nonsecret root configuration without constructing auth profiles."""
import typer
from cli_tools_shared.config import config_env_path_for_tool, _read_env_values, _write_env_values
from cli_tools_shared.exceptions import ConfigError
from cli_tools_shared.output import command, print_json
from ..config import rewards_location

app = typer.Typer(help="Provision Whop root configuration", no_args_is_help=True)
COMMAND_CREDENTIALS = {"set-rewards-url": ["no_auth"]}

@app.command("set-rewards-url")
@command
def set_rewards_url(url: str = typer.Argument(..., help="Embedded Content Rewards HTTPS URL")):
    """Set a missing Rewards URL; refuse replacing an existing different URL."""
    origin, path = rewards_location(url)
    canonical = origin + path
    config_path = config_env_path_for_tool("whop")
    if config_path.is_symlink() or config_path.absolute() != config_path.resolve():
        raise ConfigError("Whop root config path must be unaliased")
    values = _read_env_values(config_path) if config_path.exists() else {}
    current = values.get("REWARDS_URL")
    if current and current != canonical:
        raise ConfigError("Whop Rewards URL is already configured differently")
    if current != canonical:
        values["REWARDS_URL"] = canonical
        _write_env_values(config_path, values)
    print_json({"tool": "whop", "rewards_url": canonical, "configured": True})
