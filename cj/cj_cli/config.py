"""Configuration management for CJ Affiliate CLI.

CJ uses TWO authentication mechanisms because the public APIs and the
publisher Marketplace UI are split across different surfaces:

- ``PERSONAL_ACCESS_TOKEN`` -- CJ Personal Access Token used as a Bearer
  credential against the REST and GraphQL APIs
  (``advertiser-lookup.api.cj.com``, ``link-search.api.cj.com``,
  ``ads.api.cj.com``).  Generated from
  https://members.cj.com/member/PersonalAccessTokens/tokens.cj.
- ``BROWSER_SESSION`` -- a persistent Playwright session signed in to
  https://members.cj.com.  Required for actions that have no public API
  endpoint, specifically applying to (joining) an advertiser program.

The publisher account id (CJ "company id" / ``requestor-cid``) is read
from ``CJ_PUBLISHER_ID`` so the same client code can target a different
publisher account by changing one env var without touching credentials.
"""

from typing import Optional

from cli_tools_shared.config import BaseConfig, resolve_tool_dir
from cli_tools_shared.credentials import CredentialType


class Config(BaseConfig):
    """CJ configuration with dual auth (PAT for APIs + browser for Marketplace)."""

    DIST_NAME = "cj-cli"
    CREDENTIAL_TYPES = [
        CredentialType.PERSONAL_ACCESS_TOKEN,
        CredentialType.BROWSER_SESSION,
    ]
    DEFAULT_BASE_URL = "https://advertiser-lookup.api.cj.com"
    LOGIN_INSTRUCTIONS = (
        "CJ requires two credentials:\n"
        "1. Generate a Personal Access Token at\n"
        "   https://members.cj.com/member/PersonalAccessTokens/tokens.cj\n"
        "   and paste it at the PAT prompt below (used for read APIs).\n"
        "2. After the PAT step the CLI will open a browser to\n"
        "   https://members.cj.com/member/login.  Sign in there with your\n"
        "   publisher account so the CLI can apply to advertiser programs\n"
        "   (no public API exists for the join action)."
    )

    def __init__(self, profile: Optional[str] = None):
        super().__init__(
            tool_dir=resolve_tool_dir(self.DIST_NAME),
            profile=profile,
        )

    # --- Dual-auth credential gates ------------------------------------------------

    def has_api_credentials(self) -> bool:
        """API client gate -- only require the PAT, not the browser session.

        The REST client must be usable even before the browser session is
        established (and vice versa).  Without this override the shared
        ``has_credentials()`` would refuse to construct the API client
        whenever the browser session is missing, even though the read APIs
        do not need a browser at all.
        """
        return bool(self.personal_access_token)

    # --- Publisher account ---------------------------------------------------------

    @property
    def publisher_id(self) -> str:
        """CJ publisher company id (a.k.a. ``requestor-cid``).

        Required by every advertiser-lookup and link-search request.  Set
        via ``CJ_PUBLISHER_ID`` in the profile env file.  Fail-fast: a
        missing publisher id is a configuration bug, not a runtime
        condition to be masked with a fallback.
        """
        value = self._get("PUBLISHER_ID")
        if not value:
            raise ValueError(
                "CJ_PUBLISHER_ID is not configured for profile "
                f"'{self.profile or 'default'}'. "
                "Set it in the profile env file or run 'cj auth login'."
            )
        return value

    @property
    def website_id(self) -> str:
        """CJ publisher *website* id (per-property identifier).

        Distinct from ``publisher_id`` (the publisher company id /
        requestor-cid).  CJ's Link Search API requires the website-id
        as a ``website-id`` query parameter because a publisher
        company can register multiple websites under one account and
        each website has its own creative inventory.

        Required by ``cj links list`` and ``cj links get``.  Read from
        ``CJ_WEBSITE_ID`` in the profile env file.  Fail-fast: passing
        the publisher_id where a website-id is expected returns HTTP
        400 ``Website id specified does not match your account``.

        Find your website-id at
        https://members.cj.com/member/<account-id>/publisher/Properties/edit
        -- the URL row for each property exposes its numeric id.
        """
        value = self._get("WEBSITE_ID")
        if not value:
            raise ValueError(
                "CJ_WEBSITE_ID is not configured for profile "
                f"'{self.profile or 'default'}'. "
                "Set it in the profile env file -- find your website-id "
                "at https://members.cj.com/member/<account-id>/publisher/Properties/edit"
            )
        return value

    @property
    def publisher_account_id(self) -> str:
        """CJ publisher *account* id (the numeric segment in member URLs).

        Distinct from ``publisher_id`` -- this is the integer that
        appears in the URL path of every authenticated member page,
        e.g. ``https://members.cj.com/member/<account-id>/publisher/``.
        CJ uses it as the first segment of every tracking URL the
        publisher generates: deep links live at
        ``https://www.anrdoezrs.net/links/<account-id>/...`` and per-
        creative click URLs at
        ``https://www.dpbolvw.net/click-<account-id>-<link-id>``.

        Required by ``cj links deeplink``.  Read from
        ``CJ_PUBLISHER_ACCOUNT_ID`` in the profile env file.  Fail-fast:
        if not set, the deeplink command refuses to run rather than
        emit an unsigned URL that CJ will reject.  To find your account
        id, log in to https://members.cj.com and copy the digits between
        ``/member/`` and ``/publisher/`` from any authenticated page.
        """
        value = self._get("PUBLISHER_ACCOUNT_ID")
        if not value:
            raise ValueError(
                "CJ_PUBLISHER_ACCOUNT_ID is not configured for profile "
                f"'{self.profile or 'default'}'. "
                "Set it in the profile env file -- it is the numeric "
                "segment between '/member/' and '/publisher/' in any "
                "authenticated members.cj.com URL."
            )
        return value

    # --- Browser wiring ------------------------------------------------------------

    def get_browser(self):
        """Return the CJ ``BrowserAutomation`` subclass.

        AuthVerifier uses this in ``auth status`` and ``auth login`` to
        drive the persistent Playwright session for the CJ Marketplace.
        """
        from .browser import CJBrowser
        return CJBrowser(self)

    def test_connection(self) -> dict:
        """Verify the configured PAT can talk to advertiser-lookup.

        Builds an isolated :class:`CjClient` from ``self`` rather than the
        cached singleton so ``cj auth status --profile <other>`` validates
        the requested profile and never the default one.
        """
        from .client import CjClient
        client = CjClient(config=self)
        # One-record probe -- cheapest valid request the API supports.
        client.list_advertisers(relationship="joined", limit=1)
        return {"api_test": "passed", "method": "advertiser-lookup"}


_configs: dict = {}


def get_config(profile: Optional[str] = None) -> Config:
    """Return a cached ``Config`` instance for the requested profile."""
    key = profile or "_default"
    if key not in _configs:
        _configs[key] = Config(profile=profile)
    return _configs[key]
