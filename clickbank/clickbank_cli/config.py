"""Configuration management for ClickBank CLI.

ClickBank exposes two completely separate surfaces that the CLI talks to:

* The public REST API at ``api.clickbank.com/rest/1.3`` -- authenticated with
  an ``API_KEY`` and used by the ``orders``, ``products``, and ``quickstats``
  commands.  These commands manage *your own* ClickBank account.
* The public-but-undocumented marketplace GraphQL endpoint at
  ``accounts.clickbank.com/graphql`` -- not auth-gated, but Cloudflare blocks
  vanilla HTTP clients.  Used by the ``marketplace`` commands to search the
  catalog of products available for affiliate promotion.  Requests are issued
  from inside a persistent Playwright session so they carry a real browser
  fingerprint past the WAF.

The marketplace surface does not require credentials; the BROWSER_SESSION
credential type below just expresses "we keep a persistent browser session
around for marketplace commands".  The REST API key is independent of the
browser, hence the ``has_api_credentials`` override -- the API client must be
constructible even before the marketplace session is established.
"""
from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """ClickBank CLI configuration (REST API key + marketplace browser session)."""

    DIST_NAME = "clickbank-cli"
    CREDENTIAL_TYPES = [CredentialType.API_KEY, CredentialType.BROWSER_SESSION]
    DEFAULT_BASE_URL = "https://api.clickbank.com/rest/1.3"
    LOGIN_INSTRUCTIONS = (
        "ClickBank uses two separate credentials:\n"
        "1. REST API key (orders, products, quickstats):\n"
        "   Open https://support.clickbank.com/en/articles/10535400-clickbank-apis\n"
        "   from your primary account's API Management area, create a key with\n"
        "   the roles you need, and paste the raw API key when prompted below.\n"
        "2. Marketplace browser session (marketplace search/categories/product):\n"
        "   A persistent Chromium window opens to ClickBank.  The marketplace\n"
        "   is public so you do NOT have to sign in -- just dismiss any cookie\n"
        "   banner and press Enter in the terminal.  If you want hoplinks to\n"
        "   auto-fill your affiliate nickname, sign in to your ClickBank\n"
        "   account in that window before pressing Enter."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # --- Dual-auth credential gates ----------------------------------------------

    def has_api_credentials(self) -> bool:
        """REST API client gate -- only require the API key.

        Without this override the shared ``has_credentials()`` would refuse to
        construct the REST client whenever the marketplace browser session is
        missing, even though the REST API does not need a browser at all.
        """
        return bool(self.api_key)

    # --- Storage (required by @cached and BrowserAutomation) ---------------------

    @property
    def storage_dir(self):
        """Profile-aware storage directory for runtime data.

        Required by the shared ``@cached`` decorator -- cached method
        returns live at ``<storage_dir>/cache/<method>_<hash>.json``.
        """
        return self.get_profile_data_dir()

    # --- Affiliate nickname (used to build hoplinks) -----------------------------

    @property
    def affiliate_nickname(self) -> Optional[str]:
        """Affiliate ClickBank account nickname used as ``affiliate=`` in hoplinks.

        Optional.  When set, ``clickbank marketplace search`` and
        ``clickbank marketplace product`` emit fully-formed hoplinks like::

            https://hop.clickbank.net/?affiliate=<your-nick>&vendor=<vendor>

        When unset, the same field is emitted with a literal ``{affiliate}``
        placeholder so the caller knows to substitute it later.  Read from
        ``CLICKBANK_AFFILIATE_NICKNAME`` in the profile env file.
        """
        return self._get("AFFILIATE_NICKNAME") or None

    # --- Browser wiring ----------------------------------------------------------

    def get_browser(self):
        """Return the ClickBank ``BrowserAutomation`` subclass.

        AuthVerifier uses this in ``auth status`` and ``auth login`` to drive
        the persistent Playwright session for the public marketplace.
        """
        from .browser import ClickBankBrowser
        return ClickBankBrowser(self)

    def test_connection(self) -> Optional[dict]:
        """Verify the API key with a lightweight authenticated request."""
        from .client import ClickBankClient, ClientError

        try:
            accounts = ClickBankClient(config=self, max_retries=0).list_quickstats_accounts()
            return {
                "api_test": "passed",
                "account_count": len(accounts),
                "accounts": [account.nickName for account in accounts if account.nickName],
            }
        except ClientError as exc:
            return {"api_test": f"failed: {exc}"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Get or create a config instance for the given profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
