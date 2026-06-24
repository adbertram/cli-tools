from facebook_cli.browser import FacebookBrowser


def test_facebook_browser_keeps_auth_lifecycle_declarative():
    assert FacebookBrowser.SESSION_NAME == "facebook"
    assert FacebookBrowser.LOGIN_URL == "https://www.facebook.com/login"
    assert FacebookBrowser.AUTH_CHECK_URL == "https://m.facebook.com/"
    assert FacebookBrowser.AUTH_COOKIE_PATTERNS == ["c_user"]
    assert FacebookBrowser.MANUAL_LOGIN is True
