"""Authentication verification service for all credential types."""

import logging
from typing import Optional

from .credentials import CredentialType

logger = logging.getLogger("cli_tools.auth_verifier")


class AuthVerifier:
    """Verifies authentication across all configured credential types.

    Produces a per-credential-type breakdown so that multi-type CLIs
    (e.g. OAuth + browser session) can report the state of each type
    independently. The top-level `authenticated` field is True when any
    configured credential pathway authenticates — a type is considered
    configured only when its `credentials_saved` is True. This matches
    `BaseConfig.has_credentials()` OR semantic and prevents false
    negatives when one listed type is unused or has no session file.
    """

    OAUTH_TYPES = frozenset({
        CredentialType.OAUTH,
        CredentialType.OAUTH_AUTHORIZATION_CODE,
    })
    BROWSER_TYPES = frozenset({
        CredentialType.BROWSER_SESSION,
    })
    # Types verified via config.test_connection() — everything not OAuth or browser
    API_TYPES = frozenset({
        CredentialType.API_KEY,
        CredentialType.PERSONAL_ACCESS_TOKEN,
        CredentialType.USERNAME_PASSWORD,
        CredentialType.CUSTOM,
    })

    def __init__(self, config, api_test_handler=None):
        self.config = config
        self._api_test_handler = api_test_handler

    def verify(self) -> dict:
        """Run authentication checks and return a per-credential-type report.

        Returns dict with:
          authenticated     - bool: True when ANY credential type that has
                              `credentials_saved=True` also authenticates. A
                              type with no saved credentials is ignored for
                              this roll-up (it is not "configured" yet).
          credential_types  - dict mapping CredentialType.value to a per-type
                              result dict. Each type block contains:
              authenticated     - bool: did this specific type verify?
              credentials_saved - bool: are the static credentials or session
                                        for this type populated?
              oauth_status      - OAuth types only. "valid"|"refreshed"|
                                  "expired"|"no_token"
              browser_session   - Browser types only. bool: live session?
              browser_available - Browser types only. bool: can we probe?
              api_test          - API/custom types only. "passed"|"failed: ..."|
                                  "skipped". Extra handler fields (e.g. "email")
                                  are merged into the same block.
        """
        cred_types = self.config.CREDENTIAL_TYPES
        type_blocks = {ct.value: self._verify_single_type(ct) for ct in cred_types}

        configured = [b for b in type_blocks.values() if b.get("credentials_saved")]
        all_ok = any(b["authenticated"] for b in configured) if configured else False

        return {
            "authenticated": all_ok,
            "credential_types": type_blocks,
        }

    def _verify_single_type(self, ct: CredentialType) -> dict:
        """Verify one credential type and return its result block.

        Every credential type performs a LIVE verification round-trip
        against the underlying service when the credentials are saved.
        Filesystem state ("we have a token", "we have a session marker")
        is never used as proof of being authenticated — credentials on
        disk can be revoked, expired, or rotated server-side at any time
        without our knowledge. ``auth status`` and ``auth login`` MUST
        report ground truth, not cached belief.
        """
        if ct in self.OAUTH_TYPES:
            if not getattr(self.config, "OAUTH_TOKEN_EXPIRES", True):
                # Non-expiring OAuth (e.g. OAuth 1.0a): there is no
                # token-refresh check, so the only way to verify the
                # credentials are still valid is a live API round-trip.
                credentials_saved = self._has_static_oauth_credentials()
                block = {"credentials_saved": credentials_saved}
                if not credentials_saved:
                    block["oauth_status"] = "no_token"
                    block["authenticated"] = False
                    return block

                api_result = self._check_api()
                if api_result is None:
                    # No live test handler implemented. Report saved-only
                    # so callers can see credentials_saved=True without us
                    # falsely claiming live verification succeeded.
                    block["oauth_status"] = "saved"
                    block["api_test"] = "skipped: no test handler"
                    block["authenticated"] = False
                    return block

                api_test_val = api_result.get("api_test", "skipped")
                block["api_test"] = api_test_val
                for k, v in api_result.items():
                    if k != "api_test":
                        block[k] = v
                authenticated = api_test_val == "passed"
                block["oauth_status"] = "valid" if authenticated else "invalid"
                block["authenticated"] = authenticated
                return block

            block = {"credentials_saved": self.config.has_credentials()}
            status = self._check_oauth()
            block["oauth_status"] = status
            if status not in ("valid", "refreshed"):
                block["authenticated"] = False
                return block

            api_result = self._check_api()
            if api_result is None:
                block["authenticated"] = True
                return block

            api_test_val = api_result.get("api_test", "skipped")
            block["api_test"] = api_test_val
            for k, v in api_result.items():
                if k != "api_test":
                    block[k] = v
            block["authenticated"] = api_test_val == "passed"
            if not block["authenticated"]:
                block["oauth_status"] = "invalid"
            return block

        if ct in self.BROWSER_TYPES:
            browser_check = self._check_browser()
            if browser_check is None:
                return {"credentials_saved": False, "authenticated": False}
            block = {
                "credentials_saved": browser_check["has_session"],
                "browser_session": browser_check["authenticated"],
                "browser_available": browser_check["available"],
                "authenticated": browser_check["authenticated"],
            }
            if not block["authenticated"]:
                return block

            if getattr(self.config, "BROWSER_SESSION_REQUIRES_API_TEST", False) is not True:
                return block

            api_result = self._check_api()
            if api_result is None:
                return block

            api_test_val = api_result.get("api_test", "skipped")
            block["api_test"] = api_test_val
            for k, v in api_result.items():
                if k != "api_test":
                    block[k] = v
            block["authenticated"] = api_test_val == "passed"
            return block

        # API-capable types (API_TYPES + CUSTOM)
        block = {"credentials_saved": self.config.has_credentials()}
        if not block["credentials_saved"]:
            block["authenticated"] = False
            return block

        api_result = self._check_api()
        if api_result is None:
            # No test implemented — accept as authenticated since creds are set
            block["authenticated"] = True
            return block

        api_test_val = api_result.get("api_test", "skipped")
        block["api_test"] = api_test_val
        for k, v in api_result.items():
            if k != "api_test":
                block[k] = v
        block["authenticated"] = api_test_val == "passed"
        return block

    def _has_static_oauth_credentials(self) -> bool:
        """Return whether non-expiring OAuth credentials are complete."""
        fields = getattr(
            self.config,
            "OAUTH_STATIC_REQUIRED_FIELDS",
            ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN"),
        )
        return all(self.config._get(field) for field in fields)

    def _check_oauth(self) -> str:
        """Check OAuth token expiry, attempt refresh if needed."""
        if not self.config.access_token:
            return "no_token"
        from .token_manager import TokenManager
        tm = TokenManager(self.config)
        if not tm.is_expired():
            return "valid"
        try:
            tm.force_refresh()
            return "refreshed"
        except Exception:
            return "expired"

    def _check_api(self) -> Optional[dict]:
        """Test API connectivity via handler or config.test_connection().

        Returns:
            dict with at minimum {"api_test": "passed"|"failed: ..."|"skipped"},
            plus any extra fields returned by the handler (e.g., "email"),
            or None if no test is implemented.
        """
        # Custom handler takes priority (used by auth_test)
        if self._api_test_handler:
            try:
                api_result = self._api_test_handler(self.config)
                if not isinstance(api_result, dict):
                    return {"api_test": "skipped"}
                api_result.setdefault("api_test", "skipped")
                return api_result
            except Exception as e:
                return {"api_test": f"failed: {e}"}

        # Auto-detect test_connection override
        from .config import BaseConfig
        config_test_connection = getattr(type(self.config), "test_connection", None)
        if config_test_connection is None or config_test_connection is BaseConfig.test_connection:
            return None  # No test implemented - can't verify
        try:
            r = self.config.test_connection()
            if r is None:
                return None
            if not isinstance(r, dict):
                return {"api_test": "skipped"}
            r.setdefault("api_test", "skipped")
            return r
        except Exception as e:
            return {"api_test": f"failed: {e}"}

    def _check_browser(self) -> Optional[dict]:
        """Check browser session via a LIVE round-trip.

        On-disk profile state (persistent Chromium user-data-dir under
        ``chromium-profile/Default/``) is necessary but NOT sufficient:
        cookies can be invalidated server-side at any time. The only
        accurate way to report whether the browser session is currently
        usable is to navigate to ``AUTH_CHECK_URL`` and inspect the live
        page — what ``BrowserAutomation.is_authenticated()`` does.
        ``auth status`` MUST report ground truth, not on-disk belief, so
        it performs the live check unconditionally.

        Returns dict with 'authenticated', 'available', and 'has_session'
        keys, or None if no browser is configured.

        - ``has_session`` reflects the on-disk profile (what we have, from
          ``config.has_saved_session()``).
        - ``authenticated`` reflects the live round-trip (what works).

        When ``has_session`` is False there is nothing to live-check, so
        the live probe is skipped. The browser is closed after the live
        check so this method never leaks a running browser daemon.
        """
        browser = self.config.get_browser()
        if browser is None:
            return None
        try:
            has_session = bool(self.config.has_saved_session())
        except Exception:
            return {"authenticated": False, "available": False, "has_session": False}

        if not has_session:
            return {"authenticated": False, "available": False, "has_session": False}

        try:
            try:
                live = browser.is_authenticated()
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
        except Exception:
            return {"authenticated": False, "available": False, "has_session": True}

        authenticated = bool(live)
        available = bool(getattr(live, "available", True))
        return {
            "authenticated": authenticated,
            "available": available,
            "has_session": has_session,
        }
