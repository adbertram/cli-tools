# Impact CLI

## DESCRIPTION

The `impact` CLI provides command-line access to Impact.com Publisher API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Authentication

```bash
impact auth login
impact auth status
impact auth profiles list
impact auth logout
```

The CLI stores `IMPACT_ACCOUNT_SID` and `IMPACT_AUTH_TOKEN` in the selected profile and sends requests with Basic Auth.

## Command Groups

Every list command supports `--table/-t`, `--limit/-l`, `--filter/-f`, and `--properties/-p`. Every get-style output command supports `--table/-t`.

### account

```bash
impact account get
impact account list --table
impact account update --json-file account.json
impact account users list --limit 10 --properties id,name
impact account users get USER_ID --table
impact account invoices list --limit 10
impact account invoices get INVOICE_ID
impact account invoices download INVOICE_ID
impact account tax-documents list
impact account tax-documents get TAX_DOCUMENT_ID
impact account tax-documents latest
impact account tax-documents create --json-file tax-document.json
impact account tax-documents complete --json-file submission.json
impact account withdrawal-settings list
impact account withdrawal-settings get
impact account withdrawal-settings update --json-file withdrawal.json
impact account withdrawal-settings required-fields --bank-country US
```

### campaigns

```bash
impact campaigns list --limit 10 --table
impact campaigns get CAMPAIGN_ID
impact campaigns logo CAMPAIGN_ID
impact campaigns contracts list
impact campaigns contracts get CONTRACT_ID
impact campaigns contracts active CAMPAIGN_ID
impact campaigns contracts public-terms CAMPAIGN_ID
impact campaigns promotions list
impact campaigns promotions get PROMOTION_ID
impact campaigns deals list CAMPAIGN_ID
impact campaigns deals get CAMPAIGN_ID DEAL_ID
impact campaigns tracking-link PROGRAM_ID --json-file tracking-link.json
```

### ads

```bash
impact ads list --limit 10 --filter CampaignId:eq:123
impact ads get AD_ID
impact ads code AD_ID
impact ads iframe-code AD_ID
impact ads tracking-link AD_ID
```

### actions

```bash
impact actions list --limit 10
impact actions get ACTION_ID
impact actions items ACTION_ID
impact actions item ACTION_ID SKU
impact actions updates list
impact actions updates get UPDATE_ID
impact actions inquiries list
impact actions inquiries get INQUIRY_ID
impact actions inquiries create --json-file inquiry.json
```

### catalogs

```bash
impact catalogs list
impact catalogs get CATALOG_ID
impact catalogs items CATALOG_ID
impact catalogs item CATALOG_ID ITEM_ID
impact catalogs search --filter Query:eq:camera
impact catalogs stores list
impact catalogs stores get STORE_ID
impact catalogs stores items STORE_ID GROUP_ID
impact catalogs exception-lists show EXCEPTION_LIST_ID
impact catalogs exception-lists items EXCEPTION_LIST_ID
impact catalogs promo-code-exception-lists show EXCEPTION_LIST_ID
impact catalogs promo-code-exception-lists items EXCEPTION_LIST_ID
```

### reports

```bash
impact reports list
impact reports get REPORT_ID
impact reports metadata REPORT_ID
impact reports run REPORT_ID --limit 10
impact reports export REPORT_ID --json-file report-export-params.json
```

### clicks

```bash
impact clicks retrieve CLICK_ID
impact clicks export --json-file click-export-params.json
```

### jobs

```bash
impact jobs history --limit 10
impact jobs status JOB_ID
impact jobs download JOB_ID
impact jobs replay JOB_ID --force
```

### websites

```bash
impact websites list
impact websites get WEBSITE_ID
impact websites create --json-file website.json
impact websites update WEBSITE_ID --json-file website.json
impact websites delete WEBSITE_ID --force
```

### marketplace

Impact's Publisher API has **no marketplace/discovery endpoint** — every documented `/Mediapartners/{AccountSID}/...` resource is post-approval/operational. The `marketplace` command group therefore returns **structured browser-automation instructions** that another agent (using the `playwright-cli` skill) can follow to drive the partner-portal UI.

```bash
impact marketplace search
impact marketplace search --keyword fitness
impact marketplace search --category Health --keyword nutrition
impact marketplace search --text                # human-readable rendering
impact marketplace apply PROGRAM_ID
impact marketplace apply PROGRAM_ID --text
impact marketplace list-categories
impact marketplace list-categories --text
```

Default output is machine-parseable JSON with these top-level fields: `type` (`browser_navigation_instruction`), `schema_version`, `tool`, `command`, `action_id`, `objective`, `disclaimer`, `target_url`, `auth_note`, `structured_context`, `steps`, `extraction_target`, `allowed_tools`, `constraints`, `success_criteria`, `next_actions`.

`auth_note` directs the consumer to use the `lastpass` CLI for `app.impact.com` credentials before driving the browser. The instruction never embeds credentials.

### cache

```bash
impact cache status
impact cache clear
```

## JSON Bodies

Mutating commands read request bodies from `--json-file`. When `--json-file` is omitted, they read a JSON object from stdin.

```bash
printf '{"Name":"Example"}' | impact websites create
```

Destructive commands require `--force/-F`.

## Output

JSON is the default output format and preserves every field returned by the API. Table output selects compact fields for scanning.

```bash
impact campaigns list --limit 5 --table
impact ads list --limit 5 --properties id,name
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted |
