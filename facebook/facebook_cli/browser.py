"""Browser automation for Facebook CLI."""
import time

from cli_tools_shared.auth import AuthResult, BrowserAutomation, BrowserAutomationError
from cli_tools_shared.output import print_info, print_success


class FacebookBrowser(BrowserAutomation):
    SESSION_NAME = "facebook"
    LOGIN_URL = "https://www.facebook.com/login"
    AUTH_CHECK_URL = "https://m.facebook.com/"
    AUTH_URL_PATTERN = r"/login"
    AUTH_COOKIE_PATTERNS = ["c_user"]  # c_user cookie exists when logged into Facebook

    def _login_blocker(self, page) -> str | None:
        url = page.url or ""
        lowered_url = url.lower()
        if "/checkpoint" in lowered_url:
            return "checkpoint"
        if "two_step_verification" in lowered_url or "two-factor" in lowered_url or "two_factor" in lowered_url:
            return "two-step"

        blocker = page.evaluate(
            """() => ({
                captcha: !!document.querySelector('iframe[src*="recaptcha"], iframe#captcha-recaptcha'),
                checkpoint: !!document.querySelector('form[action*="checkpoint"]'),
                twoStep: !!document.querySelector('input[name="approvals_code"], input[name="code"]')
            })"""
        )
        if not isinstance(blocker, dict):
            raise BrowserAutomationError("Facebook login blocker probe returned a non-object result.")
        if blocker.get("captcha"):
            return "captcha"
        if blocker.get("checkpoint"):
            return "checkpoint"
        if blocker.get("twoStep"):
            return "two-step"
        return None

    def _submit_credentials(self, page, username: str, password: str) -> None:
        page.wait_for_selector('form#login_form', timeout=15000)
        page.wait_for_selector('input[name="email"]', timeout=15000)
        page.wait_for_selector('input[name="pass"]', timeout=15000)
        result = page.evaluate(
            """(credentials) => {
                const form = document.querySelector('form#login_form');
                const email = document.querySelector('input[name="email"]');
                const password = document.querySelector('input[name="pass"]');
                if (!form || !email || !password) {
                    return {success: false, error: "Facebook login form is missing the form, email field, or password field."};
                }
                if (email.form !== form || password.form !== form) {
                    return {success: false, error: "Facebook email/password fields are not attached to form#login_form."};
                }
                if (typeof form.requestSubmit !== "function") {
                    return {success: false, error: "Facebook login form does not expose requestSubmit()."};
                }
                const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
                if (typeof valueSetter !== "function") {
                    return {success: false, error: "HTMLInputElement.value setter is unavailable."};
                }
                email.focus();
                valueSetter.call(email, credentials.username);
                email.dispatchEvent(new Event("input", { bubbles: true }));
                email.dispatchEvent(new Event("change", { bubbles: true }));
                password.focus();
                valueSetter.call(password, credentials.password);
                password.dispatchEvent(new Event("input", { bubbles: true }));
                password.dispatchEvent(new Event("change", { bubbles: true }));
                form.requestSubmit();
                return {success: true};
            }""",
            {"username": username, "password": password},
        )
        if not isinstance(result, dict):
            raise BrowserAutomationError("Facebook login form submit returned a non-object result.")
        if not result.get("success"):
            raise BrowserAutomationError(result.get("error") or "Facebook login form submit failed.")

    def _wait_for_authenticated_submit(self, page) -> None:
        deadline = time.monotonic() + self.LOGIN_TIMEOUT
        while time.monotonic() < deadline:
            blocker = self._login_blocker(page)
            if blocker is not None:
                raise BrowserAutomationError(
                    f"Facebook login blocked by {blocker} at {page.url}."
                )
            cookies = page.cookie_list()
            if self._get_auth_cookies(cookies):
                return
            page.wait_for_timeout(500)
        raise BrowserAutomationError(
            f"Facebook login did not produce c_user auth cookie within {self.LOGIN_TIMEOUT}s. Final URL: {page.url}"
        )

    def authenticate(self, force: bool = False):
        has_saved = (
            self.config.has_saved_session()
            if hasattr(self.config, "has_saved_session")
            else False
        )
        if has_saved and not force:
            return

        username = self.config.username
        password = self.config.password
        if not username or not password:
            raise BrowserAutomationError(
                "Facebook browser login requires USERNAME and PASSWORD in the selected auth profile."
            )

        if force:
            self.clear_session()

        print_info(f"Opening browser for login at: {self.LOGIN_URL}")
        print_info("Submitting Facebook credentials from the selected auth profile.")

        svc = self._get_service()
        try:
            svc.browser_open(
                self.LOGIN_URL,
                headed=True,
                persistent_profile_dir=self._get_persistent_profile_dir(),
            )
            self._service = svc
            self._page = svc
            self._submit_credentials(svc, username, password)
            self._wait_for_authenticated_submit(svc)
        finally:
            self.close()

        persisted = self.is_authenticated()
        self.close()
        if not isinstance(persisted, AuthResult) or not persisted.authenticated:
            raise BrowserAutomationError(
                "Browser session did not persist after reopening. "
                "Facebook login completed without a reusable saved session."
            )

        self._auth_verified_at = time.time()
        print_success("Authentication complete.")
