---
name: wordpress-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute wordpress operations using the `wordpress` CLI tool.
  CLI interface for WordPress API -- manage posts, pages, media, categories, and tags.
  Triggers: wordpress, wordpress cli, wordpress posts, wordpress pages, wordpress page, update wordpress page, edit wordpress page, wordpress media, create wordpress post, upload wordpress image, wordpress categories, wordpress tags, publish blog post, wordpress blog, wordpress site
---

<objective>
Execute wordpress operations using the `wordpress` CLI. All wordpress interactions should use this CLI.
</objective>

<quick_start>
The `wordpress` CLI follows this pattern:
```bash
wordpress <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List posts | `wordpress posts list --table` |
| Get a post | `wordpress posts get POST_ID` |
| Create from Markdown | `wordpress posts create --from-markdown file.md` |
| Create from DOCX | `wordpress posts create --from-docx file.docx` |
| Publish a draft | `wordpress posts update POST_ID --status publish` |
| List pages | `wordpress pages list --table` |
| Get a page (raw HTML) | `wordpress pages get PAGE_ID --raw` |
| Find page by slug | `wordpress pages list --filter slug:eq:my-slug` |
| Update page content | `wordpress pages update PAGE_ID --content-file page.html` |
| Upload media | `wordpress media upload image.png` |
| List categories | `wordpress categories list --table` |
| List tags | `wordpress tags list --table` |
| List plugins | `wordpress admin plugins list --table` |
| Upgrade plugin | `wordpress admin plugins upgrade PLUGIN` |
| List themes | `wordpress admin themes list --table` |
| Preview theme file push | `wordpress admin themes file-push THEME LOCAL_FILE REMOTE_FILE --remote-root /path/to/wp --host host --dry-run` |
| Push theme file | `wordpress admin themes file-push THEME LOCAL_FILE REMOTE_FILE --remote-root /path/to/wp --host host --backup --yes` |
| Save WordPress.com OAuth credentials | `wordpress org token save-credential --client-id ... --client-secret ... --username ... --password ... --site ...` |
| Refresh WordPress.com token | `wordpress org token` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `wordpress` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication commands and nested `auth profiles` management
- **auth** — Authentication: login, logout, status, refresh, test
- **posts** — Full post lifecycle: list, get, create (from DOCX/Markdown), update, delete
- **pages** — Page lifecycle: list, get, create (from DOCX/Markdown), update (supports --content-file), delete. Pages support `parent`, `menu_order`, `template` (no tags/categories/format).
- **media** — Media library: list, get, upload, delete
- **categories** — Category management: list, get, create, update, delete
- **tags** — Tag management: list, get, create, update, delete
- **admin** — WordPress admin maintenance, including plugin list/get/activate/deactivate/delete/install/upgrade and theme list/get/file-push through explicit SSH settings
- **org** — WordPress.com OAuth token commands used by Jetpack plugin updates
</principle>

<principle name="Ad-Hoc Internal Imports">
If a diagnostic task must import WordPress CLI internals directly, use the live
`wordpress` launcher shebang interpreter and the actual source module paths.
There is no `wordpress_cli.auth` module; auth commands are mounted from shared
CLI tooling, and the WordPress API client factory lives in `wordpress_cli.client`.
For task-workspace scripts that intentionally import `wordpress_cli.client`, do
not add local `sys.path` bootstraps to satisfy Pyright; run the script with the
launcher-derived interpreter and, if Hermes reports `reportMissingImports`, add a
line-local suppression such as
`from wordpress_cli.client import get_client  # pyright: ignore[reportMissingImports]`.

```bash
launcher="$(command -v wordpress)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" - <<'PY'
from wordpress_cli.client import get_client

client = get_client()
PY
```
</principle>
<principle name="ACF Options Writes">
ACF options can be read from the site's ACF to REST API endpoint, for example
`GET /wp-json/acf/v3/options/options/site_ad_settings`, but do not use that
endpoint for ATA sitewide option writes. On the ATA Blog, ACF to REST API 3.3.4
advertises editable options routes, but authenticated administrator no-op POST,
PUT, and PATCH probes to `/acf/v3/options/options/site_ad_settings`,
`/acf/v3/options/options/site_ad_settings_logo`, `/acf/v3/options/option`, and
`/acf/v3/options/options` all return `500 Cannot update item`, including the
documented `fields[...]` body shape. Treat this as an unavailable REST write
capability, not a payload-shape typo.

For ATA sitewide ACF option changes, use a server-side WordPress execution path
that loads ACF, such as WP-CLI on the WordPress host, and update the ACF option
fields with `update_field(..., 'option')` after backing up the REST GET response.
Example method for the sitewide ad settings:

```bash
wp eval 'update_field("site_ad_settings_logo", 26999, "option"); update_field("site_ad_settings_link", "https://specopssoft.com/product/specops-password-auditor/?utm_source=adamtheautomator&utm_medium=referral&utm_campaign=adamtheautomator_referral_na&utm_content=display", "option"); update_field("site_ad_settings_text", "<p>Audit your Active Directory for weak passwords and risky accounts. <strong><a href=\"https://specopssoft.com/product/specops-password-auditor/?utm_source=adamtheautomator&amp;utm_medium=referral&amp;utm_campaign=adamtheautomator_referral_na&amp;utm_content=display\">Run your free Specops scan</a> now!</strong></p>\n", "option");'
```

Preserve valid HTML and use `&amp;` inside HTML attributes when updating the copy
field. Verify with `GET /wp-json/acf/v3/options/options/site_ad_settings`.
</principle>

<principle name="Theme-Constrained Page Layouts">
Many themes wrap page content in a narrow typography container (Tailwind `prose`
+ `max-w-[NNch]`, a constrained `entry-content`, etc.). Rendering a rich
landing/About page as plain blocks inside such a container looks broken: it is
too narrow for multi-column layouts, and the typography styles restyle headings
and underline button links. The fix is NOT a full-page custom shell that hides
the theme's header/nav or forces full-bleed -- that fights the theme.

When a page needs a custom landing layout, build it as ONE self-contained
`<!-- wp:html -->` block instead of plain blocks:
- First DISCOVER the wrapper: load the live page and inspect the content
  ancestor chain (DevTools or `playwright-cli eval`) to find the class and the
  `max-width` that constrains content.
- Namespace all styles under a wrapper class and give every styled element a
  class. If the theme uses Tailwind Typography, its rules use `:where()` (zero
  specificity), so class-based rules override them without `!important`.
- Widen only that page's column with a page-scoped selector
  (`body.page-id-<ID> .<content-wrapper>{max-width:100%}`) -- never a global
  override.
- Keep the theme header, nav, and footer; do not hide chrome.
- Drive component colors from CSS variables and SUPPORT the theme's dark mode:
  detect its strategy first (a `.dark`/`.theme-dark` class toggled on `<html>`
  or `<body>`, vs. `@media (prefers-color-scheme: dark)`), then redefine the
  variables under that selector so the page re-skins to match the dark chrome
  instead of sitting as a light island. Verify both modes with screenshots.

Always visually verify the live page after the update (screenshot desktop and
mobile) and iterate against the target design before calling it done.
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
