"""Real-Chrome User-Agent derivation for headless browser automation.

Headless Chrome presents ``HeadlessChrome/<version>`` in its User-Agent.
Bot-protection vendors (Cloudflare, Akamai, ...) treat that token as an
automation signal, and UA-bound clearance cookies (e.g. Cloudflare
``cf_clearance``) minted during a headed login are invalidated when the
headless UA differs. Deriving the UA from the installed Chrome binary lets a
CLI present the same real-Chrome UA headed and headless, tracking Chrome
upgrades automatically.

Usage (in a CLI's ``Config``)::

    from cli_tools_shared.browser.user_agent import derive_real_chrome_user_agent

    @property
    def browser_user_agent(self) -> str:
        override = self._get("BROWSER_USER_AGENT")
        if override:
            return override
        return derive_real_chrome_user_agent()
"""
import re
import subprocess
from typing import Optional

_UA_TEMPLATE = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/{version} Safari/537.36"
)

_derived_user_agent: Optional[str] = None


def _installed_chrome_version() -> str:
    """Return the installed Chrome version string (e.g. ``149.0.7827.201``).

    Locates Chrome via the shared browser-harness resolver, then reads its
    version with ``--version`` (no window, no CDP). Raises when Chrome cannot
    be located or its version parsed — a real-Chrome UA must never be guessed.
    """
    from cli_tools_shared.browser import driver

    chrome = driver._chrome_binary()
    result = subprocess.run(
        [chrome, "--version"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
    if not match:
        raise RuntimeError(
            f"Could not parse Chrome version from {chrome!r} --version output: "
            f"{result.stdout!r}"
        )
    return match.group(1)


def derive_real_chrome_user_agent() -> str:
    """Derive the real-Chrome UA to present headed AND headless.

    Built from the installed Chrome's full version with NO ``Headless`` token,
    so the same value is presented headed and headless. Derived once per
    process and cached.
    """
    global _derived_user_agent
    if _derived_user_agent is None:
        _derived_user_agent = _UA_TEMPLATE.format(version=_installed_chrome_version())
    return _derived_user_agent
