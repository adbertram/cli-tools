from brickowl_cli.browser import _BrickOwlAutomation


def test_login_url_targets_live_brickowl_login_route():
    assert (
        _BrickOwlAutomation.LOGIN_URL
        == "https://www.brickowl.com/user?destination=mystore/orders"
    )


def test_auth_url_pattern_matches_current_login_routes():
    assert _BrickOwlAutomation._is_login_page(
        _BrickOwlAutomation, "https://www.brickowl.com/user"
    )
    assert _BrickOwlAutomation._is_login_page(
        _BrickOwlAutomation, "https://www.brickowl.com/user/login"
    )
    assert _BrickOwlAutomation._is_login_page(
        _BrickOwlAutomation,
        "https://www.brickowl.com/user?destination=mystore/orders",
    )
    assert not _BrickOwlAutomation._is_login_page(
        _BrickOwlAutomation, "https://www.brickowl.com/mystore/orders"
    )
