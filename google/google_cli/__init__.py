"""Google CLI - Command-line interface for Google Workspace APIs."""
# Suppress warnings - must be before any library imports
import warnings
warnings.filterwarnings("ignore", module="urllib3")
warnings.filterwarnings("ignore", category=FutureWarning, module="google.api_core._python_version_support")

__version__ = "0.1.0"
