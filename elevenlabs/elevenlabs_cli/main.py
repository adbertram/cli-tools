"""Main entry point for ElevenLabs CLI."""
from . import __version__
from .config import get_config
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

app = create_app(name="elevenlabs", help="CLI interface for ElevenLabs API", version=__version__)

# Register command modules
from .commands import models, pronunciation_dictionaries, speech, user, voices
register_commands(app, get_config, voices, name="voices", help="Manage ElevenLabs voices")
register_commands(app, get_config, models, name="models", help="Manage ElevenLabs models")
register_commands(app, get_config, speech, name="speech", help="Generate speech audio")
register_commands(
    app,
    get_config,
    pronunciation_dictionaries,
    name="pronunciation-dictionaries",
    help="Manage pronunciation dictionaries",
)
register_commands(app, get_config, user, name="user", help="Inspect ElevenLabs user account data")

# Register shared apps
app.add_typer(create_auth_app(get_config, tool_name="elevenlabs"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
