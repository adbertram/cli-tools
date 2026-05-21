"""Main entry point for CodexSessions CLI."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .config import get_config

app = create_app(
    name="codex-sessions",
    help="Query and analyze OpenAI Codex session data from ~/.codex",
    version=__version__,
    cache_support=False,
)

from .commands import (  # noqa: E402
    auth,
    conversations,
    projects,
    sessions,
    skills,
    subagent_activity,
    timeline,
    todos,
    tool_calls,
)

app.add_typer(auth.app, name="auth", help="Check local Codex access")
register_commands(app, get_config, projects, name="projects", help="List and query projects")
register_commands(app, get_config, sessions, name="sessions", help="List, get, and search sessions")
register_commands(app, get_config, conversations, name="conversations", help="List and query conversation turns")
register_commands(app, get_config, subagent_activity, name="subagent-activity", help="Query subagent invocations")
register_commands(app, get_config, tool_calls, name="tool-calls", help="Query tool call history")
register_commands(app, get_config, todos, name="todos", help="Query update-plan items")
register_commands(app, get_config, skills, name="skills", help="Query skill mentions")
register_commands(app, get_config, timeline, name="timeline", help="View activity timelines")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
