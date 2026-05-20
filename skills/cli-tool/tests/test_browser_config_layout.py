"""Browser-auth Config classes must not carry dead browser attributes.

``LOGIN_URL`` and ``SESSION_NAME`` are read by ``cli_tools_shared.auth`` directly
off the ``BrowserAutomation`` subclass (browser.py). Declaring them on ``Config``
(a ``BaseConfig`` subclass) is dead code — nothing in ``cli_tools_shared`` ever
reads ``config.LOGIN_URL`` or ``config.SESSION_NAME``. Carrying them duplicates
the source of truth and rots over time.
"""

from __future__ import annotations

import ast

import pytest

DEAD_CONFIG_ATTRS = ("LOGIN_URL", "SESSION_NAME")


def test_browser_cli_config_has_no_dead_browser_attrs(cli_name, cli_dir, command_filter, is_browser_cli):
    """Config must not declare LOGIN_URL or SESSION_NAME — they belong on the BrowserAutomation subclass."""
    if command_filter:
        pytest.skip("Skipping (command filter active)")
    if not is_browser_cli:
        pytest.skip(f"{cli_name} is not a browser automation CLI")

    config_file = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "config.py"
    if not config_file.exists():
        pytest.fail(f"config.py not found at {config_file}")

    offenders = []
    for class_node in (n for n in ast.walk(ast.parse(config_file.read_text())) if isinstance(n, ast.ClassDef)):
        for stmt in class_node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id in DEAD_CONFIG_ATTRS:
                    offenders.append(f"{class_node.name}.{target.id}")

    assert not offenders, (
        f"{config_file.relative_to(cli_dir)} declares dead attributes {offenders}.\n"
        f"Fix: remove these from Config. cli_tools_shared.auth reads LOGIN_URL / SESSION_NAME "
        f"from the BrowserAutomation subclass in browser.py — never from Config."
    )
