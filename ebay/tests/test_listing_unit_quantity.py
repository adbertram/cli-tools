"""Unit Quantity comes from --weight only when the aspects opt in with Unit Type."""

import json
from unittest.mock import MagicMock, patch

import pytest

from ebay_cli.commands import listings

BASE_ARGS = [
    "create",
    "--sku", "SKU-UNIT-QTY",
    "--title", "Unit quantity test",
    "--description", "Testing Unit Quantity",
    "--price", "9.99",
    "--category", "183454",
    "--format", "FIXED_PRICE",
    "--fulfillment-policy", "F-POLICY",
    "--payment-policy", "P-POLICY",
    "--return-policy", "R-POLICY",
    "--location", "warehouse-1",
    "--weight", "2.5",
    "--dimensions", "10x8x6",
    "--publish",
]


def _create(runner, extra_args, template_record=None):
    client = MagicMock()
    client.create_offer.return_value = {"offerId": "OFFER-1"}
    client.publish_offer.return_value = {"listingId": "110000000001"}
    storage = MagicMock()
    storage.return_value.get_template.return_value = template_record

    with patch("ebay_cli.commands.listings.get_client", return_value=client), patch(
        "ebay_cli.commands.listings.TemplateStorage", storage
    ), patch(
        "ebay_cli.commands.listings.validate_template_data", return_value=(True, [])
    ):
        result = runner.invoke(listings.app, [*BASE_ARGS, *extra_args])

    assert result.exit_code == 0, result.stderr
    return client.create_or_update_inventory_item.call_args.args[1]["product"]["aspects"]


def test_weight_never_adds_unit_quantity_without_unit_type(runner):
    aspects = _create(runner, ["--aspects", json.dumps({"Brand": ["Ultra PRO"]})])

    assert aspects == {"Brand": ["Ultra PRO"]}


@pytest.mark.parametrize("weight_source", ["template", "aspects"])
def test_weight_sets_unit_quantity_when_unit_type_opts_in(runner, weight_source):
    if weight_source == "template":
        template = {"itemSpecifics": {"Brand": ["LEGO"], "Unit Type": ["lb"]}}
        aspects = _create(runner, ["--template", "lego-bulk-auction"], {"template": template})
    else:
        aspects = _create(
            runner, ["--aspects", json.dumps({"Brand": ["LEGO"], "Unit Type": ["lb"]})]
        )

    assert aspects == {"Brand": ["LEGO"], "Unit Type": ["lb"], "Unit Quantity": ["2.5"]}
