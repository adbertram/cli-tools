"""Main entry point for CourseCraft CLI."""
from . import __version__
from cli_tools_shared import create_app, run_app
from cli_tools_shared.command_registry import register_commands
from .client import ClientError
from .config import get_config

app = create_app(
    name="coursecraft",
    help="Manage CourseCraft course content in Airtable",
    version=__version__,
)

# Register command modules
from .commands import artifacts, auth, courses, modules, clips, demos, slides, slide_templates, course_outline, status, voice_recordings, feedback, fields, human_verification, versions
from cli_tools_shared.cache_commands import create_cache_app
app.add_typer(auth.app, name="auth", help="Manage authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")
register_commands(app, get_config, courses, name="courses", help="Manage course records")
register_commands(app, get_config, course_outline, name="course-outline", help="Manage course outline documents")
register_commands(app, get_config, modules, name="modules", help="Manage module records")
register_commands(app, get_config, clips, name="clips", help="Manage clip records")
register_commands(app, get_config, demos, name="demos", help="Manage demo records")
register_commands(app, get_config, slides, name="slides", help="Manage slide records")
register_commands(app, get_config, voice_recordings, name="voice-recordings", help="Generate demo voice recordings")
register_commands(app, get_config, slide_templates, name="slide-templates", help="Manage slide template records")
register_commands(app, get_config, feedback, name="feedback", help="Manage feedback records")
register_commands(app, get_config, fields, name="fields", help="Manage CourseCraft Airtable schema fields")
register_commands(app, get_config, artifacts, name="artifacts", help="Run CourseCraft artifact validation and preflight")
register_commands(app, get_config, human_verification, name="human-verification", help="Set or clear canonical human-verification gates")
register_commands(app, get_config, status, name="status", help="Report and gate CourseCraft work phase status")
register_commands(app, get_config, versions, name="versions", help="Sync CourseCraft artifact Version Control entries")
def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
