---
name: moz-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute moz operations using the `moz` CLI tool.
  CLI interface for Moz API -- SEO keyword research and analysis.
  Triggers: moz, moz cli, moz keywords, keyword research, keyword volume, keyword difficulty, search intent, keyword suggestions, keyword ranking, seo metrics, moz seo
---

<objective>
Execute moz operations using the `moz` CLI. All moz interactions should use this CLI.
</objective>

<quick_start>
The `moz` CLI follows this pattern:
```bash
moz <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get metrics for a single keyword | `moz keywords get "keyword"` |
| Get metrics for multiple keywords | `moz keywords list -k "kw1,kw2,kw3"` |
| Get keyword suggestions | `moz keywords suggestions "keyword"` |
| Analyze search intent | `moz keywords intent "keyword"` |
| Find keywords a URL ranks for | `moz keywords ranking "https://example.com"` |
| Check auth status | `moz auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `moz` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage Moz API authentication (login, logout, status)
- **keywords** -- Keyword research and analysis (get, list, suggestions, intent, ranking)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Known Issues

### 1. `moz keywords suggestions` and `moz keywords ranking` returned "Action not found"

**Symptom:** Running `moz keywords suggestions "<keyword>"` or `moz keywords ranking "<url>"` returned an HTTP 400 from the Moz API with `Action not found: Keywordsuggestions` or `Action not found: Rankingkeywords`. Other `moz keywords` subcommands (`get`, `list`, `intent`) worked fine.

**Cause:** `moz_cli/client.py` used invalid JSON-RPC method strings (`KeywordSuggestions`, `RankingKeywords`) instead of Moz's V3 dotted `data.<resource>.<verb>` namespace. The Moz API normalizes unknown action names by lowercasing all but the first letter, which is why the error reported `Keywordsuggestions` / `Rankingkeywords`. The params shape was also wrong — both endpoints require a wrapped `serp_query` (and `target_query` for ranking), not a flat `{keyword: ...}` or `{url: ...}`.

**Fix:** Update `~/Dropbox/GitRepos/cli-tools/moz/moz_cli/client.py`:
- `get_keyword_suggestions` now calls `data.keyword.suggestions.list` with a `serp_query` block (`keyword`, `locale`, `device`, `engine`).
- `get_ranking_keywords` now calls `data.site.ranking.keywords.list` with a `target_query` block (`query`, `scope`, `locale`), a `serp_query` block (`engine`, `locale`), and a `limit`. Valid scopes per the API: `domain`, `subdomain`, `subfolder`, `url` (NOT `page`/`root_domain` — those belong to other endpoints).
- The ranking response field is `ranking_keywords` (not `keywords`).
- `RankingKeyword.volume` is `Optional[float]` because the ranking endpoint returns fractional volumes (e.g. `10.53708...`). `KeywordMetrics.volume` remains `int` — those are separate API shapes.

**Verification:**
```bash
moz keywords get "powershell"                                                # baseline still works
moz keywords suggestions "powershell" --limit 5                              # returns JSON or quota error, not "Action not found"
moz keywords ranking "https://adamtheautomator.com/netstat-port/" --limit 5  # same
```
A non-`Action not found` response confirms the action name reaches the API. A `403: The account does not have enough quota remaining` response is an account-level quota condition (specific quota pools for suggestions/ranking endpoints), NOT a regression — wait for the quota window to reset.

**Recurrence Prevention:** Moz API V3 method names follow `data.<resource>.<sub-resource>.<verb>` (e.g. `data.keyword.metrics.fetch`, `data.keyword.search.intent.fetch`, `data.keyword.suggestions.list`, `data.site.ranking.keywords.list`). Params always go in `params.data.<wrapper>`, where `<wrapper>` is `serp_query`, `target_query`, or `data`-level fields per the endpoint. When adding any new Moz endpoint, never invent CamelCase method names — confirm the V3 dotted form against an existing working method or against a known-working reference like https://github.com/metehan777/moz-mcp.

**General rule:** When a vendor API returns "Action not found" with a re-cased action string, the method name is wrong, not the auth or the request body — the server is rejecting the action lookup before it parses params. Verify the exact method string against working sibling endpoints in the same SDK before changing anything else.
