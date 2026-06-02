---
name: medium-cli
description: >-
  MANDATORY: Execute medium operations using the `medium` CLI tool.
  Authenticate with a saved Medium browser session and create Medium drafts through the real web composer.
  Do not use Medium integration tokens or the archived Medium API path.
  Triggers: medium, medium cli, medium draft, medium post create, publish to medium, medium auth, medium browser session, medium composer
---

<objective>
Execute Medium operations using the `medium` CLI. All Medium interactions should use this CLI.
</objective>

<quick_start>
The `medium` CLI follows this pattern:
```bash
medium <command-group> <action> [arguments] [options]
```

| Command | Use |
| --- | --- |
| `medium auth status` | Check whether any saved profile has a valid Medium browser session |
| `medium auth login` | Open Medium sign-in and save the browser session for later CLI use |
| `medium auth test` | Verify that the saved session can still load Medium's composer |
| `medium posts create --title "Hello" --content-file ./post.md` | Create a Medium draft from a file |
| `medium posts create --title "Hello" --content "<p>Hello</p>" --table` | Create a Medium draft from inline content and show the result as a table |
| `medium cache clear` | Clear cached Medium responses |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `medium` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Browser Session Only">
This CLI uses Medium's real web composer and a saved browser session. Do not ask for or use Medium integration tokens, and do not route work through the archived API.
</principle>

<principle name="Command Groups">
- `auth`: Save, verify, clear, and profile-manage Medium browser sessions.
- `posts`: Create Medium drafts through `https://medium.com/new-story`.
- `medium auth login` runs headed for manual sign-in. Normal commands run headless after authentication using the CLI's configured desktop Chrome identity.
- `cache`: Clear cached Medium responses.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
