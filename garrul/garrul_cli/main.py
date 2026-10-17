"""Main entry point for Garrul CLI."""

from cli_tools_shared import create_app, run_app
from cli_tools_shared.auth_commands import create_auth_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .commands import (
    audit,
    comments,
    instance,
    notes,
    ops,
    posts,
    saved_replies,
    settings,
    subscriptions,
    telegram,
    users,
    webhooks,
)
from .config import get_config

app = create_app(name="garrul", help="Moderate and operate a self-hosted Garrul comment system", version=__version__)

GROUPS = (
    (comments, "comments", "Moderate comments and read threads"),
    (posts, "posts", "Open or close a post's comment thread"),
    (users, "users", "Manage commenter accounts"),
    (saved_replies, "saved-replies", "Manage saved replies"),
    (notes, "notes", "Write and remove internal moderator notes"),
    (webhooks, "webhooks", "Manage webhook endpoints"),
    (subscriptions, "subscriptions", "Manage email subscriptions"),
    (audit, "audit", "Read the moderation audit log"),
    (settings, "settings", "Read and change runtime settings"),
    (telegram, "telegram", "Manage your Telegram operator link"),
    (ops, "ops", "Run operator maintenance jobs"),
    (instance, "instance", "Inspect the Garrul instance"),
)
for module, name, help_text in GROUPS:
    register_commands(app, get_config, module, name=name, help=help_text)

app.add_typer(create_auth_app(get_config, tool_name="garrul"), name="auth")
app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app)


if __name__ == "__main__":
    main()
