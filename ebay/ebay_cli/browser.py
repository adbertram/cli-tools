"""eBay browser automation using cli_tools_shared."""

import re

from cli_tools_shared.auth import BrowserAutomation, BrowserAutomationError


# JavaScript run on the My-eBay summary page to distinguish a real, rendered
# signed-in page from a URL-preserving error/interstitial. eBay redirects a
# logged-out summary request to sign-in (URL changes, caught by
# AUTH_URL_PATTERN) and a challenged one to /splashui/captcha (caught by
# AUTH_FAILURE_URL_PATTERN), so the only remaining false-healthy path is an
# error page that keeps the summary URL. This flags those.
EBAY_PAGE_FETCH_JS = """() => {
    const body = document.body ? document.body.innerText : '';
    const low = body.toLowerCase();
    const failure = /something went wrong|we'?re having trouble|try again later|temporarily unavailable|this page is (currently )?unavailable|access denied|page not found|error reference/i.test(low);
    const greeting = !!document.querySelector('#gh-ug, .gh-identity__greeting, [id^="gh-ug"], .gh-eb-u');
    return { failure_banner: failure, greeting: greeting };
}"""


class EbayBrowser(BrowserAutomation):
    """eBay browser session managed by the shared BrowserAutomation base."""

    SESSION_NAME = "ebay"
    LOGIN_URL = "https://www.ebay.com/signin/"
    AUTH_CHECK_URL = "https://www.ebay.com/mye/myebay/summary"
    AUTH_URL_PATTERN = r"/signin|SignIn|signin\.ebay|login"
    AUTH_FAILURE_URL_PATTERN = r"/splashui/captcha|hcaptcha|recaptcha"
    # Positive authenticated signal: the My eBay summary page requires login.
    # A logged-out (or challenged) session is redirected to signin/captcha and
    # never lands here, so the request URL staying on the summary path is proof
    # of a live authenticated session.
    #
    # NOTE: Do NOT use AUTH_COOKIE_PATTERNS for eBay. eBay sets dozens of
    # anonymous/guest cookies (dp1, nonsession, ebay, s, svid, ...) on every
    # visitor, including logged-out ones, so cookie presence is not an auth
    # signal. Broad patterns there (e.g. r"s", r"ebay") match those guest
    # cookies and make auth status falsely report the browser session as
    # authenticated while listings search — which relies on the same live
    # check — fails. See tests/test_browser_auth_check.py.
    AUTH_SUCCESS_URL = r"/mye/myebay/summary"

    TIME_AWAY_URL = "https://www.ebay.com/vac/timeaway"

    def _check_auth(self, page) -> bool:
        """Truthful browser-session check for eBay.

        A logged-out session is redirected to sign-in and a challenged one to
        /splashui/captcha, both of which change the URL and are rejected by the
        base class' failure/login-page checks. The remaining false-healthy risk
        is a URL-preserving error/interstitial served at the summary URL: the
        URL still matches ``AUTH_SUCCESS_URL`` but the browser did not actually
        fetch a usable page. Require a positive fetch signal so ``auth status``
        does not report healthy when it cannot really fetch.
        """
        # Fail closed on captcha/challenge and sign-in pages first.
        if self.AUTH_FAILURE_URL_PATTERN and self._is_auth_failure_page(page):
            return False
        if self._is_login_page(page):
            return False

        url = getattr(page, "url", "")
        if not re.search(self.AUTH_SUCCESS_URL, url):
            return False

        signal = self._page_fetch_signal(page)
        if signal is None:
            # Content could not be inspected (e.g. an offline unit-test page):
            # trust the summary-URL match as before.
            return True
        return signal

    def _page_fetch_signal(self, page):
        """Return True/False for a rendered summary page, or None if the page
        cannot be inspected (no ``evaluate``)."""
        evaluate = getattr(page, "evaluate", None)
        if not callable(evaluate):
            return None
        try:
            state = evaluate(EBAY_PAGE_FETCH_JS)
        except Exception:
            return None
        if not isinstance(state, dict):
            return None
        if state.get("failure_banner"):
            return False
        return True

    def get_time_away_settings(self) -> dict:
        """Read the eBay Time Away page state."""
        page = self.get_page(self.TIME_AWAY_URL)
        page.wait_for_timeout(3000)
        self._raise_for_time_away_blocker(page)
        return self._extract_time_away_state(page)

    def enable_time_away(
        self,
        *,
        start_date_iso: str,
        start_date_display: str,
        end_date_iso: str,
        end_date_display: str,
        mode: str,
    ) -> dict:
        """Schedule eBay Time Away."""
        page = self.get_page(self.TIME_AWAY_URL)
        page.wait_for_timeout(3000)
        self._raise_for_time_away_blocker(page)
        current = self._extract_time_away_state(page)
        if self._time_away_matches(
            current,
            start_date_iso=start_date_iso,
            end_date_iso=end_date_iso,
            mode=mode,
        ):
            return current

        self._click_time_away_button(
            page,
            ["schedule time away", "edit time away", "change time away"],
            required=False,
        )
        page.wait_for_timeout(1000)
        self._set_time_away_form(
            page,
            start_date_iso=start_date_iso,
            start_date_display=start_date_display,
            end_date_iso=end_date_iso,
            end_date_display=end_date_display,
            mode=mode,
        )
        self._click_time_away_button(page, ["apply", "save"], required=True)
        page.wait_for_timeout(3000)
        self._raise_for_time_away_blocker(page)
        return self._extract_time_away_state(page)

    def disable_time_away(self) -> dict:
        """Cancel eBay Time Away."""
        page = self.get_page(self.TIME_AWAY_URL)
        page.wait_for_timeout(3000)
        self._raise_for_time_away_blocker(page)
        self._click_time_away_button(
            page,
            ["cancel time away", "end time away", "turn off time away"],
            required=True,
        )
        page.wait_for_timeout(1000)
        self._click_time_away_button(
            page,
            ["apply", "confirm", "save", "cancel time away"],
            required=False,
        )
        page.wait_for_timeout(3000)
        self._raise_for_time_away_blocker(page)
        return self._extract_time_away_state(page)

    def _raise_for_time_away_blocker(self, page) -> None:
        state = page.evaluate(
            """() => ({
                url: location.href,
                title: document.title,
                text: document.body ? document.body.innerText.replace(/\\s+/g, " ").slice(0, 500) : "",
            })"""
        )
        url = state.get("url", "")
        title = state.get("title", "")
        text = state.get("text", "")
        lowered = f"{url} {title} {text}".lower()
        if "splashui/captcha" in lowered or "security measure" in lowered or "please verify yourself" in lowered:
            raise BrowserAutomationError(
                "eBay Time Away page is blocked by a security verification page. "
                f"url={url} title={title!r}"
            )
        if "signin.ebay.com" in lowered or "/signin" in lowered or "sign in to your account" in lowered:
            raise BrowserAutomationError(
                "eBay Time Away page requires browser-session login. "
                "Run 'ebay auth login --credential-type browser_session'. "
                f"url={url} title={title!r}"
            )

    def _extract_time_away_state(self, page) -> dict:
        return page.evaluate(
            """() => {
                const text = document.body ? document.body.innerText.replace(/\\s+/g, " ").trim() : "";
                const controls = Array.from(document.querySelectorAll("button,input,select,textarea,[role='button'],[role='radio']"))
                    .filter((el) => {
                        const style = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                    })
                    .map((el) => ({
                        tag: el.tagName,
                        type: el.getAttribute("type"),
                        name: el.getAttribute("name"),
                        value: el.value || el.getAttribute("value"),
                        text: (el.innerText || el.textContent || el.getAttribute("aria-label") || "").replace(/\\s+/g, " ").trim(),
                        checked: !!el.checked,
                    }));
                const lower = text.toLowerCase();
                return {
                    url: location.href,
                    title: document.title,
                    enabled: lower.includes("cancel time away") || lower.includes("end time away") || lower.includes("currently on time away") || lower.includes("scheduled time away"),
                    has_schedule_action: lower.includes("schedule time away"),
                    has_cancel_action: lower.includes("cancel time away") || lower.includes("end time away"),
                    mode: lower.includes("pause sales") ? "pause-sales" : (lower.includes("allow sales") || lower.includes("allow item sales") ? "allow-sales" : null),
                    page_text: text.slice(0, 6000),
                    text_excerpt: text.slice(0, 1000),
                    controls: controls.slice(0, 40),
                };
            }"""
        )

    def _time_away_matches(
        self,
        state: dict,
        *,
        start_date_iso: str,
        end_date_iso: str,
        mode: str,
    ) -> bool:
        """Return true when the current visible schedule already matches."""
        if not state.get("enabled") or state.get("mode") != mode:
            return False
        page_text = (state.get("page_text") or state.get("text_excerpt") or "").lower()
        return (
            self._long_date_label(start_date_iso).lower() in page_text
            and self._long_date_label(end_date_iso).lower() in page_text
        )

    @staticmethod
    def _long_date_label(value: str) -> str:
        year, month, day = (int(part) for part in value.split("-"))
        month_name = [
            "",
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ][month]
        return f"{month_name} {day}, {year}"

    def _click_time_away_button(self, page, labels: list[str], *, required: bool) -> bool:
        clicked = page.evaluate(
            """(labels) => {
                const wanted = labels.map((label) => label.toLowerCase());
                const visible = (el) => {
                    const style = getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                };
                const norm = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
                const candidates = Array.from(document.querySelectorAll("button,a,input[type='button'],input[type='submit'],[role='button']"));
                const match = candidates.find((el) => {
                    if (!visible(el) || el.disabled) return false;
                    const text = norm(el.innerText || el.textContent || el.value || el.getAttribute("aria-label"));
                    return wanted.some((label) => text.includes(label));
                });
                if (!match) return false;
                match.click();
                return true;
            }""",
            labels,
        )
        if required and not clicked:
            raise BrowserAutomationError(
                f"eBay Time Away page did not contain an actionable button matching: {', '.join(labels)}"
            )
        return bool(clicked)

    def _set_time_away_form(
        self,
        page,
        *,
        start_date_iso: str,
        start_date_display: str,
        end_date_iso: str,
        end_date_display: str,
        mode: str,
    ) -> None:
        result = page.evaluate(
            """(data) => {
                const visible = (el) => {
                    const style = getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
                };
                const norm = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
                const setValue = (input, isoValue, displayValue) => {
                    const value = input.type === "date" ? isoValue : displayValue;
                    input.value = value;
                    input.dispatchEvent(new Event("input", {bubbles: true}));
                    input.dispatchEvent(new Event("change", {bubbles: true}));
                    input.dispatchEvent(new Event("blur", {bubbles: true}));
                };
                const fieldByLabel = (patterns) => {
                    const wanted = patterns.map((pattern) => pattern.toLowerCase());
                    const fields = Array.from(document.querySelectorAll("input,textarea"));
                    let byAria = fields.find((field) => visible(field) && wanted.some((pattern) => norm(field.getAttribute("aria-label") || field.name || field.id || field.placeholder).includes(pattern)));
                    if (byAria) return byAria;
                    for (const label of Array.from(document.querySelectorAll("label"))) {
                        const labelText = norm(label.innerText || label.textContent);
                        if (!wanted.some((pattern) => labelText.includes(pattern))) continue;
                        if (label.htmlFor) {
                            const linked = document.getElementById(label.htmlFor);
                            if (linked && visible(linked)) return linked;
                        }
                        const nested = label.querySelector("input,textarea");
                        if (nested && visible(nested)) return nested;
                    }
                    return null;
                };
                const dateInputs = Array.from(document.querySelectorAll("input[type='date'],input")).filter((input) => visible(input) && !["radio", "checkbox", "hidden", "submit", "button"].includes(input.type));
                const start = fieldByLabel(["start date", "start"]) || dateInputs[0];
                const end = fieldByLabel(["end date", "end"]) || dateInputs[1];
                if (!start || !end) {
                    return {success: false, error: "Time Away date fields were not found."};
                }
                const modeWords = data.mode === "pause-sales" ? ["pause", "sales"] : ["allow", "sales"];
                const modeText = modeWords.join(" ");
                const textFor = (el) => norm([
                    el.innerText,
                    el.textContent,
                    el.getAttribute("aria-label"),
                    el.getAttribute("title"),
                    el.value,
                ].filter(Boolean).join(" "));
                const hasModeText = (el) => {
                    const text = textFor(el);
                    return modeWords.every((word) => text.includes(word));
                };
                const actionable = (el) => {
                    if (!el || el.disabled || !visible(el)) return null;
                    const role = norm(el.getAttribute("role"));
                    const tag = el.tagName.toLowerCase();
                    if (tag === "button" || role === "radio" || role === "button") return el;
                    if (tag === "input" && el.type === "radio") return el;
                    return null;
                };
                const controlForTextNode = (el) => {
                    const direct = actionable(el);
                    if (direct) return direct;
                    if (el.tagName.toLowerCase() === "label" && el.htmlFor) {
                        const linked = actionable(document.getElementById(el.htmlFor));
                        if (linked) return linked;
                    }
                    const nested = Array.from(el.querySelectorAll("input[type='radio'],button,[role='radio'],[role='button']"))
                        .map(actionable)
                        .find(Boolean);
                    if (nested) return nested;
                    const parent = el.closest("label,[role='radio'],button");
                    return actionable(parent);
                };
                const modeContainers = Array.from(document.querySelectorAll("label,button,[role='radio'],input[type='radio'],fieldset,li,div,span"))
                    .filter((el) => visible(el) && hasModeText(el))
                    .sort((left, right) => textFor(left).length - textFor(right).length);
                const modeControl = modeContainers.map(controlForTextNode).find(Boolean);
                if (!modeControl) {
                    return {success: false, error: `Time Away mode control was not found: ${modeText}`};
                }
                modeControl.click();
                setValue(start, data.start_date_iso, data.start_date_display);
                setValue(end, data.end_date_iso, data.end_date_display);
                return {success: true};
            }""",
            {
                "start_date_iso": start_date_iso,
                "start_date_display": start_date_display,
                "end_date_iso": end_date_iso,
                "end_date_display": end_date_display,
                "mode": mode,
            },
        )
        if not result or not result.get("success"):
            raise BrowserAutomationError(
                result.get("error") if isinstance(result, dict) else "Unable to fill eBay Time Away form."
            )


BrowserService = EbayBrowser
BrowserError = BrowserAutomationError
