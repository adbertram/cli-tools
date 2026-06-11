---
name: impact-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute impact operations using the `impact` CLI tool.
  Impact.com Publisher API CLI plus a `marketplace` command group that emits browser-automation instructions (no public Impact discovery API exists).
  Triggers: impact, impact cli, impact account, impact campaigns, impact ads, impact actions, impact catalogs, impact reports, impact websites, list impact programs, export impact report, impact publisher data, impact marketplace, browse impact brands, impact marketplace search, impact apply to brand, impact list categories, impact discovery, find impact brands
---

<objective>
Execute Impact.com Publisher API operations using the `impact` CLI. All Impact.com account, program, ad, action, catalog, report, click, job, and website interactions should use this CLI.
</objective>

<quick_start>
The `impact` CLI follows this pattern:
```bash
impact <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `impact auth login` |
| Check auth | `impact auth status` |
| Account info | `impact account get` |
| List programs | `impact campaigns list --limit 10` |
| List ads | `impact ads list --limit 10` |
| List actions | `impact actions list --limit 10` |
| Export report | `impact reports export REPORT_ID --json-file params.json` |
| Manage websites | `impact websites list` |
| Discover marketplace programs (browser instructions) | `impact marketplace search --keyword fitness` |
| Apply to a marketplace program (browser instructions) | `impact marketplace apply PROGRAM_ID` |
| List marketplace categories (browser instructions) | `impact marketplace list-categories` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `impact` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Authentication">
Use `impact auth login` to store `IMPACT_ACCOUNT_SID` and `IMPACT_AUTH_TOKEN`. API calls use Basic Auth and account-scoped MediaPartner paths.
</principle>

<principle name="Output Controls">
List commands use `--limit/-l`, `--filter/-f`, `--properties/-p`, and `--table/-t` when those flags appear in `usage.json`. Mutating commands read JSON from `--json-file` or stdin, and destructive commands require `--force/-F`.
</principle>

<principle name="AI Instruction Results">
After every `impact` command, inspect stdout. If it is JSON with `type: "ai_instruction"` and `schema_version: "1.0"`, follow the instruction object as the next task instead of summarizing it as ordinary command output.
</principle>

<principle name="Command Groups">
- `account` — Manage account data
- `campaigns` — Manage programs and program assets
- `ads` — Manage ads
- `actions` — Manage actions
- `catalogs` — Manage catalogs
- `reports` — Run and export reports
- `clicks` — Retrieve and export clicks
- `jobs` — Manage async jobs
- `websites` — Manage websites
- `auth` — Manage impact authentication
- `cache` — Manage response cache
- `marketplace` — Generate browser-automation instructions for Impact marketplace flows. Impact has NO public discovery API; this group emits structured JSON for `playwright-cli` to drive the partner-portal UI. Subcommands: `search`, `apply <PROGRAM_ID>`, `list-categories`. Default output is JSON; `--text` renders the same instruction in human-readable form. The JSON includes a top-level `disclaimer` field flagging the no-API constraint.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used after checking usage.json
</success_criteria>

## Known Issues

### 1. Marketplace commands emitted a stale 404 URL

**Symptom:** `impact marketplace search`, `impact marketplace apply`, and `impact marketplace list-categories` produced playwright-cli instructions whose `target_url` was `https://app.impact.com/secure/marketplace/brand-listings.ihtml`. The agent following the steps received an HTTP 404 "Page Not Found" body inside the impact.com chrome — the URL was the publisher's post-login redirect target but Impact retired the path. Direct probes of related variants (`/secure/`, `/secure/mediapartner/`, `/secure/affiliate/`, `/secure/dashboard.ihtml`, `/secure/mediapartner/dashboard.ihtml`) also 404d, confirming the publisher portal UI had migrated, not the whole `app.impact.com` host.

**Cause:** Impact migrated the publisher Brand Marketplace SPA from the legacy `/secure/marketplace/brand-listings.ihtml` path to `/secure/mediapartner/marketplace/new-campaign-marketplace-flow.ihtml`. The legacy path was hardcoded in `impact_cli/models/marketplace_instructions.py` (`PORTAL_MARKETPLACE_URL`). Additional staleness existed in the instruction steps (no tab selection — the default landing tab is 'Home', a curated subset; no `.brands-card` selector hint; an invented `?programId=` deep link that does not exist; outdated `extraction_target.fields` like `EPC` and `apply_url` that the SPA never exposes).

**Fix:** In `impact_cli/models/marketplace_instructions.py`:
- Set `PORTAL_MARKETPLACE_URL = "https://app.impact.com/secure/mediapartner/marketplace/new-campaign-marketplace-flow.ihtml"`.
- Add `PORTAL_MARKETPLACE_SEARCH_URL_TEMPLATE = PORTAL_MARKETPLACE_URL + "#joinState=all&q={keyword}"` (the SPA reads the search keyword from the URL fragment on initial render).
- Update `PORTAL_LOGIN_URL` to the canonical `https://app.impact.com/login.user` (Impact redirects `/secure/login.ihtml` to login.user).
- In `build_search_instruction`, emit a `select_tab` step that clicks 'All Brands' before harvesting (the default 'Home' tab is curated/limited), pass the search input selector `input[placeholder='Search for a brand or enter a prompt']`, and replace the imaginary `apply_url`/`EPC` fields with real ones derived from the SPA: `program_name`, `advertiser`, `category`, `terms_summary`, `program_id` (parsed from `display-logo-via-campaign/<id>.gif` in the card's logo URL), `join_state`.
- In `build_apply_instruction`, REMOVE the imaginary `?programId=<id>` deep link. Navigate to the marketplace landing page, click 'All Brands', locate the `.brands-card` whose logo URL matches the campaign id via regex, then click the inline 'Apply' button on that card — there is no separate apply URL.
- In `build_list_categories_instruction`, click 'All Brands' first, then click the 'Categories' filter chip to open its dropdown.

**Verification:**
1. Reinstall: `uv tool install -e ~/Dropbox/GitRepos/cli-tools/impact --force --refresh`.
2. Check emitted URL: `impact marketplace search --keyword "PowerShell" --text` must show `Target URL: https://app.impact.com/secure/mediapartner/marketplace/new-campaign-marketplace-flow.ihtml#joinState=all&q=PowerShell`.
3. End-to-end: with an authenticated `playwright-cli -s=impact` session, `playwright-cli -s=impact goto "<the new target URL>"` must produce a page with title `impact.com - Brand Marketplace` (NOT `Page Not Found`) and a result grid with `N rows` count above it.

**Recurrence Prevention:** Impact has shown a willingness to retire portal URLs. The structured_context block of every marketplace instruction now includes the selectors (`.brands-card`, `input[placeholder=...]`, `category_filter_trigger_text`) and the `campaign_id_regex` so a future URL migration only needs the URL constant updated, not the entire instruction shape. When updating, always validate with a live playwright-cli session against the publisher account before shipping — Impact help-center pages can lag the actual UI by months.

**General rule:** Browser-automation instruction generators that hardcode third-party portal URLs are tomorrow-bugs. Validate every URL against a live authenticated session before publishing, and structure instructions so that selectors, fragment formats, and IDs live in one named constant per UI element.

### 2. Marketplace `q=<keyword>` URL fragment silently fails on Home tab and is dropped on tab switch

**Symptom:** Navigating to `…/new-campaign-marketplace-flow.ihtml#joinState=all&q=PowerShell` renders the marketplace SPA on the 'Home' tab (default) with the search box pre-filled but the grid shows `0 rows` — even though the keyword would return non-zero on 'All Brands'. After clicking the 'All Brands' tab the URL fragment is rewritten to `…#joinState=all` (the `q=` portion is dropped) and the search box clears, so naive follow-up snapshots show an unfiltered grid.

**Cause:** Impact's SPA treats the URL fragment as initial-state-only and tied to the Home tab's curated subset. Tab clicks rewrite the fragment, so the fragment is effectively useless for any keyword-based search workflow. The search input itself is the only authoritative source of the active query, and it must be filled AFTER the tab switch.

**Fix:** In `impact_cli/models/marketplace_instructions.py` `build_search_instruction`:
- Keep the URL-fragment target_url for backwards compat / first-paint behavior, but mark it as advisory.
- Make the `select_tab` step mandatory (click 'All Brands') and warn that the click drops `q=<keyword>`.
- Make the `fill_search` step mandatory when a keyword is specified (do not gate it on URL-fragment behavior).
- Require an explicit `press Enter` after `fill` — `fill` alone does not submit.
- Surface the row-count indicator regex `^\|?\s*([\d,]+) rows$` so harvesters can short-circuit on `0 rows` and detect grid settling before scrolling.

**Verification:**
1. `impact marketplace search --keyword PowerShell --text` shows the WARNING in step 2 and the mandatory fill_search step 5 with `'submit': 'press Enter after fill'`.
2. End-to-end against the `impact` playwright session: navigate to the search URL, snapshot, click 'All Brands', fill the search input with the keyword, press Enter, wait, snapshot — the row-count indicator must reflect the keyword-filtered count (e.g. `windows` → 6 rows, `developer` → 34 rows, `PowerShell` → 0 rows). All three were verified 2026-05-13.

**Recurrence Prevention:** The instruction's `structured_context` block now declares `tabs.side_effect_on_tab_switch` and `row_count_regex` as first-class fields, and the constraints list calls out (a) the fragment-drop on tab switch, (b) fill-does-not-submit, and (c) the `$USERNAME` shell-var trap that silently truncated the username during testing. Future updates to the SPA that change these behaviors must update the same single block.

**General rule:** SPA URL fragments are first-paint state, not durable query state. Any instruction that relies on URL fragments must (a) drive the actual UI control afterward, and (b) verify with a state indicator (row count, search box value) before harvesting.

### 3. Impact credentials are NOT in LastPass — use the CLI-tools secret manager

**Symptom:** Following the prior auth guidance (`lastpass show 'app.impact.com' --notes`) returns "No such command" or the entry is missing — wasted a multi-step lookup against a vault that has no impact entry.

**Cause:** The skill historically referenced LastPass as the credential source. Adam's vault has no `app.impact.com` entry; impact credentials live in the CLI-tools Keychain-backed secret manager under names `impact-username` and `impact-password`. An authenticated persistent browser profile also exists at `.playwright-cli/profiles/impact`.

**Fix:** All marketplace instruction outputs and SKILL guidance now reference `/Users/adam/Dropbox/GitRepos/cli-tools/secret-manager/secrets.sh get impact-username|impact-password`. The `_common_login_steps()` action arguments include `credentials_source: "cli-tools-secret-manager"`, `username_secret`, `password_secret`, and `profile_path` so future agents look in the right place first.

**Verification:** `impact marketplace search --keyword X | jq '.steps[0].arguments'` must show `credentials_source: cli-tools-secret-manager` and the secret names — not a `lastpass_entry` reference.

**Recurrence Prevention:** Credential source is now a structured field on the instruction (not free-text in a description). Adding a new vendor that uses the same store only requires changing the secret names.

**General rule:** Credential lookups in instruction generators must reference the canonical store by structured key, not by free-text prose. Free-text references rot when vault names change; structured fields force the update.
