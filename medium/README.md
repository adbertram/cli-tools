# Medium CLI

## DESCRIPTION

The `medium` CLI lets you create Medium drafts through Medium's web composer.

Use it when you need repeatable access to medium workflows that are only available through a signed-in website.

## Installation

```bash
cd <cli-tools-root>/medium
uv tool install -e . --force --refresh
```

The CLI installs the `medium` command.

## Authentication

Authenticate with a browser session:

```bash
medium auth login
medium auth status
medium auth test
medium auth logout
```

Profile management:

```bash
medium auth profiles list
medium auth profiles get default
medium auth profiles create work
medium auth profiles select work
```

`medium auth login` opens Medium's sign-in flow in a browser window. After you complete sign-in, return to the terminal and press Enter so the CLI can save the browser session.

## Commands

### `posts`

Create a Medium draft from inline content:

```bash
medium posts create \
  --title "Hello Medium" \
  --content "This draft was created through the Medium web composer."
```

Create a Medium draft from a file:

```bash
medium posts create \
  --title "Release Notes" \
  --content-file ./release-notes.md
```

Show the result as a table:

```bash
medium posts create \
  --title "Hello Medium" \
  --content-file ./draft.md \
  --table
```

Supported options:

```bash
medium posts create --help
```

Required content rule:
- Provide exactly one of `--content` or `--content-file`.

Composer behavior:
- The CLI opens `https://medium.com/new-story`.
- It fills the visible title and body editor regions.
- It waits for Medium to autosave the story to a draft edit URL shaped like `https://medium.com/p/<id>/edit`.
- It returns the saved draft edit URL.

### `cache`

Clear cached Medium responses:

```bash
medium cache clear
```

## Output

Default output is JSON. Use `--table` for tabular display on supported commands.

Draft result fields:
- `title`
- `draft_url`
- `edit_url`

## Configuration

Profile env files live under the shared cli-tools profile storage managed by `cli_tools_shared`.

Example profile fields:

```bash
ACTIVE=true
BASE_URL=https://medium.com
BROWSER_USER_AGENT=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36
BROWSER_WINDOW_SIZE=1280,900
HEADLESS=true
```

`medium auth login` always opens a headed browser for manual sign-in. Command execution defaults to headless after authentication while using a desktop Chrome identity so Medium serves the web composer.

## Examples

Check whether the saved browser session is valid:

```bash
medium auth status
medium auth test
```

Create a draft from a Markdown or plain-text file:

```bash
medium posts create \
  --title "Weekly Update" \
  --content-file ./weekly-update.md
```

Clear a saved browser session:

```bash
medium auth logout
```
