"""Command modules for Bricklink CLI."""
def run_browser(action):
    from ..browser import get_browser

    browser = get_browser()
    try:
        return action(browser)
    finally:
        browser.close()


def render_list(data, table, properties, columns, headers, filter=None, limit=None):
    from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter
    from ..display import print_list

    if filter:
        data = apply_filters(data, filter)
    if properties:
        data = apply_properties_filter(data, properties)
    data = apply_limit(data, limit)
    print_list(data, table, properties, columns, headers)
