"""Main entry point for the Hermes Sessions CLI."""
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from cli_tools_shared.exceptions import ClientError

from . import __version__
from .commands import (
    auth,
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
from .config import get_config

app = create_app(
    name="hermes-sessions",
    help="Query and analyze Hermes Agent session state from the local Hermes home",
    version=__version__,
    cache_support=False,
)

app.add_typer(auth.app, name="auth", help="Check local Hermes state access")

# The command surface mirrors claude-code-sessions, codex-sessions, and
# deepseek-sessions so the same question can be asked of any harness.
register_commands(app, get_config, projects, name="projects", help="List and query projects")
register_commands(app, get_config, sessions, name="sessions", help="List, get, and search sessions")
register_commands(app, get_config, conversations, name="conversations", help="List conversations within sessions")
register_commands(app, get_config, turns, name="turns", help="Query agent turns")
register_commands(app, get_config, tool_calls, name="tool-calls", help="Query tool call history")
register_commands(app, get_config, todos, name="todos", help="Query todo items from sessions")
register_commands(app, get_config, skills, name="skills", help="Query skill loads and slash commands")
register_commands(app, get_config, subagent_activity, name="subagent-activity", help="Query subagent invocations")
register_commands(app, get_config, timeline, name="timeline", help="View unified activity timeline")
register_commands(app, get_config, search, name="search", help="Search keywords across session transcripts")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
