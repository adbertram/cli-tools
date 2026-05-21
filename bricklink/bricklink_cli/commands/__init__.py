"""Command modules for Bricklink CLI."""
def run_browser(action):
    from ..config import get_config

    browser = get_config().get_browser()
    try:
        return action(browser)
    finally:
        browser.close()
