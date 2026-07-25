import pytest
import typer

from brickowl_cli.commands import store


class _StoreBrowser:
    def __init__(self, slogan="FREE shipping on orders over $75", max_length=85):
        self.settings = {
            "slogan": slogan,
            "slogan_max_length": max_length,
        }
        self.saved = []
        self.closed = False

    def get_store_settings(self):
        return self.settings

    def save_store_slogan(self, slogan):
        self.saved.append(slogan)
        return {"success": True, "submitted": True, "slogan": slogan}

    def close(self):
        self.closed = True


def test_validate_ship_out_date_accepts_short_and_long_forms():
    assert store.validate_ship_out_date("07/21/2026") == "07/21/2026"
    assert store.validate_ship_out_date("7/21/26") == "07/21/2026"
    assert store.format_store_ship_out_date("07/21/2026") == "7/21/26"

    with pytest.raises(ValueError, match="M/D/YY or MM/DD/YYYY"):
        store.validate_ship_out_date("2026-07-21")

    with pytest.raises(ValueError, match="valid calendar date"):
        store.validate_ship_out_date("02/30/2026")


def test_apply_vacation_suffix_appends_accepted_text():
    result = store.apply_vacation_suffix("FREE shipping on orders over $75", "7/21/26")

    assert result == (
        "FREE shipping on orders over $75 | ATTENTION: All orders will ship 7/21/26!"
    )


def test_apply_vacation_suffix_replaces_existing_notice():
    result = store.apply_vacation_suffix(
        "FREE shipping on orders over $75 | ATTENTION: All orders will ship out 07/01/2026",
        "7/21/26",
    )

    assert result == (
        "FREE shipping on orders over $75 | ATTENTION: All orders will ship 7/21/26!"
    )


def test_remove_vacation_suffix_preserves_base_text():
    result = store.remove_vacation_suffix(
        "FREE shipping on orders over $75 | ATTENTION: All orders will ship 7/21/26!"
    )

    assert result == "FREE shipping on orders over $75"


def test_enable_saves_slogan_with_yes(monkeypatch):
    browser = _StoreBrowser()

    def _get_browser():
        return browser

    import brickowl_cli.browser as browser_module

    monkeypatch.setattr(browser_module, "get_browser", _get_browser)

    result = store._run_vacation_update(
        enabled=True,
        ship_out_date="7/21/26",
        dry_run=False,
        yes=True,
    )

    assert result["submitted"] is True
    assert browser.saved == [
        "FREE shipping on orders over $75 | ATTENTION: All orders will ship 7/21/26!"
    ]
    assert browser.closed is True


def test_disable_saves_slogan_with_yes(monkeypatch):
    browser = _StoreBrowser(
        slogan="FREE shipping on orders over $75 | ATTENTION: All orders will ship 7/21/26!"
    )

    def _get_browser():
        return browser

    import brickowl_cli.browser as browser_module

    monkeypatch.setattr(browser_module, "get_browser", _get_browser)

    result = store._run_vacation_update(
        enabled=False,
        dry_run=False,
        yes=True,
    )

    assert result["submitted"] is True
    assert browser.saved == ["FREE shipping on orders over $75"]
    assert browser.closed is True


def test_mutation_refuses_without_yes_or_dry_run(monkeypatch):
    called = False

    def _get_browser():
        nonlocal called
        called = True

    import brickowl_cli.browser as browser_module

    monkeypatch.setattr(browser_module, "get_browser", _get_browser)

    with pytest.raises(typer.Exit) as exc:
        store._run_vacation_update(
            enabled=False,
            dry_run=False,
            yes=False,
        )

    assert exc.value.exit_code == 1
    assert called is False


def test_enable_fails_when_slogan_limit_would_be_exceeded(monkeypatch):
    browser = _StoreBrowser(slogan="X" * 50, max_length=60)

    def _get_browser():
        return browser

    import brickowl_cli.browser as browser_module

    monkeypatch.setattr(browser_module, "get_browser", _get_browser)

    with pytest.raises(ValueError, match="maximum is 60"):
        store._run_vacation_update(
            enabled=True,
            ship_out_date="7/21/26",
            dry_run=False,
            yes=True,
        )

    assert browser.saved == []
    assert browser.closed is True
