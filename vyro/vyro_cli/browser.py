"""Declarative Vyro login through the shared persistent browser engine."""
from cli_tools_shared.auth import BrowserAutomation

AUTH_CONTEXT_URL = "https://app.vyro.com/favicon.ico"


class VyroBrowser(BrowserAutomation):
    LOGIN_URL = "https://app.vyro.com/login"
    # Use a static same-origin document. Loading the campaigns SPA starts its
    # own refresh/redirect flow before our probe and can send a fresh captured
    # session back to /login. The probe below owns the single refresh exchange.
    AUTH_CHECK_URL = "https://app.vyro.com/favicon.ico"
    AUTH_URL_PATTERN = r"/login(?:/|\?|$)"
    # ``vyro_rt`` can remain present after Vyro rejects it and was also an
    # unreliable post-login signal. Verify the same refresh exchange every
    # data command needs instead of treating cookie presence as authentication.
    AUTH_FAILURE_PAGE_JS = r"""async () => {
        try {
            const response = await fetch('https://api.vyro.com/auth/refresh', {
                method: 'POST',
                credentials: 'include',
                headers: {'x-realm': 'vyro-app'},
                signal: AbortSignal.timeout(20000),
            });
            let data;
            try {
                data = await response.json();
            } catch (_) {
                return response.ok
                    ? 'invalid_json'
                    : 'http_status_' + response.status;
            }
            if (!response.ok) {
                const candidate = data?.errorCode || data?.errors?.[0];
                const code = typeof candidate === 'string'
                    && /^[A-Z][A-Z0-9_]{1,80}$/.test(candidate)
                    ? '_code_' + candidate.toLowerCase()
                    : '';
                return 'http_status_' + response.status + code;
            }
            return typeof data?.accessToken !== 'string' || !data.accessToken
                ? 'missing_access_token'
                : false;
        } catch (_) {
            return 'request_failed';
        }
    }"""
    SESSION_NAME = "vyro"
    MANUAL_LOGIN = True
