# Facebook CLI - Claude Instructions

This is a **browser automation CLI** that uses `BrowserAutomation` from `cli_tools_shared`.

Always read the README.md file first when working with this CLI tool.

## Key Concepts

- **Auth type**: Browser session via BrowserAutomation (persistent Playwright profiles)
- **Browser class**: `FacebookBrowser` in `browser.py` (subclasses `BrowserAutomation`)
- **Session detection**: Uses `c_user` cookie pattern to verify Facebook login
- **Shared browser session**: Marketplace, Messenger, and Groups use the same browser session

## Architecture

```
facebook <command>  -->  FacebookClient  -->  FacebookBrowser.get_page()  -->  page.evaluate(JS)  -->  parse results
```

## Customization Points

1. **`browser.py`**: BrowserAutomation subclass with Facebook-specific auth hooks
2. **`client.py`**: All Facebook operations using Playwright page API (evaluate, goto, etc.)
3. **`parsers.py`**: Marketplace snapshot parsers (parse ARIA accessibility tree YAML)
4. **`messenger_parsers.py`**: Messenger snapshot parsers (parse ARIA accessibility tree YAML)
5. **`config.py`**: BaseConfig subclass with `get_browser()` accessor
