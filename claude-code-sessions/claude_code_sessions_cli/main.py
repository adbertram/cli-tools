"""Main entry point for Claude Code Sessions CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="claude-code-sessions",
    help="Query and analyze Claude Code session data from ~/.claude",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import auth, projects, sessions, subagent_activity, tool_calls, todos, skills, timeline, conversations, search

app.add_typer(auth.app, name="auth", help="Check local Claude access")
register_commands(app, get_config, projects, name="projects", help="List and query projects")
register_commands(app, get_config, sessions, name="sessions", help="List and query sessions")
register_commands(app, get_config, conversations, name="conversations", help="List conversations within sessions")
register_commands(app, get_config, subagent_activity, name="subagent-activity", help="Query subagent invocations")
register_commands(app, get_config, tool_calls, name="tool-calls", help="Query tool call history")
register_commands(app, get_config, todos, name="todos", help="Query todo items from sessions")
register_commands(app, get_config, skills, name="skills", help="Query skill/command invocations")
register_commands(app, get_config, timeline, name="timeline", help="View unified activity timeline")
register_commands(app, get_config, search, name="search", help="Search keywords across all session transcripts")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
