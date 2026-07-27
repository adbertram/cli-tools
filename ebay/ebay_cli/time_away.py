"""eBay Time Away page automation.

Time Away has no API, so these read and drive the seller's Time Away settings
page through the CLI-owned browser session. Each function takes a live
:class:`~ebay_cli.browser.EbayBrowser`; the caller owns opening and closing it.
"""

from cli_tools_shared.auth import BrowserAutomationError

TIME_AWAY_URL = "https://www.ebay.com/vac/timeaway"

MONTH_NAMES = [
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
]

BLOCKER_JS = """() => ({
    url: location.href,
    title: document.title,
    text: document.body ? document.body.innerText.replace(/\\s+/g, " ").slice(0, 500) : "",
})"""

STATE_JS = """() => {
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

CLICK_BUTTON_JS = """(labels) => {
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
}"""

SET_FORM_JS = """(data) => {
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
}"""


def read_settings(browser) -> dict:
    """Read the eBay Time Away page state."""
    page = _open_page(browser)
    return extract_state(page)


def enable(
    browser,
    *,
    start_date_iso: str,
    start_date_display: str,
    end_date_iso: str,
    end_date_display: str,
    mode: str,
) -> dict:
    """Schedule eBay Time Away."""
    page = _open_page(browser)
    current = extract_state(page)
    if _matches_schedule(
        current,
        start_date_iso=start_date_iso,
        end_date_iso=end_date_iso,
        mode=mode,
    ):
        return current

    click_button(
        page,
        ["schedule time away", "edit time away", "change time away"],
        required=False,
    )
    page.wait_for_timeout(1000)
    set_form(
        page,
        start_date_iso=start_date_iso,
        start_date_display=start_date_display,
        end_date_iso=end_date_iso,
        end_date_display=end_date_display,
        mode=mode,
    )
    click_button(page, ["apply", "save"], required=True)
    page.wait_for_timeout(3000)
    raise_for_blocker(page)
    return extract_state(page)


def disable(browser) -> dict:
    """Cancel eBay Time Away."""
    page = _open_page(browser)
    click_button(
        page,
        ["cancel time away", "end time away", "turn off time away"],
        required=True,
    )
    page.wait_for_timeout(1000)
    click_button(
        page,
        ["apply", "confirm", "save", "cancel time away"],
        required=False,
    )
    page.wait_for_timeout(3000)
    raise_for_blocker(page)
    return extract_state(page)


def _open_page(browser):
    """Load the Time Away page and fail loudly on a captcha/sign-in wall."""
    page = browser.get_page(TIME_AWAY_URL)
    page.wait_for_timeout(3000)
    raise_for_blocker(page)
    return page


def raise_for_blocker(page) -> None:
    """Raise when the page is a security challenge or a sign-in redirect."""
    state = page.evaluate(BLOCKER_JS)
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


def extract_state(page) -> dict:
    """Return the visible Time Away schedule state."""
    return page.evaluate(STATE_JS)


def _matches_schedule(
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
        long_date_label(start_date_iso).lower() in page_text
        and long_date_label(end_date_iso).lower() in page_text
    )


def long_date_label(value: str) -> str:
    """Render an ISO date the way the Time Away page prints it."""
    year, month, day = (int(part) for part in value.split("-"))
    return f"{MONTH_NAMES[month]} {day}, {year}"


def click_button(page, labels: list[str], *, required: bool) -> bool:
    """Click the first visible, enabled control whose text contains a label."""
    clicked = page.evaluate(CLICK_BUTTON_JS, labels)
    if required and not clicked:
        raise BrowserAutomationError(
            f"eBay Time Away page did not contain an actionable button matching: {', '.join(labels)}"
        )
    return bool(clicked)


def set_form(
    page,
    *,
    start_date_iso: str,
    start_date_display: str,
    end_date_iso: str,
    end_date_display: str,
    mode: str,
) -> None:
    """Fill the Time Away start/end dates and select the sales mode."""
    result = page.evaluate(
        SET_FORM_JS,
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
