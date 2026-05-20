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
from .commands import auth, courses, modules, clips, demos, slides, templates, course_outlines, voice_recordings
from .commands import demo_build_products, slide_build_products, descript
from cli_tools_shared.cache_commands import create_cache_app
app.add_typer(auth.app, name="auth", help="Manage authentication")
app.add_typer(create_cache_app(get_config), name="cache", help="Manage CLI cache")
register_commands(app, get_config, courses, name="courses", help="Manage course records")
register_commands(app, get_config, course_outlines, name="course-outlines", help="Manage course outline documents")
register_commands(app, get_config, modules, name="modules", help="Manage module records")
register_commands(app, get_config, clips, name="clips", help="Manage clip records")
register_commands(app, get_config, demos, name="demos", help="Manage demo records")
register_commands(app, get_config, slides, name="slides", help="Manage slide records")
register_commands(app, get_config, voice_recordings, name="voice-recordings", help="Generate slide and demo voice recordings")
register_commands(app, get_config, templates, name="slide-templates", help="Manage slide template records")
register_commands(app, get_config, demo_build_products, name="demo-build-products", help="Manage demo build product definitions")
register_commands(app, get_config, slide_build_products, name="slide-build-products", help="Manage slide build product definitions")
register_commands(app, get_config, descript, name="descript", help="Export videos from Descript")
def main():
    """Main entry point."""
    run_app(app, error_types=ClientError)


if __name__ == "__main__":
    main()
