"""Crypto.com Exchange CLI."""
# Suppress urllib3 SSL warnings (LibreSSL compatibility) - must be before urllib3 import
import warnings
warnings.filterwarnings("ignore", module="urllib3")

__version__ = "0.1.0"
