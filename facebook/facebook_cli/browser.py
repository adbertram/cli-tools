"""Browser automation for Facebook CLI."""
from cli_tools_shared.auth import BrowserAutomation

# Facebook remembers accounts that signed in on this browser profile and then
# opens /login on a saved-account picker ("<Name> / Continue / Use another
# profile") instead of the email + password form. "Continue" opens a
# password-only dialog with no username field, so the declarative login picks
# "Use another profile", which renders the normal email + password form in place.
SAVED_ACCOUNT_PICKER_SELECTOR = '[role="button"][aria-label="Use another profile"]'
_DISMISS_SAVED_ACCOUNT_PICKER_JS = """(sel) => {
  if (document.querySelector('input[name="email"]')?.offsetParent) return 'form';
  const other = document.querySelector(sel);
  if (!other) return 'none';
  other.focus();
  return 'focused';
}"""


class FacebookBrowser(BrowserAutomation):
    SESSION_NAME = "facebook"
    LOGIN_URL = "https://www.facebook.com/login"
    AUTH_CHECK_URL = "https://m.facebook.com/"
    AUTH_URL_PATTERN = r"/login"
    AUTH_COOKIE_PATTERNS = ["c_user"]  # c_user cookie exists when logged into Facebook
    AUTH_LOGIN_FORM_SELECTOR = 'input[name="email"], input[name="pass"]'
    AUTH_LOGIN_USERNAME_SELECTOR = 'input[name="email"]'
    AUTH_LOGIN_PASSWORD_SELECTOR = 'input[name="pass"]'
    # Classic form: <button name="login">. Current (Nov 2026) form: a
    # <div role="button" aria-label="Log In"> inside the login <form>.
    AUTH_LOGIN_SUBMIT_SELECTOR = 'button[name="login"], form [role="button"][aria-label="Log In"]'
    AUTH_LOGIN_USERNAME_SECRET = "facebook-username"
    AUTH_LOGIN_PASSWORD_SECRET = "facebook-password"
    AUTH_LOGIN_SECRETS_PROFILE_SCOPED = True
    # A Facebook checkpoint, MFA prompt, or CAPTCHA still needs a person. The
    # shared auth flow attempts the declarative secret-manager login first,
    # then preserves this plain-browser fallback for those human gates.
    MANUAL_LOGIN = True

    def _complete_noninteractive_login(self, page) -> None:
        """Dismiss Facebook's saved-account picker, then run the shared login."""
        state = page.evaluate(_DISMISS_SAVED_ACCOUNT_PICKER_JS, SAVED_ACCOUNT_PICKER_SELECTOR)
        if state == "focused":
            # A synthetic el.click() does not reach Facebook's React handler on
            # this control; keyboard activation of the focused button does.
            page.keyboard_press("Enter")
            page.wait_for_selector(self.AUTH_LOGIN_USERNAME_SELECTOR, state="visible", timeout=15000)
        super()._complete_noninteractive_login(page)
