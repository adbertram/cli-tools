"""Declarative Whop session authentication using the shared browser engine."""
from cli_tools_shared.auth import BrowserAutomation

class WhopBrowser(BrowserAutomation):
    LOGIN_URL = "https://whop.com/login/"
    AUTH_CHECK_URL = "https://whop.com/"
    AUTH_URL_PATTERN = r"/login(?:/|\?|$)"
    AUTH_COOKIE_PATTERNS = ["whop-core.access-token"]
    AUTH_FAILURE_PAGE_JS = """async () => {
        try {
            const r = await fetch('/api/v1/users/me', {credentials:'include', signal:AbortSignal.timeout(15000)});
            if (!r.ok) return true;
            const d = await r.json();
            return !(typeof d.id === 'string' && d.id.startsWith('user_') && typeof d.username === 'string');
        } catch (_) { return true; }
    }"""
    SESSION_NAME = "whop"
    MANUAL_LOGIN = True
