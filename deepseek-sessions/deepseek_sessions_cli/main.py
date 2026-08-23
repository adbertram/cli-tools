"""Main entry point for the DeepSeek Sessions CLI."""
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands

from . import __version__
from .client import ClientError
from .config import get_config

app = create_app(
    name="deepseek-sessions",
    help="Query and analyze DeepSeek Harness (dsh) session data from ~/.dsh",
    version=__version__,
    cache_support=False,
)

from .commands import (  # noqa: E402
    approvals,
    auth,
    conversations,
    goals,
    projects,
    retries,
    search,
    sessions,
    skills,
    subagent_activity,
    timeline,
    todos,
    tool_calls,
    turns,
)

app.add_typer(auth.app, name="auth", help="Check local dsh access")

# Groups 1-9 mirror claude-code-sessions and codex-sessions so the same
# question can be asked of any harness with the same command shape.
register_commands(app, get_config, projects, name="projects", help="List and query projects")
register_commands(app, get_config, sessions, name="sessions", help="List, get, and search sessions")
register_commands(app, get_config, conversations, name="conversations", help="List conversations within sessions")
register_commands(app, get_config, subagent_activity, name="subagent-activity", help="Query subagent invocations")
register_commands(app, get_config, tool_calls, name="tool-calls", help="Query tool call history")
register_commands(app, get_config, todos, name="todos", help="Query todo items from sessions")
register_commands(app, get_config, skills, name="skills", help="Query skill loads and slash commands")
register_commands(app, get_config, timeline, name="timeline", help="View unified activity timeline")
register_commands(app, get_config, search, name="search", help="Search keywords across all session transcripts")

# Groups 10-13 have no Claude Code counterpart; they expose dsh's own records.
register_commands(app, get_config, turns, name="turns", help="Query agent turns and their steps")
register_commands(app, get_config, retries, name="retries", help="Query LLM retries and failure codes")
register_commands(app, get_config, approvals, name="approvals", help="Query permission escalation requests")
register_commands(app, get_config, goals, name="goals", help="Query standing goals and their revisions")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
