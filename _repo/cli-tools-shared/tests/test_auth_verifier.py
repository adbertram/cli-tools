"""Unit tests for AuthVerifier service.

Validates that AuthVerifier correctly verifies authentication across all
credential types and produces the expected output fields.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cli_tools_shared.auth_verifier import AuthVerifier
from cli_tools_shared.credentials import CredentialType


# ---------------------------------------------------------------------------
# Helpers: mock config factories
# ---------------------------------------------------------------------------

def _make_config(cred_types, has_creds=True, browser=None, access_token=None,
                 has_saved_session=False):
    """Create a mock config with the given credential types.

    Uses BaseConfig as spec so type(config).test_connection resolves correctly
    for the AuthVerifier._check_api() auto-detection logic.

    ``has_saved_session`` controls ``config.has_saved_session()`` — the
    single source of truth for whether a persistent browser profile exists
    on disk for this config (replaces the old ``browser.has_session()``).
    """
    from cli_tools_shared.config import BaseConfig

    config = MagicMock(spec=BaseConfig)
    config.CREDENTIAL_TYPES = cred_types
    config.has_credentials.return_value = has_creds
    config.has_saved_session.return_value = has_saved_session
    config.get_browser.return_value = browser
    config.access_token = access_token
    config.base_url = "https://example.com"
    config.get_active_profile_name.return_value = "default"

    return config


# ---------------------------------------------------------------------------
# auth_commands.py uses AuthVerifier (source-level check)
# ---------------------------------------------------------------------------

def test_auth_commands_uses_auth_verifier():
    """auth_commands.py must import and use AuthVerifier, with no legacy functions."""
    import importlib.util
    spec = importlib.util.find_spec("cli_tools_shared.auth_commands")
    assert spec is not None, "cli_tools_shared.auth_commands not found"
    source = Path(spec.origin).read_text()

    assert "AuthVerifier" in source, (
        "auth_commands.py does not use AuthVerifier. "
        "Fix: Import AuthVerifier from cli_tools_shared.auth_verifier and use it in "
        "auth_status and auth_test commands."
    )
    assert "_check_browser_status" not in source, (
        "auth_commands.py still contains legacy _check_browser_status function. "
        "Fix: Remove it — browser checking is handled by AuthVerifier._check_browser()."
    )


# ---------------------------------------------------------------------------
# AuthVerifier.verify() output structure
# ---------------------------------------------------------------------------

class TestVerifyOutputFields:
    """Verify that AuthVerifier.verify() returns the expected per-credential-type shape."""

    def test_top_level_shape(self):
        """verify() must return {authenticated, credential_types: {...}}."""
        config = _make_config([CredentialType.API_KEY], has_creds=True)
        handler = lambda cfg: {"api_test": "passed"}
        result = AuthVerifier(config, api_test_handler=handler).verify()
        assert "authenticated" in result
        assert "credential_types" in result
        assert isinstance(result["credential_types"], dict)

    def test_credential_types_block_includes_credentials_saved(self):
        """Every credential_types block must include credentials_saved."""
        config = _make_config([CredentialType.API_KEY], has_creds=True)
        handler = lambda cfg: {"api_test": "passed"}
        result = AuthVerifier(config, api_test_handler=handler).verify()
        block = result["credential_types"]["api_key"]
        assert "credentials_saved" in block
        assert "authenticated" in block

    def test_browser_session_block_has_browser_session_field(self):
        """BROWSER_SESSION type must expose browser_session + browser_available in its block.

        ``auth status`` MUST live-verify the browser session — filesystem
        state is necessary but not sufficient. When ``has_session()``
        returns True, the verifier calls ``browser.is_authenticated()``
        and the live result is the source of truth for the block.
        """
        browser = MagicMock()
        browser.is_authenticated.return_value = True
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=True,
        )
        result = AuthVerifier(config).verify()
        block = result["credential_types"]["browser_session"]

        assert block["browser_session"] is True
        assert "browser_available" in block
        assert block["authenticated"] is True
        # Live check was performed — that's the whole point of auth status.
        browser.is_authenticated.assert_called_once_with()

    def test_browser_session_false_when_not_authenticated(self):
        """No session on disk → no live check needed → authenticated=False."""
        browser = MagicMock()
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=False,
        )
        result = AuthVerifier(config).verify()
        block = result["credential_types"]["browser_session"]
        assert block["browser_session"] is False
        assert block["authenticated"] is False
        assert result["authenticated"] is False
        # No on-disk session — skip the live probe.
        browser.is_authenticated.assert_not_called()

    def test_browser_session_files_exist_but_live_check_fails(self):
        """Saved session files but live check fails → authenticated=False.

        This is the exact contradiction users hit: ``has_session`` is True
        (we have files on disk) but the cookies are expired/revoked
        server-side. The live check must override the on-disk state and
        report not-authenticated, otherwise ``auth status`` lies and the
        next data command fails with a misleading 'session expired'.
        """
        browser = MagicMock()
        browser.is_authenticated.return_value = False
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=True,
        )
        result = AuthVerifier(config).verify()
        block = result["credential_types"]["browser_session"]
        # credentials_saved tracks the on-disk state.
        assert block["credentials_saved"] is True
        # authenticated tracks the live round-trip.
        assert block["browser_session"] is False
        assert block["browser_available"] is True
        assert block["authenticated"] is False
        assert result["authenticated"] is False
        browser.is_authenticated.assert_called_once_with()

    def test_browser_session_live_check_raises_returns_unauthenticated(self):
        """Live check raising must not crash auth status — report False."""
        browser = MagicMock()
        browser.is_authenticated.side_effect = RuntimeError("playwright crashed")
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=True,
        )
        result = AuthVerifier(config).verify()
        block = result["credential_types"]["browser_session"]
        assert block["credentials_saved"] is True
        assert block["browser_available"] is False
        assert block["authenticated"] is False
        assert result["authenticated"] is False

    def test_browser_session_ignores_api_test_handler_by_default_when_browser_probe_passes(self):
        """Browser-session auth is defined by the live browser probe by default."""
        browser = MagicMock()
        browser.is_authenticated.return_value = True
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=True,
        )

        handler = lambda cfg: {"api_test": "failed: request context invalid"}
        result = AuthVerifier(config, api_test_handler=handler).verify()
        block = result["credential_types"]["browser_session"]

        assert block["credentials_saved"] is True
        assert block["browser_session"] is True
        assert "api_test" not in block
        assert block["authenticated"] is True
        assert result["authenticated"] is True

    def test_browser_session_failed_api_test_overrides_passing_browser_probe_when_configured(self):
        """Browser-session CLIs may opt into a tool-specific API probe too."""
        browser = MagicMock()
        browser.is_authenticated.return_value = True
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=True,
        )
        config.BROWSER_SESSION_REQUIRES_API_TEST = True

        handler = lambda cfg: {"api_test": "failed: request context invalid"}
        result = AuthVerifier(config, api_test_handler=handler).verify()
        block = result["credential_types"]["browser_session"]

        assert block["credentials_saved"] is True
        assert block["browser_session"] is True
        assert block["api_test"] == "failed: request context invalid"
        assert block["authenticated"] is False
        assert result["authenticated"] is False

    def test_browser_session_passed_api_test_keeps_passing_browser_probe_authenticated(self):
        browser = MagicMock()
        browser.is_authenticated.return_value = True
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=True,
        )
        config.BROWSER_SESSION_REQUIRES_API_TEST = True

        handler = lambda cfg: {"api_test": "passed", "account": "ok"}
        result = AuthVerifier(config, api_test_handler=handler).verify()
        block = result["credential_types"]["browser_session"]

        assert block["credentials_saved"] is True
        assert block["browser_session"] is True
        assert block["api_test"] == "passed"
        assert block["account"] == "ok"
        assert block["authenticated"] is True
        assert result["authenticated"] is True

    def test_browser_session_ignores_api_test_handler_when_browser_probe_fails(self):
        """A global API test handler must not manufacture browser auth."""
        browser = MagicMock()
        browser.is_authenticated.return_value = False
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=True,
        )

        handler = lambda cfg: {"api_test": "passed"}
        result = AuthVerifier(config, api_test_handler=handler).verify()
        block = result["credential_types"]["browser_session"]

        assert block["credentials_saved"] is True
        assert block["browser_session"] is False
        assert "api_test" not in block
        assert block["authenticated"] is False
        assert result["authenticated"] is False

    def test_non_browser_clis_have_no_browser_block(self):
        """Non-browser CLIs must not include a browser_session key in credential_types."""
        config = _make_config([CredentialType.API_KEY], has_creds=True)
        handler = lambda cfg: {"api_test": "passed"}
        result = AuthVerifier(config, api_test_handler=handler).verify()
        assert "browser_session" not in result["credential_types"]

    def test_oauth_block_has_oauth_status(self):
        config = _make_config(
            [CredentialType.OAUTH],
            has_creds=True,
            access_token="fake-token",
        )
        with patch("cli_tools_shared.token_manager.TokenManager") as MockTM:
            MockTM.return_value.is_expired.return_value = False
            result = AuthVerifier(config).verify()

        block = result["credential_types"]["oauth"]
        assert block["oauth_status"] == "valid"
        assert block["authenticated"] is True

    def test_oauth_expired_sets_authenticated_false(self):
        config = _make_config(
            [CredentialType.OAUTH],
            has_creds=True,
            access_token="fake-token",
        )
        with patch("cli_tools_shared.token_manager.TokenManager") as MockTM:
            MockTM.return_value.is_expired.return_value = True
            MockTM.return_value.force_refresh.side_effect = Exception("refresh failed")
            result = AuthVerifier(config).verify()

        block = result["credential_types"]["oauth"]
        assert block["oauth_status"] == "expired"
        assert block["authenticated"] is False
        assert result["authenticated"] is False

    def test_expiring_oauth_with_live_test_handler_merges_api_result(self):
        config = _make_config(
            [CredentialType.OAUTH_AUTHORIZATION_CODE],
            has_creds=True,
            access_token="fake-token",
        )
        handler = lambda cfg: {"api_test": "passed", "scopes": ["w_member_social"]}

        with patch("cli_tools_shared.token_manager.TokenManager") as MockTM:
            MockTM.return_value.is_expired.return_value = False
            result = AuthVerifier(config, api_test_handler=handler).verify()

        block = result["credential_types"]["oauth_authorization_code"]
        assert block["oauth_status"] == "valid"
        assert block["api_test"] == "passed"
        assert block["scopes"] == ["w_member_social"]
        assert block["authenticated"] is True
        assert result["authenticated"] is True

    def test_expiring_oauth_failed_live_test_reports_invalid(self):
        config = _make_config(
            [CredentialType.OAUTH_AUTHORIZATION_CODE],
            has_creds=True,
            access_token="fake-token",
        )
        handler = lambda cfg: {"api_test": "failed: revoked"}

        with patch("cli_tools_shared.token_manager.TokenManager") as MockTM:
            MockTM.return_value.is_expired.return_value = False
            result = AuthVerifier(config, api_test_handler=handler).verify()

        block = result["credential_types"]["oauth_authorization_code"]
        assert block["oauth_status"] == "invalid"
        assert block["api_test"] == "failed: revoked"
        assert block["authenticated"] is False
        assert result["authenticated"] is False

    def test_static_oauth_credentials_with_live_test_handler_pass(self):
        """Non-expiring OAuth must still be live-verified via test_handler.

        ``OAUTH_TOKEN_EXPIRES = False`` (OAuth 1.0a, static API keys
        masquerading as OAuth) means there's no refresh-token check, so
        the only way to confirm the saved credentials still work is a
        live API round-trip. The verifier delegates to the api test
        handler exactly like API_KEY types do.
        """
        config = _make_config(
            [CredentialType.OAUTH],
            has_creds=True,
            access_token="fake-token",
        )
        config.OAUTH_TOKEN_EXPIRES = False
        config.OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN")
        config._get.side_effect = lambda field: {
            "CLIENT_ID": "consumer-key",
            "CLIENT_SECRET": "consumer-secret",
            "ACCESS_TOKEN": "token-value",
            "REFRESH_TOKEN": "token-secret",
        }.get(field)

        handler = lambda cfg: {"api_test": "passed"}
        with patch("cli_tools_shared.token_manager.TokenManager") as MockTM:
            result = AuthVerifier(config, api_test_handler=handler).verify()

        MockTM.assert_not_called()
        block = result["credential_types"]["oauth"]
        assert block["credentials_saved"] is True
        assert block["oauth_status"] == "valid"
        assert block["api_test"] == "passed"
        assert block["authenticated"] is True
        assert result["authenticated"] is True

    def test_static_oauth_credentials_with_failed_live_test_report_invalid(self):
        """Saved static OAuth credentials whose live API call fails must NOT report authenticated.

        This is the bricklink-style bug: all four OAuth1 fields are
        saved in .env but the token was revoked server-side. ``auth
        status`` must report this as invalid, not "valid".
        """
        config = _make_config(
            [CredentialType.OAUTH],
            has_creds=True,
            access_token="fake-token",
        )
        config.OAUTH_TOKEN_EXPIRES = False
        config.OAUTH_STATIC_REQUIRED_FIELDS = ("CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN")
        config._get.side_effect = lambda field: {
            "CLIENT_ID": "consumer-key",
            "CLIENT_SECRET": "consumer-secret",
            "ACCESS_TOKEN": "token-value",
            "REFRESH_TOKEN": "token-secret",
        }.get(field)

        def handler(cfg):
            raise RuntimeError("401 unauthorized")

        result = AuthVerifier(config, api_test_handler=handler).verify()

        block = result["credential_types"]["oauth"]
        assert block["credentials_saved"] is True
        assert block["oauth_status"] == "invalid"
        assert "failed" in block["api_test"]
        assert block["authenticated"] is False
        assert result["authenticated"] is False

    def test_static_oauth_credentials_without_test_handler_report_unverified(self):
        """Saved static OAuth credentials with no test handler can't be live-verified.

        Without a handler we have no way to round-trip — we must NOT
        falsely claim "valid". Report credentials_saved=True but
        authenticated=False so the user knows verification was not
        performed.
        """
        from cli_tools_shared.config import BaseConfig

        class _BareCfg:
            CREDENTIAL_TYPES = [CredentialType.OAUTH]
            OAUTH_TOKEN_EXPIRES = False
            OAUTH_STATIC_REQUIRED_FIELDS = (
                "CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN",
            )
            base_url = "https://example.com"
            test_connection = BaseConfig.test_connection  # no override

            def has_credentials(self):
                return True

            def get_active_profile_name(self):
                return "default"

            def get_browser(self):
                return None

            def _get(self, field):
                return {
                    "CLIENT_ID": "consumer-key",
                    "CLIENT_SECRET": "consumer-secret",
                    "ACCESS_TOKEN": "token-value",
                    "REFRESH_TOKEN": "token-secret",
                }.get(field)

        result = AuthVerifier(_BareCfg()).verify()
        block = result["credential_types"]["oauth"]
        assert block["credentials_saved"] is True
        assert block["oauth_status"] == "saved"
        assert block["api_test"].startswith("skipped")
        assert block["authenticated"] is False

    def test_no_credentials_sets_authenticated_false(self):
        config = _make_config([CredentialType.API_KEY], has_creds=False)
        result = AuthVerifier(config).verify()
        block = result["credential_types"]["api_key"]
        assert block["credentials_saved"] is False
        assert block["authenticated"] is False
        assert result["authenticated"] is False

    def test_api_test_with_custom_handler(self):
        config = _make_config([CredentialType.API_KEY], has_creds=True)

        def handler(cfg):
            return {"api_test": "passed"}

        result = AuthVerifier(config, api_test_handler=handler).verify()
        block = result["credential_types"]["api_key"]
        assert block["api_test"] == "passed"
        assert block["authenticated"] is True
        assert result["authenticated"] is True

    def test_api_test_failed_sets_authenticated_false(self):
        config = _make_config([CredentialType.API_KEY], has_creds=True)

        def handler(cfg):
            return {"api_test": "failed: unauthorized"}

        result = AuthVerifier(config, api_test_handler=handler).verify()
        block = result["credential_types"]["api_key"]
        assert "failed" in block["api_test"]
        assert block["authenticated"] is False
        assert result["authenticated"] is False

    def test_api_test_handler_extras_merge_into_block(self):
        """Handler fields beyond api_test (e.g. email) must merge into the type block."""
        config = _make_config([CredentialType.API_KEY], has_creds=True)

        def handler(cfg):
            return {"api_test": "passed", "email": "user@example.com"}

        result = AuthVerifier(config, api_test_handler=handler).verify()
        block = result["credential_types"]["api_key"]
        assert block["email"] == "user@example.com"

    def test_dual_auth_any_configured_type_authenticates(self):
        """Dual-auth: top-level is True when any configured pathway passes.

        OR-over-configured semantic — CLI works via any working credential
        pathway even if another listed type is broken. Here OAuth passes
        and the browser session has not been established yet
        (``has_session()`` is False), so the top-level rolls up True via
        the OAuth pathway.
        """
        browser = MagicMock()
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.OAUTH, CredentialType.BROWSER_SESSION],
            has_creds=True,
            access_token="fake-token",
            browser=browser,
            has_saved_session=False,
        )
        with patch("cli_tools_shared.token_manager.TokenManager") as MockTM:
            MockTM.return_value.is_expired.return_value = False
            result = AuthVerifier(config).verify()

        assert result["credential_types"]["oauth"]["authenticated"] is True
        assert result["credential_types"]["browser_session"]["authenticated"] is False
        assert result["authenticated"] is True
        # No on-disk browser session -> live probe is skipped.
        browser.is_authenticated.assert_not_called()

    def test_custom_plus_unconfigured_browser_reports_authenticated_true(self):
        """Regression: google-style (CUSTOM passes + BROWSER_SESSION not configured) → True.

        A listed BROWSER_SESSION type with no get_browser() configured must
        not drag the top-level to False when the CUSTOM path authenticates.
        """
        config = _make_config(
            [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=None,
        )
        handler = lambda cfg: {"api_test": "passed", "email": "u@example.com"}
        result = AuthVerifier(config, api_test_handler=handler).verify()

        assert result["credential_types"]["custom"]["authenticated"] is True
        assert result["credential_types"]["browser_session"]["credentials_saved"] is False
        assert result["credential_types"]["browser_session"]["authenticated"] is False
        assert result["authenticated"] is True

    def test_browser_session_credentials_saved_is_false_when_no_session_file(self):
        """BROWSER_SESSION with config.has_saved_session()=False → credentials_saved=False."""
        browser = MagicMock()
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION],
            has_creds=True,
            browser=browser,
            has_saved_session=False,
        )
        result = AuthVerifier(config).verify()
        block = result["credential_types"]["browser_session"]
        assert block["credentials_saved"] is False
        assert block["authenticated"] is False
        assert result["authenticated"] is False
        browser.is_authenticated.assert_not_called()

    def test_all_types_unconfigured_reports_authenticated_false(self):
        """No type has credentials_saved → top-level authenticated=False."""
        config = _make_config(
            [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION],
            has_creds=False,
            browser=None,
        )
        result = AuthVerifier(config).verify()
        assert result["credential_types"]["custom"]["credentials_saved"] is False
        assert result["credential_types"]["browser_session"]["credentials_saved"] is False
        assert result["authenticated"] is False


# ---------------------------------------------------------------------------
# AuthVerifier credential type constants
# ---------------------------------------------------------------------------

class TestCredentialTypeConstants:
    """Verify that AuthVerifier type constants cover all CredentialTypes."""

    def test_all_types_covered(self):
        """Every CredentialType (except NO_AUTH) must be in exactly one of the type sets."""
        all_covered = AuthVerifier.OAUTH_TYPES | AuthVerifier.BROWSER_TYPES | AuthVerifier.API_TYPES
        for ct in CredentialType:
            if ct == CredentialType.NO_AUTH:
                continue
            assert ct in all_covered, (
                f"CredentialType.{ct.name} not covered by any AuthVerifier type constant"
            )

    def test_no_overlap(self):
        """Type sets must be mutually exclusive."""
        assert not (AuthVerifier.OAUTH_TYPES & AuthVerifier.BROWSER_TYPES)
        assert not (AuthVerifier.OAUTH_TYPES & AuthVerifier.API_TYPES)
        assert not (AuthVerifier.BROWSER_TYPES & AuthVerifier.API_TYPES)


# ---------------------------------------------------------------------------
# auth status MUST live-verify the browser session (ground-truth guard)
# ---------------------------------------------------------------------------

class TestAuthStatusLiveVerifiesBrowserSession:
    """Pin the contract that ``auth status`` performs a LIVE round-trip.

    Filesystem state alone is not proof of being authenticated: cookies
    expire, sessions get revoked, and the saved storage_state can
    outlive the actual login. ``auth status`` must call
    ``browser.is_authenticated()`` whenever the on-disk session exists,
    so that the JSON it reports reflects ground truth and not stale
    belief.

    This is the documented user-facing contract: "auth status must do
    LIVE checks with the auth method in question always to ensure
    accuracy." A previous iteration of this skill made status
    filesystem-only to keep it cheap; that turned out to produce
    false-positive "authenticated: true" reports that contradicted the
    very next data command, so the contract was reversed.
    """

    def test_status_skips_live_probe_when_no_session_files_exist(self):
        """No persistent profile on disk → no live probe needed."""
        browser = MagicMock()
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION], has_creds=True, browser=browser,
            has_saved_session=False,
        )
        result = AuthVerifier(config).verify()

        block = result["credential_types"]["browser_session"]
        assert block["credentials_saved"] is False
        assert block["authenticated"] is False
        assert result["authenticated"] is False
        browser.is_authenticated.assert_not_called()

    def test_status_live_verifies_when_session_files_exist_and_valid(self):
        """Persistent profile on disk → call is_authenticated() and trust it."""
        browser = MagicMock()
        browser.is_authenticated.return_value = True
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION], has_creds=True, browser=browser,
            has_saved_session=True,
        )
        result = AuthVerifier(config).verify()

        block = result["credential_types"]["browser_session"]
        assert block["credentials_saved"] is True
        assert block["browser_session"] is True
        assert block["authenticated"] is True
        assert result["authenticated"] is True
        browser.is_authenticated.assert_called_once_with()

    def test_status_reports_false_when_session_files_exist_but_live_check_fails(self):
        """The canonical bug: cookies on disk, server-side session dead.

        Without the live check, ``auth status`` would report
        ``authenticated: true`` here and the next data command would
        immediately fail with 'Session expired'. The live check exists
        precisely to prevent that contradiction.
        """
        browser = MagicMock()
        browser.is_authenticated.return_value = False
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION], has_creds=True, browser=browser,
            has_saved_session=True,
        )
        result = AuthVerifier(config).verify()

        block = result["credential_types"]["browser_session"]
        # On-disk artifacts are still present...
        assert block["credentials_saved"] is True
        # ...but live verification says no.
        assert block["browser_session"] is False
        assert block["authenticated"] is False
        assert result["authenticated"] is False
        browser.is_authenticated.assert_called_once_with()

    def test_status_closes_browser_after_live_check(self):
        """Live verification must clean up — never leak a running browser."""
        browser = MagicMock()
        browser.is_authenticated.return_value = True
        browser.close.return_value = None

        config = _make_config(
            [CredentialType.BROWSER_SESSION], has_creds=True, browser=browser,
            has_saved_session=True,
        )
        AuthVerifier(config).verify()
        browser.close.assert_called_once_with()
