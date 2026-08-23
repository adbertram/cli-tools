"""Offline tests for `marketplace list --delivery-method` and --location validation.

These tests never touch a live browser or Facebook login. They exercise:
  - the pure fulfillment-name -> Facebook `deliveryMethod` resolver, including
    its fail-fast rejects (unknown value; any real filter without --query),
  - `FacebookClient.search` URL construction for the `deliveryMethod` parameter,
  - the location-slug guard, against VERBATIM live URLs captured 2026-08-18 in
    `fixtures/marketplace_location_slugs.json`,
  - that the guard fires inside `_paginated_fetch` before any extraction and
    before the zero-result return.

The two JSON fixtures are verbatim live captures, not hand-written examples:
  - `marketplace_location_slugs.json` -- requested URL vs the URL Facebook's own
    `location.href` reported after the page settled, plus Facebook's own
    "Location:" filter button text. An unknown slug (`losangeles`,
    `zzzzznotaplace`) is rewritten to the slugless `/marketplace/category/...`
    surface and the button still names the account's home city (Evansville),
    which is the silent-wrong-city bug this guard exists to stop.
  - `marketplace_delivery_method_filter.json` -- Facebook's own Delivery method
    radio group and filter-button text read back after navigating with each
    candidate `deliveryMethod` token. It is the live proof that `shipping` and
    `local_pick_up` are the real tokens and that an invented token (`local`)
    leaves the filter in a broken, unchecked state.
"""
import json
import unittest
from pathlib import Path

import typer
from typer.testing import CliRunner

from cli_tools_shared.exceptions import ClientError

from facebook_cli.client import FacebookClient
from facebook_cli.commands.marketplace import (
    DELIVERY_METHOD_TO_PARAM,
    _resolve_delivery_method,
    app as marketplace_app,
)

FIXTURES = Path(__file__).parent / "fixtures"
LOCATION_SLUGS = json.loads((FIXTURES / "marketplace_location_slugs.json").read_text())
DELIVERY_FILTER = json.loads((FIXTURES / "marketplace_delivery_method_filter.json").read_text())


class LiveDeliveryTokenFixtureTests(unittest.TestCase):
    """The tokens the CLI sends are the ones Facebook confirmed live."""

    def _case(self, name):
        return DELIVERY_FILTER["cases"][name]

    def test_shipping_token_is_the_one_facebook_checked(self):
        case = self._case("shipping")
        self.assertIn(f"deliveryMethod={DELIVERY_METHOD_TO_PARAM['shipping']}", case["requested_url"])
        self.assertEqual(case["delivery_button"], ["Delivery method: Shipping"])
        checked = [r["text"] for r in case["delivery_radios"][:3] if r["checked"] == "true"]
        self.assertEqual(checked, ["Shipping"])

    def test_local_token_is_the_one_facebook_checked(self):
        case = self._case("local_pick_up")
        self.assertIn(f"deliveryMethod={DELIVERY_METHOD_TO_PARAM['local']}", case["requested_url"])
        self.assertEqual(case["delivery_button"], ["Delivery method: Local pickup"])
        checked = [r["text"] for r in case["delivery_radios"][:3] if r["checked"] == "true"]
        self.assertEqual(checked, ["Local pickup"])

    def test_all_sends_no_parameter_and_matches_facebooks_default(self):
        case = self._case("evansville-plain")
        self.assertIsNone(DELIVERY_METHOD_TO_PARAM["all"])
        self.assertNotIn("deliveryMethod", case["requested_url"])
        self.assertEqual(case["delivery_button"], ["Delivery method"])
        checked = [r["text"] for r in case["delivery_radios"][:3] if r["checked"] == "true"]
        self.assertEqual(checked, ["All"])

    def test_invented_token_breaks_facebooks_filter_so_it_is_never_sent(self):
        # `deliveryMethod=local` is NOT ignored by Facebook: it leaves every
        # radio unchecked and the button with an empty value. This is why the
        # CLI only ever sends a token it verified live.
        case = self._case("local")
        self.assertEqual(case["delivery_button"], ["Delivery method:"])
        checked = [r["text"] for r in case["delivery_radios"][:3] if r["checked"] == "true"]
        self.assertEqual(checked, [])
        self.assertNotIn("local", DELIVERY_METHOD_TO_PARAM.values())


class ResolveDeliveryMethodTests(unittest.TestCase):
    def test_all_resolves_to_no_parameter(self):
        self.assertIsNone(_resolve_delivery_method("all", "lego"))

    def test_all_is_allowed_without_query(self):
        self.assertIsNone(_resolve_delivery_method("all", None))

    def test_shipping_maps_to_facebook_shipping(self):
        self.assertEqual(_resolve_delivery_method("shipping", "lego"), "shipping")

    def test_local_maps_to_facebook_local_pick_up(self):
        self.assertEqual(_resolve_delivery_method("local", "lego"), "local_pick_up")

    def test_value_is_case_insensitive(self):
        self.assertEqual(_resolve_delivery_method("SHIPPING", "lego"), "shipping")
        self.assertEqual(_resolve_delivery_method("Local", "lego"), "local_pick_up")

    def test_unknown_value_raises_with_valid_values(self):
        with self.assertRaises(typer.BadParameter) as ctx:
            _resolve_delivery_method("nationwide", "lego")
        message = str(ctx.exception)
        self.assertIn("nationwide", message)
        for valid in ("all", "local", "shipping"):
            self.assertIn(valid, message)

    def test_shipping_without_query_is_rejected(self):
        with self.assertRaises(typer.BadParameter) as ctx:
            _resolve_delivery_method("shipping", None)
        self.assertIn("--query", str(ctx.exception))

    def test_local_without_query_is_rejected(self):
        with self.assertRaises(typer.BadParameter) as ctx:
            _resolve_delivery_method("local", "")
        self.assertIn("--query", str(ctx.exception))


class MarketplaceListRejectTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_cli_rejects_unknown_delivery_method_before_any_browser_work(self):
        result = self.runner.invoke(
            marketplace_app, ["list", "--query", "lego", "--delivery-method", "nationwide"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Invalid --delivery-method value 'nationwide'", result.output)

    def test_cli_rejects_delivery_method_without_query(self):
        result = self.runner.invoke(marketplace_app, ["list", "--delivery-method", "shipping"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--query", result.output)


class MarketplaceSearchDeliveryUrlTests(unittest.TestCase):
    def _client_capturing_url(self):
        client = FacebookClient()
        captured = {}

        def fake_paginated_fetch(url, status_msg, limit, location):
            captured["url"] = url
            captured["location"] = location
            return []

        client._paginated_fetch = fake_paginated_fetch
        return client, captured

    def test_search_appends_delivery_method_shipping(self):
        client, captured = self._client_capturing_url()
        client.search(query="LEGO", location="evansville", delivery_method="shipping")
        self.assertIn("deliveryMethod=shipping", captured["url"])

    def test_search_appends_delivery_method_local_pick_up(self):
        client, captured = self._client_capturing_url()
        client.search(query="LEGO", delivery_method="local_pick_up")
        self.assertIn("deliveryMethod=local_pick_up", captured["url"])

    def test_search_omits_delivery_method_when_none(self):
        client, captured = self._client_capturing_url()
        client.search(query="LEGO", delivery_method=None)
        self.assertNotIn("deliveryMethod", captured["url"])

    def test_search_passes_requested_location_for_validation(self):
        client, captured = self._client_capturing_url()
        client.search(query="LEGO", location="seattle", delivery_method="shipping")
        self.assertEqual(captured["location"], "seattle")

    def test_browse_passes_requested_location_for_validation(self):
        client, captured = self._client_capturing_url()
        client.browse(location="chicago")
        self.assertEqual(captured["location"], "chicago")


class ServedLocationSlugTests(unittest.TestCase):
    def test_search_url_slug_is_read_from_live_urls(self):
        for name in ("evansville-plain", "chicago", "seattle", "nyc"):
            case = LOCATION_SLUGS["search"][name]
            expected = case["requested_url"].split("/marketplace/")[1].split("/")[0]
            self.assertEqual(
                FacebookClient._served_location_slug(case["served_url"]), expected, name
            )

    def test_rejected_slug_urls_report_facebooks_slugless_segment(self):
        for name in ("losangeles-invalid", "notaplace-invalid"):
            case = LOCATION_SLUGS["search"][name]
            self.assertEqual(
                FacebookClient._served_location_slug(case["served_url"]), "category", name
            )

    def test_rejected_browse_url_reports_no_slug_at_all(self):
        case = LOCATION_SLUGS["browse"]["browse-losangeles-invalid"]
        self.assertIsNone(FacebookClient._served_location_slug(case["served_url"]))


class AssertRequestedLocationTests(unittest.TestCase):
    def _requested_slug(self, requested_url):
        return requested_url.split("/marketplace/")[1].split("/")[0]

    def test_every_live_valid_slug_passes(self):
        cases = list(LOCATION_SLUGS["search"].items()) + list(LOCATION_SLUGS["browse"].items())
        checked = 0
        for name, case in cases:
            if "invalid" in name:
                continue
            slug = self._requested_slug(case["requested_url"])
            FacebookClient._assert_requested_location(
                case["served_url"], slug, case["requested_url"]
            )
            checked += 1
        # evansville/chicago/seattle/nyc searches + evansville/chicago browses
        self.assertEqual(checked, 6)

    def test_live_invalid_search_slug_raises_and_names_the_slug(self):
        case = LOCATION_SLUGS["search"]["losangeles-invalid"]
        with self.assertRaises(ClientError) as ctx:
            FacebookClient._assert_requested_location(
                case["served_url"], "losangeles", case["requested_url"]
            )
        message = str(ctx.exception)
        self.assertIn("losangeles", message)
        self.assertIn(case["served_url"], message)

    def test_live_invalid_nonsense_slug_raises(self):
        case = LOCATION_SLUGS["search"]["notaplace-invalid"]
        with self.assertRaises(ClientError) as ctx:
            FacebookClient._assert_requested_location(
                case["served_url"], "zzzzznotaplace", case["requested_url"]
            )
        self.assertIn("zzzzznotaplace", str(ctx.exception))

    def test_live_invalid_browse_slug_raises(self):
        case = LOCATION_SLUGS["browse"]["browse-losangeles-invalid"]
        with self.assertRaises(ClientError) as ctx:
            FacebookClient._assert_requested_location(
                case["served_url"], "losangeles", case["requested_url"]
            )
        self.assertIn("losangeles", str(ctx.exception))

    def test_requesting_facebooks_own_slugless_segment_raises(self):
        # `--location category` would satisfy naive equality while returning
        # exactly the home-city inventory this guard exists to catch.
        served = "https://www.facebook.com/marketplace/category/search/?query=lego"
        with self.assertRaises(ClientError):
            FacebookClient._assert_requested_location(served, "category", served)

    def test_empty_served_url_raises(self):
        with self.assertRaises(ClientError):
            FacebookClient._assert_requested_location(
                "", "evansville", "https://www.facebook.com/marketplace/evansville/search/?query=x"
            )


class PaginatedFetchLocationGuardTests(unittest.TestCase):
    """The guard must fire before extraction and before the zero-result return."""

    def _client(self, served_url, no_results):
        client = FacebookClient()
        extracted = {"called": False}

        client._get_page = lambda url: object()
        client._dismiss_marketplace_login_dialog = lambda page: None
        client._assert_marketplace_authenticated = lambda page, url, surface: None
        client._wait_for_marketplace_results = lambda page: {
            "url": served_url,
            "no_results": no_results,
            "empty_heading": 'No listings found for "lego" within 11 miles',
        }

        def fake_scroll_collect(*args, **kwargs):
            extracted["called"] = True
            return []

        client._scroll_collect = fake_scroll_collect
        client._install_delivery_capture = lambda page: None
        return client, extracted

    def test_rejected_slug_raises_before_extraction(self):
        case = LOCATION_SLUGS["search"]["losangeles-invalid"]
        client, extracted = self._client(case["served_url"], no_results=False)
        with self.assertRaises(ClientError) as ctx:
            client._paginated_fetch(
                url=case["requested_url"], status_msg="test", limit=10, location="losangeles"
            )
        self.assertIn("losangeles", str(ctx.exception))
        self.assertFalse(extracted["called"])

    def test_rejected_slug_is_not_reported_as_a_zero_result_search(self):
        case = LOCATION_SLUGS["search"]["losangeles-invalid"]
        client, _ = self._client(case["served_url"], no_results=True)
        with self.assertRaises(ClientError):
            client._paginated_fetch(
                url=case["requested_url"], status_msg="test", limit=10, location="losangeles"
            )

    def test_valid_slug_zero_result_search_still_returns_empty(self):
        case = LOCATION_SLUGS["search"]["evansville-plain"]
        client, extracted = self._client(case["served_url"], no_results=True)
        result = client._paginated_fetch(
            url=case["requested_url"], status_msg="test", limit=10, location="evansville"
        )
        self.assertEqual(result, [])
        self.assertFalse(extracted["called"])


if __name__ == "__main__":
    unittest.main()
