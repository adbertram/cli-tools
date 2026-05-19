"""Globiflow CLI - Command-line interface for Globiflow via browser automation."""
# Suppress urllib3 SSL warnings (LibreSSL compatibility) - must be before urllib3 import
import warnings
warnings.filterwarnings("ignore", module="urllib3")

__version__ = "0.1.0"

# Export commonly used classes for convenience
from .browser import GlobiflowBrowser, BrowserService, BrowserError
from .client import ClientError, get_client
from .config import get_config
