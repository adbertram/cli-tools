"""Browser automation sub-package.

Public API:
- BrowserHarnessError  — exception for all service errors
- BrowserHarnessService — unified browser automation service (lazy-loaded)
- WebwrightBrowserService — optional Webwright-backed service (lazy-loaded)

The persistent Chromium user-data-dir for each profile is owned by
``cli_tools_shared.config.BaseConfig.get_persistent_profile_dir()`` and
passed into ``BrowserHarnessService.browser_open(persistent_profile_dir=...)``
by callers. There is no shared / legacy daemon-profiles path any more.
"""


class BrowserHarnessError(Exception):
    """Error from BrowserHarnessService operations."""


PlaywrightServiceError = BrowserHarnessError


def __getattr__(name):
    if name == "BrowserHarnessService":
        from .driver import BrowserHarnessService
        return BrowserHarnessService
    if name in ("WebwrightBrowserService", "WebwrightServiceError"):
        from .webwright import WebwrightBrowserService, WebwrightServiceError
        webwright_exports = {
            "WebwrightBrowserService": WebwrightBrowserService,
            "WebwrightServiceError": WebwrightServiceError,
        }
        return webwright_exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
