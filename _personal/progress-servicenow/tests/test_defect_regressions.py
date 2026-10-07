"""Regression tests for the three reported progress-servicenow defects.

1. ``ticket product list`` silently returned ``[]`` with exit code 0.
2. ``ticket form inspect`` could not resolve its own template.
3. ``ticket create --draft`` raised ``TypeError`` from a call-site/callee
   signature mismatch, and ``--dry-run`` reported success for values it never
   checked.
"""

import inspect

import pytest
import typer
from cli_tools_shared.exceptions import ClientError
from typer.testing import CliRunner

from progress_servicenow_cli import client as client_mod
from progress_servicenow_cli.client import ProgressServicenowClient
from progress_servicenow_cli.commands import form, product, ticket
from progress_servicenow_cli.template_data import load_ticket_template

from conftest import (
    DRAFT_MODAL_SNAPSHOT,
    DRAFT_SAVED_SNAPSHOT,
    LIVE_FORM_SNAPSHOT,
    UNAUTHORIZED_SNAPSHOT,
)

runner = CliRunner()


def _create_app():
    app = typer.Typer()
    app.command("create")(ticket.ticket_create)
    return app


class FakeClient:
    """Records what a command asked the client to do."""

    def __init__(self, products=None, fields=None, error=None):
        self._products = products
        self._fields = fields
        self._error = error
        self.closed = False

    def list_products(self):
        if self._error:
            raise self._error
        return self._products

    def inspect_form(self, template_data=None, url=None):
        if self._error:
            raise self._error
        return self._fields

    def close(self):
        self.closed = True


# --------------------------------------------------------------------------
# Defect 1: a discovery command must never report success with no results.
# --------------------------------------------------------------------------


def test_product_list_fails_loudly_when_live_options_are_empty(monkeypatch):
    """An empty live product list is a failure, not an empty successful result."""
    monkeypatch.setattr(product, "get_client", lambda: FakeClient(products=[]))
    result = runner.invoke(product.app, ["list"])
    assert result.exit_code != 0
    assert result.stdout.strip() != "[]"
    assert "no options" in result.output


def test_product_list_table_fails_loudly_when_live_options_are_empty(monkeypatch):
    monkeypatch.setattr(product, "get_client", lambda: FakeClient(products=[]))
    result = runner.invoke(product.app, ["list", "--table"])
    assert result.exit_code != 0
    assert "No products found" not in result.output


def test_product_list_surfaces_live_client_errors(monkeypatch):
    error = ClientError("The live Product dropdown returned no choices.")
    monkeypatch.setattr(product, "get_client", lambda: FakeClient(error=error))
    result = runner.invoke(product.app, ["list"])
    assert result.exit_code != 0
    assert "returned no choices" in result.output


def test_product_list_returns_live_options(monkeypatch):
    monkeypatch.setattr(
        product, "get_client", lambda: FakeClient(products=["Sitefinity", "OpenEdge"])
    )
    result = runner.invoke(product.app, ["list"])
    assert result.exit_code == 0
    assert "Sitefinity" in result.stdout
    assert "OpenEdge" in result.stdout


def test_list_products_fails_when_variable_publishes_no_choices(monkeypatch, live_catalog_item):
    """The client refuses to hand back an empty option list as a success."""
    stripped = {
        **live_catalog_item,
        "variables": [
            {
                "name": "var_product",
                "label": "Product",
                "friendly_type": "select_box",
                "mandatory": True,
                "choices": [],
            }
        ],
    }
    monkeypatch.setattr(client_mod, "_catalog_page", lambda self: object())
    monkeypatch.setattr(client_mod.catalog_api, "get_item", lambda page, sys_id: stripped)

    client = ProgressServicenowClient.__new__(ProgressServicenowClient)
    with pytest.raises(ClientError, match="returned no choices"):
        client_mod._live_product_options(client)


# --------------------------------------------------------------------------
# Defect 2: the template registry and the catalog must agree.
# --------------------------------------------------------------------------


def test_template_registry_carries_live_catalog_identifiers():
    """Every registry entry must be resolvable without scraping the search page."""
    catalog_items = load_ticket_template()["catalog_items"]
    assert catalog_items, "ticket_template.json has no catalog items"
    for key, entry in catalog_items.items():
        assert entry.get("sys_id"), f"template {key} has no sys_id"
        assert entry.get("url", "").startswith("?id=sc_cat_item&sys_id="), key
        assert entry.get("fields"), f"template {key} has no fields"


def test_product_template_entry_publishes_live_options():
    entry = load_ticket_template()["catalog_items"][client_mod.PRODUCT_TEMPLATE_KEY]
    options = entry["fields"][client_mod.PRODUCT_FIELD_KEY]["options"]
    assert len(options) > 1
    assert "Sitefinity" in options


class RecordingClient:
    """Captures navigation so the resolution path can be asserted."""

    def __init__(self, snapshot=LIVE_FORM_SNAPSHOT):
        self.navigated = []
        self.snapshot_text = snapshot
        self.config = type("Config", (), {"base_url": "https://progress1.service-now.com/esc"})()

    def _ensure_browser(self):
        return None

    def _navigate(self, url):
        self.navigated.append(url)

    def _wait(self, ms):
        return None

    def _dismiss_loading_overlay(self):
        return None

    def _snapshot(self):
        return self.snapshot_text


def test_navigate_to_catalog_form_uses_sys_id_not_the_search_page():
    client = RecordingClient()
    entry = {"name": "Other Development Request", "sys_id": "838c9810dbe5db0408f33a1b7c961930"}
    client_mod._navigate_to_catalog_form(client, template_data=entry)
    assert client.navigated == [
        "https://progress1.service-now.com/esc"
        "?id=sc_cat_item&sys_id=838c9810dbe5db0408f33a1b7c961930"
    ]
    assert not any("id=search" in url for url in client.navigated)


def test_navigate_to_catalog_form_fails_on_retired_catalog_item():
    client = RecordingClient(snapshot=UNAUTHORIZED_SNAPSHOT)
    entry = {"name": "Development Cloud Issue", "sys_id": "c9f3a854dbe5db0408f33a1b7c9619dc"}
    with pytest.raises(ClientError, match="not authorized or record is not valid"):
        client_mod._navigate_to_catalog_form(client, template_data=entry)


def test_navigate_to_catalog_form_requires_exactly_one_target():
    client = RecordingClient()
    with pytest.raises(ClientError, match="exactly one"):
        client_mod._navigate_to_catalog_form(client)
    with pytest.raises(ClientError, match="exactly one"):
        client_mod._navigate_to_catalog_form(client, template_data={"sys_id": "x"}, url="y")


def test_form_inspect_fails_loudly_when_no_fields_are_found(monkeypatch):
    monkeypatch.setattr(form, "get_client", lambda: FakeClient(fields=[]))
    monkeypatch.setattr(
        form, "load_ticket_template", lambda: {"catalog_items": {"other_development_request": {}}}
    )
    result = runner.invoke(form.app, ["inspect", "-T", "other_development_request"])
    assert result.exit_code != 0
    assert "No form fields" in result.output


def test_form_inspect_names_available_keys_for_an_unknown_template(monkeypatch):
    monkeypatch.setattr(
        form, "load_ticket_template", lambda: {"catalog_items": {"purchase_request": {}}}
    )
    result = runner.invoke(form.app, ["inspect", "-T", "development_cloud_issue"])
    assert result.exit_code != 0
    assert "purchase_request" in result.output


# --------------------------------------------------------------------------
# Defect 3: --draft must work, and --dry-run must not pass unchecked values.
# --------------------------------------------------------------------------


def test_create_ticket_from_template_signature_matches_the_call_site():
    signature = inspect.signature(ProgressServicenowClient.create_ticket_from_template)
    assert list(signature.parameters) == [
        "self",
        "template_key",
        "template_data",
        "field_values",
        "draft",
        "draft_name",
    ]


def test_ticket_create_passes_template_data_and_draft_to_the_client(monkeypatch):
    captured = {}

    class DraftClient:
        def create_ticket_from_template(self, **kwargs):
            captured.update(kwargs)
            return {"status": "DRAFT_SAVED", "number": "", "template": kwargs["template_key"]}

        def close(self):
            return None

    monkeypatch.setattr(ticket, "get_client", lambda: DraftClient())
    result = runner.invoke(
        _create_app(),
        [
            "--template",
            "other_development_request",
            "-F",
            "product=Sitefinity",
            "-F",
            "req_impact=Low",
            "-F",
            "description=hello",
            "--draft",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["template_key"] == "other_development_request"
    assert captured["draft"] is True
    assert captured["template_data"]["sys_id"]
    assert captured["field_values"]["product"] == "Sitefinity"


def test_dry_run_rejects_a_value_the_live_template_does_not_offer():
    result = runner.invoke(
        _create_app(),
        [
            "--template",
            "other_development_request",
            "-F",
            "product=Azure",
            "-F",
            "req_impact=Low",
            "-F",
            "description=hello",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "not a valid option" in result.output
    assert "Validation passed" not in result.output


def test_dry_run_marks_values_it_cannot_verify():
    result = runner.invoke(
        _create_app(),
        [
            "--template",
            "other_development_request",
            "-F",
            "product=Sitefinity",
            "-F",
            "req_impact=Low",
            "-F",
            "description=hello",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "NOT VERIFIED" in result.output


def test_draft_name_requires_draft():
    result = runner.invoke(
        _create_app(),
        ["--template", "other_development_request", "--draft-name", "x"],
    )
    assert result.exit_code != 0
    assert "--draft-name requires --draft" in result.output


class DraftFlowClient:
    """Drives the draft dialog through a scripted sequence of snapshots."""

    def __init__(self, snapshots):
        self._snapshots = list(snapshots)
        self.clicked = []
        self._svc = self

    def _get_page(self):
        return self

    def evaluate(self, script, arg=None):
        return {"ok": True, "applied": arg}

    def _snapshot(self):
        return self._snapshots.pop(0)

    def _click(self, ref):
        self.clicked.append(ref)

    def _wait(self, ms):
        return None

    def _dismiss_loading_overlay(self):
        return None


def test_save_draft_completes_the_save_dialog():
    client = DraftFlowClient([DRAFT_MODAL_SNAPSHOT, DRAFT_SAVED_SNAPSHOT])
    confirmation = client_mod._save_draft(client, LIVE_FORM_SNAPSHOT, "CLI test draft")
    assert client.clicked == ["e224", "e31"]
    assert client_mod.DRAFT_SAVED_MARKER in confirmation


def test_save_draft_fails_when_servicenow_never_confirms():
    client = DraftFlowClient([DRAFT_MODAL_SNAPSHOT, DRAFT_MODAL_SNAPSHOT])
    with pytest.raises(ClientError, match="already exists"):
        client_mod._save_draft(client, LIVE_FORM_SNAPSHOT, "CLI test draft")


def test_save_draft_fails_when_the_dialog_never_opens():
    client = DraftFlowClient([LIVE_FORM_SNAPSHOT])
    with pytest.raises(ClientError, match="did not open"):
        client_mod._save_draft(client, LIVE_FORM_SNAPSHOT, None)


def test_apply_field_rejects_an_option_missing_from_the_live_form():
    class RejectingClient:
        def __init__(self):
            self._svc = self

        def _get_page(self):
            return self

        def evaluate(self, script, arg=None):
            return {"ok": False, "error": "option not present on the live form",
                    "options": ["Low", "Medium", "High"]}

        def _wait(self, ms):
            return None

    definition = {
        "label": "What's the impact of the problem on your productivity?",
        "type": "dropdown",
        "variable": "ReqImpact",
    }
    with pytest.raises(ClientError) as exc:
        client_mod._apply_field(RejectingClient(), LIVE_FORM_SNAPSHOT, "req_impact", definition,
                                "Critical")
    assert "live options: Low, Medium, High" in str(exc.value)
