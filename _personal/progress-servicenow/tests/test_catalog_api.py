"""Tests for the ServiceNow Service Catalog API helpers."""

import pytest
from cli_tools_shared.exceptions import ClientError

from progress_servicenow_cli import catalog_api


class FakePage:
    """Minimal stand-in for the shared browser page's ``evaluate``."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def evaluate(self, script, arg=None):
        self.calls.append(arg)
        return self._response


def _ok(text):
    return {"status": 200, "ok": True, "text": text, "token": True}


def test_get_item_returns_result_object():
    page = FakePage(_ok('{"result": {"sys_id": "abc", "name": "Thing"}}'))
    assert catalog_api.get_item(page, "abc")["name"] == "Thing"


def test_missing_user_token_fails_loudly():
    page = FakePage({"status": 200, "ok": True, "text": "{}", "token": False})
    with pytest.raises(ClientError, match="no g_ck user token"):
        catalog_api.get_item(page, "abc")


def test_http_error_fails_loudly_with_status_and_body():
    page = FakePage(
        {
            "status": 400,
            "ok": False,
            "text": '{"error":{"message":"Either Catalog Item is not valid"}}',
            "token": True,
        }
    )
    with pytest.raises(ClientError) as exc:
        catalog_api.get_item(page, "c9f3a854dbe5db0408f33a1b7c9619dc")
    assert "HTTP 400" in str(exc.value)
    assert "Either Catalog Item is not valid" in str(exc.value)


def test_resolve_item_sys_id_matches_exact_name():
    page = FakePage(
        _ok('{"result": [{"sys_id": "1", "name": "Development Database Request"},'
            ' {"sys_id": "2", "name": "Other Development Request"}]}')
    )
    assert catalog_api.resolve_item_sys_id(page, "Other Development Request") == "2"


def test_resolve_item_sys_id_fails_loudly_and_names_candidates():
    page = FakePage(_ok('{"result": [{"sys_id": "1", "name": "Development Database Request"}]}'))
    with pytest.raises(ClientError) as exc:
        catalog_api.resolve_item_sys_id(page, "Development Cloud Issue")
    message = str(exc.value)
    assert "Development Cloud Issue" in message
    assert "Development Database Request" in message
    assert "template refresh" in message


def test_resolve_item_sys_id_fails_loudly_on_empty_search():
    page = FakePage(_ok('{"result": []}'))
    with pytest.raises(ClientError, match="returned: nothing"):
        catalog_api.resolve_item_sys_id(page, "Anything")


@pytest.mark.parametrize(
    "variable_name,expected",
    [
        ("var_product", "product"),
        ("description__desc", "description"),
        ("ReqImpact", "req_impact"),
        ("cmdb_ci", "cmdb_ci"),
    ],
)
def test_field_key_is_deterministic(variable_name, expected):
    assert catalog_api.field_key({"name": variable_name}) == expected


def test_field_type_fails_loudly_on_unknown_servicenow_type():
    with pytest.raises(ClientError, match="friendly_type 'quantum_widget'"):
        catalog_api.field_type({"name": "x", "label": "X", "friendly_type": "quantum_widget"})


def test_flatten_variables_descends_into_containers(live_catalog_item):
    names = [v["name"] for v in catalog_api.flatten_variables(live_catalog_item["variables"])]
    assert names == ["var_product", "description__desc", "ReqImpact"]


def test_build_template_entry_captures_live_identifiers_and_options(live_catalog_item):
    entry = catalog_api.build_template_entry(live_catalog_item)

    assert entry["name"] == "Other Development Request"
    assert entry["sys_id"] == "838c9810dbe5db0408f33a1b7c961930"
    assert entry["url"] == "?id=sc_cat_item&sys_id=838c9810dbe5db0408f33a1b7c961930"
    assert entry["category"] == "Development Support"
    assert sorted(entry["required_fields"]) == ["description", "product", "req_impact"]

    product = entry["fields"]["product"]
    assert product["label"] == "Product"
    assert product["type"] == "dropdown"
    assert product["variable"] == "var_product"
    assert "Sitefinity" in product["options"]

    description = entry["fields"]["description"]
    assert description["type"] == "textarea"
    assert description["sn_type"] == "html"


def test_template_key_for_slugifies_live_name():
    assert catalog_api.template_key_for("Other Development Request") == "other_development_request"
    assert (
        catalog_api.template_key_for("Application Assistance & Issue Reporting")
        == "application_assistance_issue_reporting"
    )
