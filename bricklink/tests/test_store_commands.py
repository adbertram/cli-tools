import pytest
import typer

from bricklink_cli.commands import store


class _StoreBrowser:
    def __init__(self, announcement="Welcome", banner="Ships fast", shipping_methods=None):
        self.settings = {
            "announcement": announcement,
            "banner": banner,
        }
        self.shipping_methods = shipping_methods or []
        self.saved = []
        self.saved_shipping_methods = []

    def get_store_display_settings(self):
        return self.settings

    def get_enabled_shipping_methods(self):
        return self.shipping_methods

    def save_store_display_settings(self, announcement, banner):
        self.saved.append({"announcement": announcement, "banner": banner})
        return {"success": True, "status": 200, "returnCode": 0, "returnMessage": "OK"}

    def save_shipping_method_note(self, method_id, note):
        self.saved_shipping_methods.append({"id": method_id, "note": note})
        return {"success": True, "shipping_method_id": method_id}


def test_validate_ship_out_date_requires_mm_dd_yyyy():
    assert store.validate_ship_out_date("07/15/2026") == "07/15/2026"
    assert store.validate_ship_out_date("7/15/26") == "07/15/2026"
    assert store.format_store_ship_out_date("07/15/2026") == "7/15/26"

    with pytest.raises(ValueError, match="M/D/YY or MM/DD/YYYY"):
        store.validate_ship_out_date("2026-07-15")

    with pytest.raises(ValueError, match="valid calendar date"):
        store.validate_ship_out_date("02/30/2026")


def test_apply_vacation_suffix_appends_exact_suffix():
    assert store.VACATION_SUFFIX_PREFIX == " | ATTENTION: All orders will ship "

    result = store.apply_vacation_suffix("Welcome", "07/15/2026")

    assert result == f"Welcome{store.VACATION_SUFFIX_PREFIX}7/15/26!"


def test_apply_vacation_suffix_replaces_existing_notice_without_duplicates():
    result = store.apply_vacation_suffix(
        "Welcome | ATTENTION: All orders will ship out 07/01/2026",
        "07/15/2026",
    )

    assert result == f"Welcome{store.VACATION_SUFFIX_PREFIX}7/15/26!"


def test_remove_vacation_suffix_preserves_base_text():
    result = store.remove_vacation_suffix(
        f"Welcome{store.VACATION_SUFFIX_PREFIX}7/15/26!"
    )

    assert result == "Welcome"


def test_remove_vacation_suffix_removes_recorded_legacy_text():
    result = store.remove_vacation_suffix(
        "FREE shipping on orders over $75 | ATTENTION: All orders will ship 7/21/26!"
    )

    assert result == "FREE shipping on orders over $75"


def test_enable_dry_run_does_not_save(monkeypatch):
    browser = _StoreBrowser()
    monkeypatch.setattr(store, "run_browser", lambda action: action(browser))

    result = store._run_vacation_update(
        enabled=True,
        ship_out_date="07/15/2026",
        dry_run=True,
        yes=False,
    )

    assert result["dry_run"] is True
    assert result["changed"] is True
    assert result["submitted"] is False
    assert browser.saved == []


def test_enable_saves_replaced_notice_with_yes(monkeypatch):
    browser = _StoreBrowser(
        announcement="Welcome | ATTENTION: All orders will ship out 07/01/2026",
        banner="Ships fast",
    )
    monkeypatch.setattr(store, "run_browser", lambda action: action(browser))

    result = store._run_vacation_update(
        enabled=True,
        ship_out_date="07/15/2026",
        dry_run=False,
        yes=True,
    )

    assert result["submitted"] is True
    assert browser.saved == [
        {
            "announcement": f"Welcome{store.VACATION_SUFFIX_PREFIX}7/15/26!",
            "banner": f"Ships fast{store.VACATION_SUFFIX_PREFIX}7/15/26!",
        }
    ]
    assert browser.saved_shipping_methods == []


def test_enable_saves_notice_on_enabled_shipping_methods(monkeypatch):
    browser = _StoreBrowser(
        shipping_methods=[
            {
                "id": "231904",
                "name": "Ground Advantage",
                "description": "Ships fast",
                "enabled": True,
            },
            {
                "id": "233995",
                "name": "International",
                "description": "Ships worldwide",
                "enabled": True,
            },
        ]
    )
    monkeypatch.setattr(store, "run_browser", lambda action: action(browser))

    result = store._run_vacation_update(
        enabled=True,
        ship_out_date="7/21/26",
        dry_run=False,
        yes=True,
    )

    assert result["submitted"] is True
    assert browser.saved_shipping_methods == [
        {
            "id": "231904",
            "note": f"Ships fast{store.VACATION_SUFFIX_PREFIX}7/21/26!",
        },
        {
            "id": "233995",
            "note": f"Ships worldwide{store.VACATION_SUFFIX_PREFIX}7/21/26!",
        },
    ]


def test_disable_removes_notice_from_both_fields(monkeypatch):
    browser = _StoreBrowser(
        announcement=f"Welcome{store.VACATION_SUFFIX_PREFIX}7/15/26!",
        banner=f"Ships fast{store.VACATION_SUFFIX_PREFIX}7/15/26!",
    )
    monkeypatch.setattr(store, "run_browser", lambda action: action(browser))

    result = store._run_vacation_update(
        enabled=False,
        dry_run=False,
        yes=True,
    )

    assert result["submitted"] is True
    assert browser.saved == [{"announcement": "Welcome", "banner": "Ships fast"}]
    assert browser.saved_shipping_methods == []


def test_disable_removes_notice_from_enabled_shipping_methods(monkeypatch):
    browser = _StoreBrowser(
        shipping_methods=[
            {
                "id": "231904",
                "name": "Ground Advantage",
                "description": f"Ships fast{store.VACATION_SUFFIX_PREFIX}7/21/26!",
                "enabled": True,
            }
        ]
    )
    monkeypatch.setattr(store, "run_browser", lambda action: action(browser))

    result = store._run_vacation_update(
        enabled=False,
        dry_run=False,
        yes=True,
    )

    assert result["submitted"] is True
    assert browser.saved_shipping_methods == [{"id": "231904", "note": "Ships fast"}]


def test_mutation_refuses_without_yes_or_dry_run(monkeypatch):
    called = False

    def _run_browser(_action):
        nonlocal called
        called = True

    monkeypatch.setattr(store, "run_browser", _run_browser)

    with pytest.raises(typer.Exit) as exc:
        store._run_vacation_update(
            enabled=False,
            dry_run=False,
            yes=False,
        )

    assert exc.value.exit_code == 1
    assert called is False
