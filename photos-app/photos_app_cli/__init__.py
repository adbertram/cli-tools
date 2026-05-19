"""PhotosApp CLI - Command-line wrapper for sqlite3."""
import warnings

# Suppress urllib3 warnings (not used by this CLI but may be pulled in by dependencies)
warnings.filterwarnings("ignore", module="urllib3")

__version__ = "0.1.0"
