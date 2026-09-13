"""Main entry point for the Grok Bot Sessions CLI."""
from cli_tools_shared import create_app, run_app
from cli_tools_shared.cache_commands import create_cache_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .client import ClientError
from .config import get_config

app = create_app(
    name="grokbot-sessions",
    help="Query Grok Bot (Grokbot) session transcripts over the live Cursor-hosted Connect RPC API",
    version=__version__,
)

from .commands import (  # noqa: E402
    approvals,
    auth,
    automations,
    conversations,
    projects,
    search,
    sessions,
    skills,
    subagent_activity,
    timeline,
    todos,
    tool_calls,
    turns,
)

app.add_typer(auth.app, name="auth", help="Adopt and check the Grok Bot desktop session")

# Groups 1-10 mirror claude-code-sessions, codex-sessions, and
# deepseek-sessions so the same question can be asked of any harness with the
# same command shape.
register_commands(app, get_config, projects, name="projects", help="List implicit Grokbot projects")
register_commands(app, get_config, sessions, name="sessions", help="List, get, and search Grok Bot agents")
register_commands(app, get_config, conversations, name="conversations", help="List conversations within agents")
register_commands(app, get_config, turns, name="turns", help="Query agent turns and their entries")
register_commands(app, get_config, timeline, name="timeline", help="View transcript timelines")
register_commands(app, get_config, tool_calls, name="tool-calls", help="Query tool call cards")
register_commands(app, get_config, approvals, name="approvals", help="Query permission and review approvals")
register_commands(app, get_config, subagent_activity, name="subagent-activity", help="Query room members and cursor-agent runs")
register_commands(app, get_config, skills, name="skills", help="Query agent-store skills (unsupported)")
register_commands(app, get_config, todos, name="todos", help="Query todo items (unsupported)")
register_commands(app, get_config, search, name="search", help="Search keywords across transcript entries")

# Grokbot's own extension group.
register_commands(app, get_config, automations, name="automations", help="Query Grok Bot automations")

app.add_typer(create_cache_app(get_config), name="cache")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
