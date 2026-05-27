"""Browser-session integration for Grammarly docs auth."""

from dataclasses import dataclass

from cli_tools_shared.auth import BrowserAutomation

from .client import ClientError, DocsClient


@dataclass
class _CookieProbePage:
    """Minimal page object for BrowserAutomation-style auth checks."""

    url: str

    def wait_for_timeout(self, _timeout_ms: int) -> None:
        return None


class GrammarlyBrowser(BrowserAutomation):
    """Declarative browser hooks for Grammarly docs auth."""

    SESSION_NAME = "grammarly"
    LOGIN_URL = "https://app.grammarly.com/"
    AUTH_CHECK_URL = "https://auth.grammarly.com/v3/user?app=webeditor_chrome"
    AUTH_URL_PATTERN = r"login|signin|auth-required"


class GrammarlyCookieBrowserSession:
    """Cookie-backed auth adapter used by shared auth status/login hooks."""

    def __init__(self, config):
        self.config = config
        self._delegate = GrammarlyBrowser(config)
        self._delegate.get_page = self._probe_or_login_page
        self._delegate.login = self._import_cookie_source
        self._delegate.close = self._close

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def _probe_docs_user(self) -> _CookieProbePage:
        user = DocsClient(config=self.config).get_user()
        # Grammarly issues anonymous grauth cookies to signed-out visitors.
        # Those pass the generic user endpoint but cannot access docs data.
        if user.get("anonymous") or str(user.get("email", "")).endswith("@anonymous"):
            raise ClientError("Grammarly returned an anonymous browser session")
        return _CookieProbePage(url="https://app.grammarly.com/")

    def _probe_or_login_page(self, url: str = None) -> _CookieProbePage:
        try:
            return self._probe_docs_user()
        except ClientError:
            return _CookieProbePage(url="https://app.grammarly.com/login")

    def _import_cookie_source(self, force: bool = False) -> dict:
        if force:
            self.config.clear_session()

        cookie_string = self.config.cookies
        if not cookie_string:
            return {
                "success": False,
                "message": (
                    "No Grammarly docs cookies found. Set GRAMMARLY_COOKIES or create "
                    "~/.grammarly_cookies, then run "
                    "'grammarly auth login --credential-type browser_session'."
                ),
            }

        try:
            self._probe_docs_user()
        except ClientError as exc:
            return {
                "success": False,
                "message": f"Grammarly docs cookies failed validation: {exc}",
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to verify Grammarly docs cookies: {exc}",
            }

        self.config.save_cookies(cookie_string)
        return {"success": True, "message": "Grammarly docs cookies saved"}

    def _close(self) -> None:
        return None
