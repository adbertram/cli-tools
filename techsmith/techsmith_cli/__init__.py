"""Techsmith CLI - Command-line interface for Techsmith via browser automation."""
# Suppress urllib3 SSL warnings (LibreSSL compatibility) - must be before urllib3 import
import warnings
warnings.filterwarnings("ignore", module="urllib3")

__version__ = "0.1.0"

# Export commonly used classes for convenience
from cli_tools_shared.exceptions import ClientError
from .client import get_client
from .config import get_config
