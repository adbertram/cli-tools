"""Browser automation hooks for Adobe Podcast CLI."""

from cli_tools_shared.auth import BrowserAutomation


class AdobePodcastBrowser(BrowserAutomation):
    """Declarative browser hooks for Adobe Podcast auth.

    Adobe IMS login flow blocks CDP automation, so MANUAL_LOGIN = True opens a
    plain browser window. After the user logs in, client.py uses get_browser()
    to extract the IMS access token from window.adobeIMS via a headless session.
    """

    SESSION_NAME = "adobe-podcast"
    LOGIN_URL = "https://podcast.adobe.com/en/enhance"
    AUTH_CHECK_URL = "https://podcast.adobe.com/en/enhance"
    AUTH_URL_PATTERN = r"adobelogin\.com|adobeid|ims-na1"
    AUTH_SUCCESS_URL = r"podcast\.adobe\.com"
    MANUAL_LOGIN = True
