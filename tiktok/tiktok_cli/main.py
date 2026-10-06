"""Main entry point for TikTok CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config
from .auth import add_manual_login_option
from .oauth import tiktok_oauth_login

app = create_app(
    name="tiktok",
    help="TikTok CLI for transcripts, favorites, and Content Posting API publishing",
    version=__version__,
    cache_support=False,
)

from .commands import account, favorites, studio, transcripts, videos

register_commands(app, get_config, transcripts, name="transcripts", help="Download TikTok video transcripts")
register_commands(app, get_config, favorites, name="favorites", help="Manage saved (favorited) TikTok videos")
register_commands(app, get_config, videos, name="videos", help="Publish, inspect, list, and delete TikTok videos")
register_commands(app, get_config, account, name="account", help="Read verified current account identity")
register_commands(app, get_config, studio, name="studio", help="Prepare, check, publish, and reconcile owned Studio drafts")
auth_app = create_auth_app(get_config, tool_name="tiktok", login_handler=tiktok_oauth_login)
add_manual_login_option(auth_app)
app.add_typer(auth_app, name="auth")


def main():
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
