"""JavaScript snippet constants and generators for browser element interaction."""

import json


def _fill_js(text: str) -> str:
    """JS body to set value via the native setter and dispatch input+change."""
    return (
        f"const __cliToolsValue = {json.dumps(text)};"
        " const __cliToolsProto ="
        " el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype :"
        " el instanceof HTMLInputElement ? HTMLInputElement.prototype : null;"
        " const __cliToolsDescriptor ="
        " __cliToolsProto ? Object.getOwnPropertyDescriptor(__cliToolsProto, 'value') : null;"
        " if (__cliToolsDescriptor && typeof __cliToolsDescriptor.set === 'function') {"
        " __cliToolsDescriptor.set.call(el, __cliToolsValue);"
        " } else {"
        " el.value = __cliToolsValue;"
        " }"
        f" el.dispatchEvent(new Event('input', {{bubbles: true}}));"
        f" el.dispatchEvent(new Event('change', {{bubbles: true}}));"
    )


_VISIBILITY_JS = "return el.offsetParent !== null || el.getClientRects().length > 0;"

_CLICK_JS = (
    "if (typeof el.click === 'function') el.click();"
    " else el.dispatchEvent(new MouseEvent('click', {bubbles: true}));"
)
