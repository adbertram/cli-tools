"""Offline tests for the marketplace `--sort` / `--desc` Source-CLI Sort Standard.

These tests never touch a live browser or Facebook login. They exercise:
  - the pure sort-field -> Facebook `sortBy` resolver,
  - the fail-fast reject path for unknown / unsupported sort values (both the
    resolver and the `marketplace list` CLI command),
  - the URL construction in FacebookClient.search / .browse (via a stubbed
    _paginated_fetch so no navigation happens).
"""
import unittest

import typer
from typer.testing import CliRunner

from facebook_cli.client import FacebookClient
from facebook_cli.commands.marketplace import (
    SORT_FIELD_TO_SORTBY,
    _resolve_sort_by,
    app as marketplace_app,
)


class ResolveSortByTests(unittest.TestCase):
    def test_newest_natural_maps_to_creation_time_descend(self):
        self.assertEqual(_resolve_sort_by("newest", False), "creation_time_descend")

    def test_default_field_is_newest(self):
        # The command default is "newest"; resolving it must be newest-first.
        self.assertEqual(SORT_FIELD_TO_SORTBY["newest"]["natural"], "creation_time_descend")

    def test_price_natural_maps_to_price_ascend(self):
        self.assertEqual(_resolve_sort_by("price", False), "price_ascend")

    def test_price_desc_maps_to_price_descend(self):
        self.assertEqual(_resolve_sort_by("price", True), "price_descend")

    def test_sort_field_is_case_insensitive(self):
        self.assertEqual(_resolve_sort_by("NEWEST", False), "creation_time_descend")
        self.assertEqual(_resolve_sort_by("Price", True), "price_descend")

    def test_unknown_sort_value_raises_with_valid_values(self):
        with self.assertRaises(typer.BadParameter) as ctx:
            _resolve_sort_by("bogus", False)
        message = str(ctx.exception)
        self.assertIn("bogus", message)
        self.assertIn("newest", message)
        self.assertIn("price", message)

    def test_newest_desc_is_rejected_no_oldest_first(self):
        with self.assertRaises(typer.BadParameter) as ctx:
            _resolve_sort_by("newest", True)
        self.assertIn("oldest", str(ctx.exception).lower())


class MarketplaceListRejectTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_cli_rejects_unknown_sort_before_any_browser_work(self):
        result = self.runner.invoke(marketplace_app, ["list", "--sort", "bogus"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Invalid --sort value 'bogus'", result.output)

    def test_cli_rejects_newest_desc(self):
        result = self.runner.invoke(marketplace_app, ["list", "--sort", "newest", "--desc"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not supported", result.output)


class MarketplaceSearchUrlTests(unittest.TestCase):
    def _client_capturing_url(self):
        client = FacebookClient()
        captured = {}

        def fake_paginated_fetch(url, status_msg, limit):
            captured["url"] = url
            captured["limit"] = limit
            return []

        client._paginated_fetch = fake_paginated_fetch
        return client, captured

    def test_search_appends_sortby_creation_time_descend(self):
        client, captured = self._client_capturing_url()
        client.search(query="LEGO", location="evansville", sort_by="creation_time_descend", limit=10)
        self.assertIn("sortBy=creation_time_descend", captured["url"])
        self.assertIn("query=LEGO", captured["url"])
        self.assertIn("/marketplace/evansville/search/", captured["url"])

    def test_search_appends_sortby_price_descend(self):
        client, captured = self._client_capturing_url()
        client.search(query="couch", sort_by="price_descend")
        self.assertIn("sortBy=price_descend", captured["url"])

    def test_search_omits_sortby_when_none(self):
        client, captured = self._client_capturing_url()
        client.search(query="LEGO", sort_by=None)
        self.assertNotIn("sortBy", captured["url"])

    def test_browse_appends_sortby(self):
        client, captured = self._client_capturing_url()
        client.browse(location="chicago", sort_by="creation_time_descend")
        self.assertIn("sortBy=creation_time_descend", captured["url"])
        self.assertIn("/marketplace/chicago/", captured["url"])

    def test_browse_omits_sortby_when_none(self):
        client, captured = self._client_capturing_url()
        client.browse(location="chicago", sort_by=None)
        self.assertNotIn("sortBy", captured["url"])


if __name__ == "__main__":
    unittest.main()
