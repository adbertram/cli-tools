"""Phase F1 — consumer discovery for the rollout-validation script."""

from pathlib import Path

from cli_tools_shared.discovery import discover_consumers


def _make_cli(tool_dir: Path, pkg: str, imports: str = "from cli_tools_shared.auth import BrowserAutomation\n"):
    pkg_dir = tool_dir / pkg
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "browser.py").write_text(imports)
    return pkg_dir / "browser.py"


def test_discover_consumers_finds_browser_py_under_cli_tools_shared_consumers(tmp_path):
    """Glob picks up every ``<tool>/<pkg>_cli/browser.py`` whose package
    imports ``cli_tools_shared``. CLIs that do not import the shared package
    must NOT appear in the result.
    """
    bricklink_browser = _make_cli(tmp_path / "bricklink", "bricklink_cli")
    ebay_browser = _make_cli(tmp_path / "ebay", "ebay_cli")
    # A CLI without the shared package import — must be excluded.
    _make_cli(
        tmp_path / "google",
        "google_cli",
        imports="from pathlib import Path\n",
    )
    # Junk directories — must be ignored.
    (tmp_path / ".git").mkdir()
    (tmp_path / "_templates").mkdir()

    result = discover_consumers(tmp_path)

    assert sorted(result) == sorted([bricklink_browser, ebay_browser])


def test_discover_consumers_returns_empty_list_for_missing_root(tmp_path):
    """A non-existent root must return an empty list, not raise."""
    assert discover_consumers(tmp_path / "does-not-exist") == []


def test_discover_consumers_ignores_packages_without_browser_py(tmp_path):
    """Packages without ``browser.py`` are not consumers in this sense."""
    pkg = tmp_path / "api-only" / "apionly_cli"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from cli_tools_shared.config import BaseConfig\n")
    # No browser.py — must not be returned.

    assert discover_consumers(tmp_path) == []
