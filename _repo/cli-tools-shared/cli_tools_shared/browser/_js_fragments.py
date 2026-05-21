"""JavaScript snippet constants and generators for browser element interaction."""

import json


def _fill_js(text: str) -> str:
    """JS body to set value and dispatch input+change events on `el`."""
    return (
        f"el.value = {json.dumps(text)};"
        f" el.dispatchEvent(new Event('input', {{bubbles: true}}));"
        f" el.dispatchEvent(new Event('change', {{bubbles: true}}));"
    )


_VISIBILITY_JS = "return el.offsetParent !== null || el.getClientRects().length > 0;"

_CLICK_JS = (
    "if (typeof el.click === 'function') el.click();"
    " else el.dispatchEvent(new MouseEvent('click', {bubbles: true}));"
)
