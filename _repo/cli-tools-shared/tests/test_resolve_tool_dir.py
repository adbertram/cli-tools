"""Tests for cli_tools_shared.config.resolve_tool_dir.

These tests enforce the invariant that a CLI tool's `tool_dir` — and therefore
    profile bootstrap lookups — resolve from the canonical CLI tool source
folder registered in the installed distribution, NOT from whichever copy of
the package Python happens to import (e.g., a stray editable copy sitting in
an unrelated repository).

The historical bug these tests prevent:
    A fork of the `copilot_cli` package lived inside a second repository
    (ProgressAutomationProject/). Because its pyproject.toml also declared
    `name = "copilot-cli"`, `uv tool install` silently redirected the canonical
    `copilot-cli` editable install at that fork's source folder. The installed
    config bootstrap then read source files from ProgressAutomationProject
    instead of from `cli-tools/copilot/`.

    The old Config class used `tool_dir=Path(__file__).resolve().parent.parent`,
    which followed the loaded package file — so profiles were pulled from the
    wrong folder. The new code uses `resolve_tool_dir(DIST_NAME)`, which reads
    the installed distribution's metadata (direct_url.json / top_level.txt) to
    find the canonical source folder and validates it against pyproject.toml.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType
from cli_tools_shared.exceptions import ConfigError


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_tool_folder(base: Path, name: str, dist_name: str) -> Path:
    """Create a minimal CLI tool source folder containing pyproject.toml."""
    tool_dir = base / name
    tool_dir.mkdir(parents=True)
    (tool_dir / "pyproject.toml").write_text(textwrap.dedent(f"""
        [project]
        name = "{dist_name}"
        version = "0.0.1"
    """).strip() + "\n")
    return tool_dir


# ---------------------------------------------------------------------------
# resolve_tool_dir — env override
# ---------------------------------------------------------------------------

def test_env_override_takes_precedence(tmp_path, monkeypatch):
    """CLI_TOOL_DIR_<DIST> env var overrides distribution metadata."""
    tool_dir = _make_tool_folder(tmp_path, "example", "example-cli")
    monkeypatch.setenv("CLI_TOOL_DIR_EXAMPLE_CLI", str(tool_dir))

    resolved = resolve_tool_dir("example-cli")

    assert resolved == tool_dir.resolve()


def test_env_override_missing_dir_raises(tmp_path, monkeypatch):
    """Env override pointing at nonexistent dir must raise loudly."""
    monkeypatch.setenv("CLI_TOOL_DIR_EXAMPLE_CLI", str(tmp_path / "does-not-exist"))

    with pytest.raises(ConfigError, match="does not point at an existing directory"):
        resolve_tool_dir("example-cli")


def test_env_override_with_hyphen_and_dot_in_dist_name(tmp_path, monkeypatch):
    """Env var name is normalized: hyphens/dots become underscores."""
    tool_dir = _make_tool_folder(tmp_path, "ata.blog", "ata-blog-cli")
    # Env var name = CLI_TOOL_DIR_ATA_BLOG_CLI
    monkeypatch.setenv("CLI_TOOL_DIR_ATA_BLOG_CLI", str(tool_dir))

    resolved = resolve_tool_dir("ata-blog-cli")

    assert resolved == tool_dir.resolve()


# ---------------------------------------------------------------------------
# resolve_tool_dir — missing distribution
# ---------------------------------------------------------------------------

def test_missing_distribution_raises(monkeypatch):
    """Unknown distribution name must raise ConfigError loudly."""
    monkeypatch.delenv("CLI_TOOL_DIR_DEFINITELY_NOT_A_REAL_CLI", raising=False)

    with pytest.raises(ConfigError, match="is not installed"):
        resolve_tool_dir("definitely-not-a-real-cli")


# ---------------------------------------------------------------------------
# resolve_tool_dir — STRAY EDITABLE PACKAGE (the regression test)
# ---------------------------------------------------------------------------

def _mock_editable_distribution(dist_name: str, source_dir: Path):
    """Build a fake importlib.metadata.Distribution pointing at source_dir via direct_url.json."""
    direct_url = {
        "url": f"file://{source_dir}",
        "dir_info": {"editable": True},
    }

    class _FakeDistribution:
        name = dist_name

        def read_text(self, filename):
            if filename == "direct_url.json":
                return json.dumps(direct_url)
            return None

    return _FakeDistribution()


def test_stray_package_copy_does_not_redirect_tool_dir(tmp_path, monkeypatch):
    """REGRESSION TEST for the copilot-cli redirect bug.

    Simulates the exact historical scenario:
        - Canonical tool folder at `canonical/example-cli/` — where the
          `example-cli` distribution's editable install is registered.
        - A stray copy of the same-named package at `stray/example-cli/`
          — e.g., another repo that happens to import the package.

    The resolved `tool_dir` MUST come from the canonical folder (registered
    in direct_url.json), regardless of where a stray package copy exists.
    BaseConfig must still resolve against the canonical folder. Source-tree
    profile files are intentionally ignored because runtime migration is not
    part of the package contract.
    """
    # Isolate user-data writes so the test does not pollute the
    # developer's real ``~/.local/share/cli-tools/`` tree.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))

    canonical = _make_tool_folder(tmp_path / "canonical", "example_cli", "example-cli")
    stray = _make_tool_folder(tmp_path / "stray", "example_cli", "example-cli")
    # Add a distinguishing source-tree profile in the stray copy. Runtime
    # config must read only the canonical user-data profile below.
    (stray / ".env.stray_profile").write_text(
        "ACTIVE=false\nORIGIN=stray\n"
    )

    fake_dist = _mock_editable_distribution("example-cli", canonical)

    def fake_distribution(name):
        assert name == "example-cli"
        return fake_dist

    monkeypatch.delenv("CLI_TOOL_DIR_EXAMPLE_CLI", raising=False)
    with patch(
        "cli_tools_shared.config.distribution" if False else "importlib.metadata.distribution",
        side_effect=fake_distribution,
    ):
        resolved = resolve_tool_dir("example-cli")

    # Canonical folder MUST win regardless of any stray copy
    assert resolved == canonical.resolve()
    assert resolved != stray.resolve()

    from cli_tools_shared.config import get_profiles_base_dir

    profiles_dir = get_profiles_base_dir(resolved.name)
    user_profile = profiles_dir / "canonical_profile" / ".env"
    user_profile.parent.mkdir(parents=True)
    user_profile.write_text("ACTIVE=false\nORIGIN=canonical-user-data\n")

    class _ExampleConfig(BaseConfig):
        CREDENTIAL_TYPES = [CredentialType.NO_AUTH]
        DIST_NAME = "example-cli"

        def __init__(self):
            super().__init__(tool_dir=resolved, profile="canonical_profile")

    config = _ExampleConfig()
    assert config.env_file_path == user_profile
    assert config._get("ORIGIN") == "canonical-user-data"
    # Stray's named profile must NOT have been copied into user data.
    stray_profile = profiles_dir / "stray_profile" / ".env"
    assert not stray_profile.exists()


def test_direct_url_points_to_wrong_dist_name_raises(tmp_path, monkeypatch):
    """If direct_url.json points at a folder whose pyproject declares a different
    distribution name, resolve_tool_dir MUST raise — not silently return it.

    This catches `uv tool install` pointing at the wrong source folder.
    """
    wrong_dir = _make_tool_folder(tmp_path, "wrong", "some-other-cli")
    fake_dist = _mock_editable_distribution("example-cli", wrong_dir)

    monkeypatch.delenv("CLI_TOOL_DIR_EXAMPLE_CLI", raising=False)
    with patch("importlib.metadata.distribution", side_effect=lambda n: fake_dist):
        with pytest.raises(ConfigError, match="disagree"):
            resolve_tool_dir("example-cli")


def test_direct_url_with_no_pyproject_raises(tmp_path, monkeypatch):
    """If direct_url.json points at a folder with no pyproject.toml, raise."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    fake_dist = _mock_editable_distribution("example-cli", empty_dir)

    monkeypatch.delenv("CLI_TOOL_DIR_EXAMPLE_CLI", raising=False)
    with patch("importlib.metadata.distribution", side_effect=lambda n: fake_dist):
        with pytest.raises(ConfigError, match="no.*pyproject.toml"):
            resolve_tool_dir("example-cli")


def test_pyproject_name_matches_normalized(tmp_path, monkeypatch):
    """pyproject.toml name comparison is case-insensitive and normalizes hyphens/underscores."""
    tool_dir = _make_tool_folder(tmp_path, "example_cli", "Example_CLI")
    fake_dist = _mock_editable_distribution("example-cli", tool_dir)

    monkeypatch.delenv("CLI_TOOL_DIR_EXAMPLE_CLI", raising=False)
    with patch("importlib.metadata.distribution", side_effect=lambda n: fake_dist):
        resolved = resolve_tool_dir("example-cli")

    assert resolved == tool_dir.resolve()


# ---------------------------------------------------------------------------
# Invariant: BaseConfig subclasses must NOT use Path(__file__).parent.parent
# ---------------------------------------------------------------------------

def test_base_config_does_not_use_file_based_tool_dir_in_docstring():
    """BaseConfig docs must tell subclasses to use resolve_tool_dir, not __file__.

    This is a lightweight structural test to catch regressions in the docstring
    guidance that could lead future tools to reintroduce the stray-package bug.
    """
    doc = BaseConfig.__doc__ or ""
    assert "resolve_tool_dir" in doc, (
        "BaseConfig docstring must document resolve_tool_dir as the supported "
        "way to compute tool_dir."
    )
    assert "NEVER" in doc and "__file__" in doc, (
        "BaseConfig docstring must warn against Path(__file__).parent.parent."
    )
