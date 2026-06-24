---
name: buttondown-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Buttondown operations using the `buttondown` CLI tool. Manage Buttondown subscribers, emails (including rendered HTML), tags, RSS-to-email feeds, event-driven automations, multi-newsletter authentication profiles, and cache through the Buttondown REST API.
  Triggers: buttondown, buttondown cli, buttondown subscribers, buttondown emails, buttondown tags, buttondown feeds, buttondown automations, buttondown render, list buttondown subscribers, create buttondown email, manage buttondown tags, buttondown rss, buttondown rss-to-email, buttondown external feed, buttondown automation, render buttondown email, my buttondown, buttondown newsletter data, buttondown profile, atalearning, psforsysadmins, brickbuddybeta
---

<objective>
Execute Buttondown operations using the `buttondown` CLI. All Buttondown API interactions should use this CLI.
</objective>

<quick_start>
The `buttondown` CLI follows this pattern:
```bash
buttondown [--profile NAME] <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check authentication | `buttondown auth status` |
| List profiles | `buttondown auth profiles list --table` |
| Create or switch profiles | `buttondown auth profiles create PROFILE` |
| Use a specific newsletter | `buttondown --profile atalearning emails list` |
| List subscribers | `buttondown subscribers list --limit 25` |
| Get a subscriber | `buttondown subscribers get SUBSCRIBER_ID_OR_EMAIL` |
| Create a draft email | `buttondown emails create --subject "Subject" --body-file ./draft.md` |
| List draft emails | `buttondown emails list --filter "status:eq:draft"` |
| Render an email as HTML | `buttondown --profile atalearning emails render EMAIL_ID --output /tmp/email.html` |
| Preview an email in browser | `buttondown --profile atalearning emails render EMAIL_ID --open` |
| List RSS feeds | `buttondown --profile atalearning feeds list --table` |
| Inspect an RSS feed | `buttondown --profile atalearning feeds get FEED_ID` |
| List automations | `buttondown --profile atalearning automations list --table` |
| Inspect an automation | `buttondown --profile atalearning automations get AUTOMATION_ID` |
| List tags | `buttondown tags list --table` |
| Get tag analytics | `buttondown tags analytics TAG_ID` |
</quick_start>

<principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `buttondown` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Login, logout, status, auth tests, and nested `auth profiles` management.
- **cache** -- Clear cached Buttondown CLI responses.
- **automations** -- List, get, create, update, and delete event-driven automations (e.g., welcome sequences triggered by `subscriber.confirmed`). Requires the newsletter's `automations` feature.
- **emails** -- List, get, create, update, delete, send draft, and render emails (HTML for inbox or web archive).
- **feeds** -- List, get, create, update, and delete RSS-to-email external feeds. Requires the newsletter's `rss` feature.
- **subscribers** -- List, get, create, update, delete, send magic links, and send reminders.
- **tags** -- List, get, create, update, delete, and inspect tag analytics.
</principle>

<principle name="Profile-Gated Features">
`feeds` and `automations` are per-newsletter features. The CLI refuses to run them under a profile whose newsletter lacks the feature and prints the enabled_features list. Never guess which profile to use — call `buttondown auth profiles list --table` first, then pick the profile whose newsletter has the required feature.
</principle>
</principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<domain_knowledge>
<topic name="Buttondown list pagination">
**Context:** Applies when maintaining or extending `buttondown subscribers list`, `buttondown emails list`, or `buttondown tags list`.
**Key Facts:** The Buttondown OpenAPI spec exposes `page_size` for `/tags`, but not for `/subscribers` or `/emails`. Keep `page_size` scoped to tags. Subscribers and emails should use the documented paginated response `next` link and stop after the requested `--limit`.
**Gotchas:** Do not add undocumented `limit` or `page_size` query parameters to subscribers or emails unless the OpenAPI spec changes.
</topic>

<topic name="Multi-newsletter profiles">
**Context:** The Buttondown account backing this CLI has multiple newsletters, each with its own per-newsletter API key. Use `--profile NAME` to target a specific newsletter.
**Key Facts:**
- Each `.env.NAME` file holds the API key for one newsletter.
- `buttondown auth profiles list --table` shows the available profiles.
- `/v1/accounts/me` returns the username scoped to a given API key; `/v1/newsletters` lists every newsletter visible to the key together with its `enabled_features`.
- Real newsletter profiles configured by default: `atalearning` (rss + automations), `psforsysadmins`, `brickbuddybeta` (archives/portal/api/tags/metadata only).
**Gotchas:** The bare `default` profile key may be scoped to a newsletter with limited features — if a feature gate fires, pass `--profile atalearning` (or another feature-enabled profile) explicitly.
</topic>

<topic name="RSS-to-email and automations endpoints">
**Context:** These features live behind separate REST endpoints that only respond when the newsletter has the matching feature flag.
**Key Facts:**
- RSS feeds: `/v1/external_feeds` (list/create) and `/v1/external_feeds/{id}` (get/patch/delete). Feed IDs start with `rss_`. Feed schema: `url`, `cadence` (every|daily|weekly|monthly), `behavior` (draft|emails), `cadence_metadata`, `filters` (FilterGroup object), `subject`, `body`, `label`, `metadata`, `skip_old_items`, `status` (active|failing|inactive|deleted).
- Automations: `/v1/automations`, `/v1/automations/{id}`. Automation IDs start with `aut_`. Schema: `name`, `trigger` (e.g., `subscriber.confirmed`, `email.sent`, etc.), `actions[]` (each has `type`, `metadata.email_id`, `timing.time`, `timing.delay`), `filters` (FilterGroup), `status` (active|inactive), `metadata`, `should_evaluate_filter_after_delay`.
- Required newsletter features: `rss` for `feeds`, `automations` for `automations`.
**Gotchas:** The endpoint path is `external_feeds` (underscore), NOT `rss-feeds`, `feeds`, or `rss`. Creating an RSS feed requires a non-null `filters` object like `{"filters":[],"groups":[],"predicate":"and"}`.
</topic>

<topic name="Email rendering">
**Context:** The `emails render` command returns fully rendered HTML from Buttondown's render endpoint. Works for drafts, scheduled, sent, and RSS-managed emails.
**Key Facts:**
- Endpoint: `GET /v1/emails/{id}/renders?target=email|html`.
- `--target email` returns the inbox-inlined rendering; `--target html` returns the web archive rendering. Both are fetched from the same endpoint with different query params.
- `--output FILE` writes to file; `--open` writes to a temp file and opens it in the default browser via `open`; neither prints the HTML to stdout.
- The command fails loudly on 404 / 403 / 400. There is no fallback to scraping `absolute_url`.
</topic>
</domain_knowledge>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
- For `feeds` / `automations`, the chosen `--profile` has the matching feature enabled
</success_criteria>
