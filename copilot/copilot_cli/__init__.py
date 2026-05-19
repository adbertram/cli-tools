"""Copilot CLI - Command-line interface for Microsoft Copilot Studio agents."""
import warnings

try:
    from urllib3.exceptions import NotOpenSSLWarning
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
except ImportError:
    pass

__version__ = "0.1.0"
