"""Main entry point for Claude Code Sessions CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from .client import ClientError

app = create_app(
    name="claude-code-sessions",
    help="Query and analyze Claude Code session data from ~/.claude",
    version=__version__,
    cache_support=False,
)

# Register command modules
from .commands import auth, projects, sessions, subagent_activity, tool_calls, todos, skills, timeline, conversations, search

app.add_typer(auth.app, name="auth", help="Check local Claude access")
app.add_typer(projects.app, name="projects", help="List and query projects")
app.add_typer(sessions.app, name="sessions", help="List and query sessions")
app.add_typer(conversations.app, name="conversations", help="List conversations within sessions")
app.add_typer(subagent_activity.app, name="subagent-activity", help="Query subagent invocations")
app.add_typer(tool_calls.app, name="tool-calls", help="Query tool call history")
app.add_typer(todos.app, name="todos", help="Query todo items from sessions")
app.add_typer(skills.app, name="skills", help="Query skill/command invocations")
app.add_typer(timeline.app, name="timeline", help="View unified activity timeline")
app.add_typer(search.app, name="search", help="Search keywords across all session transcripts")


def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
