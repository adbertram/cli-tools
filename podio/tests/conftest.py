"""Pytest configuration for the podio CLI test suite.

Ensures the podio_cli package (which lives at the repository root) is importable
when the suite is run from the tool directory.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
