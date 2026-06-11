# Google Lighthouse CLI

## DESCRIPTION

The `google-lighthouse` CLI wraps lighthouse with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Prerequisites

The wrapper launches Google's official npm Lighthouse package through `npx` by default:

```bash
npx --yes --package lighthouse@13.2.0 lighthouse --version
```

## Installation

```bash
cd <cli-tools-root>/google-lighthouse
uv tool install -e . --force --refresh
```

## Quick Start

```bash
google-lighthouse audits run https://example.com/
google-lighthouse audits list --table
google-lighthouse audits get 20260507T190000Z-example-com
```

## Commands

### `audits run URL`

Run a Lighthouse audit for a public URL. The command saves the raw JSON report, HTML report, and normalized `summary.json`.

```bash
google-lighthouse audits run https://example.com/
google-lighthouse audits run https://example.com/ --form-factor mobile
google-lighthouse audits run https://example.com/ --chrome-flags "--headless=new"
google-lighthouse audits run https://example.com/ --timeout 240
google-lighthouse audits run https://example.com/ --properties id,scores.performance,artifacts.html
google-lighthouse audits run https://example.com/ --table
```

### `audits list`

List saved audit summaries.

```bash
google-lighthouse audits list
google-lighthouse audits list --table
google-lighthouse audits list --limit 10
google-lighthouse audits list --filter "url:eq:https://example.com/"
google-lighthouse audits list --properties id,url,scores.performance
```

### `audits get AUDIT_ID`

Get one saved audit summary by ID.

```bash
google-lighthouse audits get 20260507T190000Z-example-com
google-lighthouse audits get 20260507T190000Z-example-com --table
google-lighthouse audits get 20260507T190000Z-example-com --properties id,metrics.largest_contentful_paint_ms
```

## Output

JSON is the default output format. Use `--table` or `-t` for human-readable table output.

`list` supports:

- `--limit` / `-l`
- `--filter` / `-f`
- `--properties` / `-p`
- `--table` / `-t`

`run` and `get` support:

- `--properties` / `-p`
- `--table` / `-t`

## Configuration

Configuration lives in `.env`.

```bash
CLI_COMMAND=npx
LIGHTHOUSE_NPM_PACKAGE=lighthouse@13.2.0
# CLI_PATH=
# GOOGLE_LIGHTHOUSE_DATA_DIR=~/Library/Application Support/cli-tools/google-lighthouse/audits
```

Default audit storage:

```text
~/Library/Application Support/cli-tools/google-lighthouse/audits/
```

Each audit is stored under:

```text
<audit-id>/
├── <audit-id>.report.json
├── <audit-id>.report.html
└── summary.json
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication or CLI availability error |
| 130 | User interrupted |
