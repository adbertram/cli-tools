# Dual Auth: Browser Session + API Credentials

Some CLIs need both API credentials (OAuth, API key) AND a browser session. Example: Bricklink uses OAuth for API calls and browser session for features not available via API.

## Config Setup

```python
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType

class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]

    # OAuth settings
    OAUTH_AUTH_URL = "https://example.com/oauth/authorize"
    OAUTH_TOKEN_URL = "https://example.com/oauth/token"

    def get_browser(self):
        from .browser import MyBrowser
        return MyBrowser(self)
```

## How AuthVerifier Handles Dual Auth

AuthVerifier checks ALL credential types. For dual auth:

1. **OAuth check** — Token expiry + refresh attempt → `oauth_status`
2. **Browser check** — Headless auth verification → `browser_session`
3. `authenticated` = True ONLY if ALL checks pass

```json
{
  "authenticated": true,
  "credentials_saved": true,
  "credential_types": {
    "oauth": {
      "authenticated": true,
      "oauth_status": "valid"
    },
    "browser_session": {
      "authenticated": true,
      "browser_session": true
    }
  }
}
```

If OAuth is valid but browser session expired:
```json
{
  "authenticated": false,
  "credentials_saved": true,
  "credential_types": {
    "oauth": {
      "authenticated": true,
      "oauth_status": "valid"
    },
    "browser_session": {
      "authenticated": false,
      "browser_session": false
    }
  }
}
```

## auth login with Dual Auth

`auth login` handles both credential types in sequence:
1. Prompts for OAuth credentials (client_id, client_secret, etc.)
2. Runs OAuth flow if configured
3. Then calls `_handle_browser_login()` for the browser session

With `--credential-type`:
- `auth login --credential-type oauth` — Only prompts for OAuth credentials
- `auth login --credential-type browser_session` — Only does browser login (no prompts)

## auth logout with Dual Auth

Clears everything:
1. `config.clear_credentials()` — Clears all env vars (OAuth tokens, etc.)
2. `browser.clear_session()` — Wipes browser session data
3. `browser.close()` — Closes browser process

## has_credentials() for Dual Auth

`BaseConfig.has_credentials()` requires ALL credential types to be satisfied:
- OAuth: `CLIENT_ID`, `CLIENT_SECRET`, `ACCESS_TOKEN` must exist in .env
- Browser: `has_saved_session()` must be True (profile.json marker exists)

Both must be true for `credentials_saved: true`.

## Example: Bricklink

```python
# config.py
class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.OAUTH, CredentialType.BROWSER_SESSION]
    OAUTH_AUTH_URL = None  # OAuth 1.0a — no auth URL
    OAUTH_TOKEN_URL = None  # OAuth 1.0a — no token URL

    FIELD_MAP = {
        "CLIENT_ID": "consumer_key",
        "CLIENT_SECRET": "consumer_secret",
        "ACCESS_TOKEN": "token_value",
        "REFRESH_TOKEN": "token_secret",
    }

    def get_browser(self):
        from .browser import BricklinkBrowser
        return BricklinkBrowser(self)

# browser.py
class BricklinkBrowser(BrowserAutomation):
    SESSION_NAME = "bricklink"
    LOGIN_URL = "https://www.bricklink.com/v2/login.page"
    AUTH_CHECK_URL = "https://www.bricklink.com/orderReceived.asp"
    AUTH_URL_PATTERN = r"/login|identity\.lego\.com"
    AUTH_SUCCESS_SELECTOR = "img.blp-icon-nav__item-image"
    AUTH_COOKIE_PATTERNS = ["bricklink\\.bricklink-account\\.jwt"]

    def __init__(self, config=None):
        config = config or get_config()
        super().__init__(config)
```
