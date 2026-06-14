"""Regression tests for the CLI selection gate in conftest.py."""

from __future__ import annotations

from types import SimpleNamespace

from conftest import CLI_NAME_REQUIRED_MESSAGE, _selected_tests_need_cli_name


def _item_with_fixtures(*fixturenames: str):
    return SimpleNamespace(fixturenames=fixturenames)


def test_selected_tests_need_cli_name_when_cli_fixture_is_selected() -> None:
    items = [
        _item_with_fixtures("tmp_path"),
        _item_with_fixtures("cli_dir", "cli_name", "test_config"),
    ]

    assert _selected_tests_need_cli_name(items) is True


def test_selected_tests_do_not_need_cli_name_for_self_contained_harness_units() -> None:
    items = [
        _item_with_fixtures("tmp_path", "monkeypatch"),
        _item_with_fixtures(),
    ]

    assert _selected_tests_need_cli_name(items) is False


def test_cli_gate_message_clarifies_force_is_not_live_cli_execution() -> None:
    assert "Use --cli-name <name> to execute CLI-dependent tests." in CLI_NAME_REQUIRED_MESSAGE
    assert "--force only confirms batch/collect-only harness work" in CLI_NAME_REQUIRED_MESSAGE
