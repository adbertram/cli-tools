---
name: scrunch-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute scrunch operations using the `scrunch` CLI tool. Provides a
  CLI interface for Scrunch AI API operations including brand
  visibility, AI search analytics, competitors, personas, prompts, and
  agent traffic. Triggers: scrunch, scrunch cli, scrunch brands,
  scrunch competitors, scrunch personas, scrunch prompts, scrunch
  query, scrunch responses, scrunch page audits, scrunch agent traffic,
  AI search visibility, brand presence.
---

<objective>
Provide expert guidance for using the `scrunch` CLI tool to interact with the Scrunch AI API. Covers brand management, competitor tracking, persona configuration, prompt management, aggregated query metrics, AI response inspection, page audits, and agent traffic analysis.
</objective>

<quick_start>
```bash
scrunch auth login          # Configure API key
scrunch auth status         # Verify authentication
scrunch brands list --table # List all brands
scrunch query metrics 123 --fields date_week,brand_presence_percentage --start-date 2026-01-01 --end-date 2026-03-30
```
</quick_start>

<command_reference>
**Auth:**
- `scrunch auth login` — Store API key
- `scrunch auth status` — Check auth status using the shared profile JSON shape (`auth profiles[].authenticated` and `auth profiles[].credential_types.api_key`)
- `scrunch auth test` — Test API connection

**Brands:**
- `scrunch brands list [--table] [--limit N] [--filter F] [--properties P]`
- `scrunch brands get BRAND_ID [--table]`
- `scrunch brands create --name NAME --website URL [--description DESC]`
- `scrunch brands update BRAND_ID [--name NAME] [--website URL]`
- `scrunch brands delete BRAND_ID`

**Competitors** (nested under brand):
- `scrunch competitors list BRAND_ID [--table] [--limit N] [--filter F]`
- `scrunch competitors get BRAND_ID COMPETITOR_ID [--table]`
- `scrunch competitors create BRAND_ID --name NAME [--websites URL1,URL2]`
- `scrunch competitors update BRAND_ID COMPETITOR_ID --name NAME`
- `scrunch competitors delete BRAND_ID COMPETITOR_ID`

**Personas** (nested under brand):
- `scrunch personas list BRAND_ID [--table] [--limit N] [--filter F]`
- `scrunch personas get BRAND_ID PERSONA_ID [--table]`
- `scrunch personas create BRAND_ID --name NAME --description DESC`
- `scrunch personas update BRAND_ID PERSONA_ID --name NAME --description DESC`
- `scrunch personas delete BRAND_ID PERSONA_ID`

**Prompts** (nested under brand):
- `scrunch prompts list BRAND_ID [--table] [--limit N] [--filter F]`
- `scrunch prompts get BRAND_ID PROMPT_ID [--table]`
- `scrunch prompts create BRAND_ID --text TEXT --stage STAGE [--platforms P1,P2]`
- `scrunch prompts delete BRAND_ID PROMPT_ID`

Stages: Advice, Awareness, Evaluation, Comparison, Other
Platforms: chatgpt, claude, google_ai_overviews, perplexity, meta, google_ai_mode, google_gemini, copilot, grok

**Query** (aggregated metrics):
- `scrunch query metrics BRAND_ID --fields F1,F2 [--start-date DATE] [--end-date DATE] [--limit N] [--offset N] [--table]`

Dimensions: date, date_week, date_month, date_quarter, date_year, prompt_id, prompt, persona_id, persona_name, ai_platform, competitor_id, competitor_name, branded, stage, prompt_topic, country
Metrics: responses, brand_presence_percentage, brand_position_score, brand_sentiment_score, competitor_presence_percentage, competitor_position_score, competitor_sentiment_score

**Responses** (AI response data):
- `scrunch responses list BRAND_ID [--platform P] [--prompt-id ID] [--persona-id ID] [--stage S] [--start-date D] [--end-date D] [--limit N] [--table]`

**Page Audits:**
- `scrunch page-audits list BRAND_ID [--status S] [--url U] [--table]`
- `scrunch page-audits get BRAND_ID AUDIT_ID [--table]`
- `scrunch page-audits create BRAND_ID --urls URL1,URL2`

**Agent Traffic:**
- `scrunch agent-traffic get BRAND_ID SITE_ID --start-date DATE --end-date DATE [--fields F] [--time-bucket B] [--table]`
</command_reference>

<api_details>
Base URL: `https://api.scrunchai.com/v1`
Auth: Bearer token via `SCRUNCH_API_KEY` env var
Scopes: query, configure, create-brand
Pagination: `limit` + `offset` on list endpoints
Rate limiting: Honors `Retry-After` header with exponential backoff
</api_details>

<success_criteria>
- Command executes without errors
- Output is valid JSON (default) or formatted table (--table)
- Filters and limits are applied server-side where supported
</success_criteria>
