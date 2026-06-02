"""Main entry point for Ring CLI."""
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .commands import auth, chime, devices, events, lights, motion, siren, snapshot, volume
from .config import get_config


app = create_app(
    name="ring",
    help="CLI for Ring doorbells, cameras, chimes — devices, events, snapshots, recordings, motion, lights, siren",
    version=__version__,
)

# Auth and cache use the shared apps directly (their own credential gating)
app.add_typer(auth.app, name="auth", help="Manage Ring authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage local response cache")

# All resource groups go through register_commands so credential checks run.
register_commands(app, get_config, devices, name="devices", help="Manage Ring devices")
register_commands(app, get_config, events, name="events", help="List and download Ring events")
register_commands(app, get_config, snapshot, name="snapshot", help="Capture device snapshots")
register_commands(app, get_config, motion, name="motion", help="Manage motion detection")
register_commands(app, get_config, lights, name="lights", help="Control floodlights (stickup_cams)")
register_commands(app, get_config, siren, name="siren", help="Control siren (stickup_cams)")
register_commands(app, get_config, chime, name="chime", help="Control Ring chime devices")
register_commands(app, get_config, volume, name="volume", help="Manage device volume")


def main():
    """Main entry point."""
    from cli_tools_shared.exceptions import ClientError
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
