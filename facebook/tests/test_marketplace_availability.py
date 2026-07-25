"""Offline tests for the Marketplace fail-loud auth gate and availability mapping.

These tests never touch a live browser or Facebook login. They exercise:
  - ``FacebookClient._assert_marketplace_authenticated`` deciding auth by
    AUTH STATE (the ``c_user`` cookie plus login-redirect / login-form
    corroboration), never by result count, so an empty-but-authenticated
    search passes while a login-walled page fails loudly with the exact
    re-auth remediation;
  - the pure ``_derive_availability`` signal -> string mapping;
  - ``MarketplaceListing`` accepting the new ``availability`` field.

The fake page objects reproduce only the surface the assertion touches: the
shared ``BrowserHarnessService`` accessors ``cookie_list()`` and ``url`` plus
``evaluate()`` for the login-form probe. Driving the real helpers this way
covers ``_page_has_c_user`` / ``_page_has_login_form``; a second block drives
``_assert_marketplace_authenticated`` directly via monkeypatched helpers.
"""
import unittest

from cli_tools_shared.exceptions import ClientError

from facebook_cli.client import FacebookClient
from facebook_cli.models import MarketplaceListing

REMEDIATION = "Run 'facebook auth login --force' to re-authenticate."
AUTHED_COOKIES = [
    {"name": "datr", "value": "abc"},
    {"name": "c_user", "value": "100012345678901"},
    {"name": "xs", "value": "def"},
]
LOGGED_OUT_COOKIES = [
    {"name": "datr", "value": "abc"},
    {"name": "wd", "value": "1280x800"},
]


class _FakeMarketplacePage:
    """Minimal stand-in for the shared BrowserHarnessService page object.

    Exposes exactly the accessors the marketplace auth assertion reads:
    ``cookie_list()`` (CDP-style ``[{"name", "value", ...}]``), the ``url``
    attribute, and ``evaluate()`` for the login-form probe.
    """

    def __init__(self, *, cookies, url, has_login_form=False):
        self._cookies = cookies
        self.url = url
        self._has_login_form = has_login_form

    def cookie_list(self):
        return self._cookies

    def evaluate(self, js, arg=None):
        # The only evaluate the assertion runs is the login-form probe.
        return self._has_login_form


class AssertMarketplaceAuthenticatedTests(unittest.TestCase):
    def setUp(self):
        self.client = FacebookClient()
        self.url = (
            "https://www.facebook.com/marketplace/evansville/search/?query=lego"
        )

    def test_authenticated_empty_search_page_does_not_raise(self):
        # c_user present, no login redirect, no login form -> authenticated even
        # if the search returned nothing. Must NOT raise.
        page = _FakeMarketplacePage(cookies=AUTHED_COOKIES, url=self.url)
        self.client._assert_marketplace_authenticated(page, self.url, "Marketplace (test)")

    def test_missing_c_user_cookie_raises_with_remediation(self):
        page = _FakeMarketplacePage(cookies=LOGGED_OUT_COOKIES, url=self.url)
        with self.assertRaises(ClientError) as ctx:
            self.client._assert_marketplace_authenticated(page, self.url, "Marketplace (test)")
        message = str(ctx.exception)
        self.assertIn("facebook auth login --force", message)
        self.assertTrue(message.endswith(REMEDIATION), message)

    def test_empty_cookie_value_is_not_authenticated(self):
        # A present-but-empty c_user value must not count as authenticated.
        page = _FakeMarketplacePage(
            cookies=[{"name": "c_user", "value": ""}], url=self.url
        )
        with self.assertRaises(ClientError) as ctx:
            self.client._assert_marketplace_authenticated(page, self.url, "Marketplace (test)")
        self.assertIn("facebook auth login --force", str(ctx.exception))

    def test_login_form_present_raises_even_with_stale_cookie(self):
        page = _FakeMarketplacePage(
            cookies=AUTHED_COOKIES, url=self.url, has_login_form=True
        )
        with self.assertRaises(ClientError) as ctx:
            self.client._assert_marketplace_authenticated(page, self.url, "Marketplace (test)")
        message = str(ctx.exception)
        self.assertIn("login form present: True", message)
        self.assertTrue(message.endswith(REMEDIATION), message)

    def test_login_redirect_url_raises_even_with_stale_cookie(self):
        page = _FakeMarketplacePage(
            cookies=AUTHED_COOKIES,
            url="https://www.facebook.com/login/?next=/marketplace/",
        )
        with self.assertRaises(ClientError) as ctx:
            self.client._assert_marketplace_authenticated(page, self.url, "Marketplace (test)")
        message = str(ctx.exception)
        self.assertIn("login redirect: True", message)
        self.assertTrue(message.endswith(REMEDIATION), message)

    def test_checkpoint_redirect_url_raises(self):
        page = _FakeMarketplacePage(
            cookies=AUTHED_COOKIES,
            url="https://www.facebook.com/checkpoint/?next",
        )
        with self.assertRaises(ClientError) as ctx:
            self.client._assert_marketplace_authenticated(page, self.url, "Marketplace item 123")
        self.assertIn("facebook auth login --force", str(ctx.exception))

    def test_surface_and_requested_url_included_in_message(self):
        page = _FakeMarketplacePage(cookies=LOGGED_OUT_COOKIES, url="")
        with self.assertRaises(ClientError) as ctx:
            self.client._assert_marketplace_authenticated(
                page, self.url, "Marketplace item 999"
            )
        message = str(ctx.exception)
        self.assertIn("Marketplace item 999", message)
        self.assertIn(self.url, message)


class AssertMarketplaceAuthenticatedMonkeypatchTests(unittest.TestCase):
    """Drive the assertion directly through its small helpers via monkeypatch."""

    class _UrlOnlyPage:
        def __init__(self, url):
            self.url = url

    def _client_with_helpers(self, *, has_c_user, has_login_form):
        client = FacebookClient()
        client._page_has_c_user = lambda page: has_c_user
        client._page_has_login_form = lambda page: has_login_form
        return client

    def test_helpers_report_authenticated(self):
        client = self._client_with_helpers(has_c_user=True, has_login_form=False)
        page = self._UrlOnlyPage("https://www.facebook.com/marketplace/evansville/")
        # Must not raise.
        client._assert_marketplace_authenticated(page, "req-url", "Marketplace (test)")

    def test_helpers_report_no_c_user(self):
        client = self._client_with_helpers(has_c_user=False, has_login_form=False)
        page = self._UrlOnlyPage("https://www.facebook.com/marketplace/evansville/")
        with self.assertRaises(ClientError) as ctx:
            client._assert_marketplace_authenticated(page, "req-url", "Marketplace (test)")
        self.assertIn("facebook auth login --force", str(ctx.exception))


class PageHasCUserTests(unittest.TestCase):
    def test_true_when_c_user_present(self):
        page = _FakeMarketplacePage(cookies=AUTHED_COOKIES, url="")
        self.assertTrue(FacebookClient._page_has_c_user(page))

    def test_false_when_c_user_absent(self):
        page = _FakeMarketplacePage(cookies=LOGGED_OUT_COOKIES, url="")
        self.assertFalse(FacebookClient._page_has_c_user(page))

    def test_non_list_cookie_payload_raises(self):
        class _BadPage:
            def cookie_list(self):
                return {"cookies": []}

        with self.assertRaises(ClientError):
            FacebookClient._page_has_c_user(_BadPage())


class DeriveAvailabilityTests(unittest.TestCase):
    def test_sold_wins_over_everything(self):
        signals = {"soldText": True, "pendingText": True, "priceRendered": True}
        self.assertEqual(FacebookClient._derive_availability(signals), "Sold")

    def test_pending_when_not_sold(self):
        signals = {"soldText": False, "pendingText": True, "priceRendered": True}
        self.assertEqual(FacebookClient._derive_availability(signals), "Pending")

    def test_available_when_price_rendered(self):
        signals = {"soldText": False, "pendingText": False, "priceRendered": True}
        self.assertEqual(FacebookClient._derive_availability(signals), "Available")

    def test_none_when_no_signal(self):
        signals = {"soldText": False, "pendingText": False, "priceRendered": False}
        self.assertIsNone(FacebookClient._derive_availability(signals))

    def test_none_when_signals_not_a_dict(self):
        self.assertIsNone(FacebookClient._derive_availability(None))

    def test_missing_keys_default_to_none(self):
        # An empty signals dict (e.g. from the null-main fallback) yields None.
        self.assertIsNone(FacebookClient._derive_availability({}))


class MarketplaceListingAvailabilityTests(unittest.TestCase):
    def test_availability_defaults_to_none(self):
        listing = MarketplaceListing(item_id="1", title="x", url="/marketplace/item/1/")
        self.assertIsNone(listing.availability)
        self.assertIn("availability", listing.model_dump())

    def test_availability_accepts_string(self):
        listing = MarketplaceListing(
            item_id="1", title="x", url="/marketplace/item/1/", availability="Sold"
        )
        self.assertEqual(listing.availability, "Sold")
        self.assertEqual(listing.model_dump()["availability"], "Sold")


if __name__ == "__main__":
    unittest.main()
