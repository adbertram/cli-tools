"""Phase F1 — validate_rollout.py classification table.

The validator's classification logic lives in a data table; this test pins
the green / unsupported / red mapping so future maintainers can add buckets
without breaking the existing rules.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def validate_rollout_module():
    """Import the script as a module without executing main()."""
    script = _REPO_ROOT / "scripts" / "validate_rollout.py"
    spec = importlib.util.spec_from_file_location("validate_rollout", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _completed(returncode: int, stderr: bytes = b""):
    return subprocess.CompletedProcess(
        args=["x", "auth", "status"], returncode=returncode, stdout=b"", stderr=stderr,
    )


def test_classification_green_for_exit_zero(validate_rollout_module):
    entry = validate_rollout_module._classify(_completed(0))
    assert entry["label"] == "green"
    assert entry["fail_run"] is False


def test_classification_unsupported_for_no_auth_command(validate_rollout_module):
    entry = validate_rollout_module._classify(
        _completed(2, stderr=b"Usage: tool\n\nError: No such command 'auth'.\n")
    )
    assert entry["label"] == "unsupported"
    assert entry["fail_run"] is False


def test_classification_red_for_other_nonzero(validate_rollout_module):
    entry = validate_rollout_module._classify(
        _completed(1, stderr=b"Authentication required.\n")
    )
    assert entry["label"] == "red"
    assert entry["fail_run"] is True


def test_classification_table_is_ordered_green_unsupported_red(validate_rollout_module):
    """Order matters because the first matching predicate wins. A red row
    must never beat an ``unsupported`` row when both could match — the
    ``unsupported`` predicate is strictly narrower.
    """
    labels = [entry["label"] for entry in validate_rollout_module._CLASSIFICATIONS]
    assert labels == ["green", "unsupported", "red"]
