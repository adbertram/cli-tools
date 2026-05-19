"""Main entry point for CodexSessions CLI."""
from . import __version__
from .client import ClientError
from cli_tools_shared import create_app, run_app

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
app.add_typer(projects.app, name="projects", help="List and query projects")
app.add_typer(sessions.app, name="sessions", help="List, get, and search sessions")
app.add_typer(conversations.app, name="conversations", help="List and query conversation turns")
app.add_typer(subagent_activity.app, name="subagent-activity", help="Query subagent invocations")
app.add_typer(tool_calls.app, name="tool-calls", help="Query tool call history")
app.add_typer(todos.app, name="todos", help="Query update-plan items")
app.add_typer(skills.app, name="skills", help="Query skill mentions")
app.add_typer(timeline.app, name="timeline", help="View activity timelines")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
