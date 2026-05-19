from cli_tools_shared.auth import BrowserAutomation


class PluralsightAuthorBrowser(BrowserAutomation):
    SESSION_NAME = "pluralsight-author"
    LOGIN_URL = "https://app.pluralsight.com/author-home/opportunities/all"
    AUTH_CHECK_URL = "https://app.pluralsight.com/author-home/opportunities/all"
    AUTH_URL_PATTERN = r"/id(?:[/?]|$)"
    LOGIN_REDIRECT_FRAGMENT = "/id?redirectTo=%2Fauthor-home%2Fopportunities%2Fall"
    LOGIN_PAGE_TITLE = "Sign In | Pluralsight"
