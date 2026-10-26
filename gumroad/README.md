# Gumroad CLI

## DESCRIPTION

Use this CLI to build PDF and EPUB books from current Notion chapter Drafts, inspect Gumroad products, and deploy reviewed book releases through Gumroad's API. This is a standalone local conversion of the BookWriter Gumroad Worker. All 14 capabilities retain their source/readiness/hash/approval checks.

## Installation

The Python CLI uses the cli-tools installer. Node.js 22+ and npm are required for the bundled local renderer and API engine. After installing the Python CLI, run:

```bash
gumroad engine install
gumroad --help
```

The engine installs its committed npm lockfile, then compiles TypeScript locally. No remote Worker or general LLM is invoked. `engine install` is explicit and never runs during a product write. To validate the source: `npm run check` and `npm test` from `gumroad_cli/engine`; `uv run --with pytest python -m pytest tests` from this tool directory.

## Authentication

Run `gumroad auth login` for an own-account Gumroad access token with `edit_products`, generated at https://gumroad.com/settings/advanced. The shared auth flow stores reusable secrets in the CLI-tools secret manager and only a `secret://` reference in the auth profile. Never paste credentials into a command, JSON input or `.env`. `gumroad auth login --force` revalidates the profile; `gumroad auth status` reports live Gumroad authentication. Select another saved Gumroad profile with the operation's `--profile` option.

Book operations separately reuse the existing CLI-tools secret `notion-api-token`, owned by the Notion CLI. That connection must have read access to the book root and chapters and insert access for builds/receipts. Product inspection needs only Gumroad; book inspection/builds need only Notion; release operations need both. No hosted Worker secrets are read.

## Output contract

stdout is one JSON document by default, or a table with `--table/-t`. Progress/errors go to stderr. Product output intentionally follows the Worker safe metadata contract: no signed/canonical paid-file URLs or buyer data. Product lists return id/name/published/price/currency records. Product get returns safe product/attachment metadata and productHash. Build results return native artifact/manifest block IDs, exact bytes/hashes, source digest, counts and warnings. Release results retain the original operation, delivery verification, no-op and receipt fields. `gumroad schema get CAPABILITY` prints every exact JSON input field and its type; no authentication is required.

Every list supports `--filter/-f`, `--limit/-l`, `--properties/-p` and `--table/-t`. Filtering is client-side and precedes the limit; the API is fully paginated (bounded to 100 pages by the original engine). Shared filters support `field:op:value` syntax.

## Commands

```bash
gumroad products list --filter 'published:eq:true' --limit 20 --table
gumroad products get 'PRODUCT_ID'
gumroad books inspect 'NOTION_BOOK_URL' --mode publication
gumroad books build-pdf 'NOTION_BOOK_URL' --mode proof --image-mode native --author 'Known Author'
gumroad books build-epub 'NOTION_BOOK_URL' --mode publication --image-mode native
gumroad schema list --table
gumroad schema get updateGumroadFormats
gumroad engine install
```

For the complex release/upload operations, `--input-file` is a strict JSON object matching the printed schema. Every field is required, including explicit nulls. Unknown fields/types/enums fail before network calls. Hashes and approval flags must reflect actual review; they are never generated as a substitute for review. Example read-only release plan input:

```json
{
  "bookPageUrl": "NOTION_BOOK_URL",
  "pdfFileBlockId": "EXACT_FRESH_PUBLICATION_PDF_BLOCK_ID",
  "productId": "PRODUCT_ID",
  "replaceFileId": "CURRENT_PDF_FILE_ID",
  "name": null,
  "priceCents": null,
  "currency": null,
  "descriptionHtml": null
}
```

Save that as `release-plan.json`, then run `gumroad releases plan --input-file release-plan.json`. For a new draft, productId/replaceFileId are null and name/priceCents/currency are explicit operator choices. A publication build requires all chapters Final and no DETAIL markers. Proof mode must be explicit and cannot pass normal deployment/publication. Author omission is null, never an invented author. Use ebook200 only with approval for that book.

### Complete Worker capability coverage

| Worker capability | CLI command example |
| --- | --- |
| `listGumroadProducts` | `gumroad products list --limit 20` |
| `inspectGumroadProduct` | `gumroad products get PRODUCT_ID` |
| `inspectGumroadBuild` | `gumroad books inspect NOTION_BOOK_URL --mode publication` |
| `buildGumroadBook` | `gumroad books build-pdf NOTION_BOOK_URL --mode publication --image-mode native` |
| `buildGumroadEpub` | `gumroad books build-epub NOTION_BOOK_URL --mode publication --image-mode native` |
| `smokeTestGumroadUpload` | `gumroad uploads smoke-test --input-file smokeTestGumroadUpload.json` |
| `createGumroadSmokeDraft` | `gumroad smoke-drafts create --input-file createGumroadSmokeDraft.json` |
| `updateGumroadSmokeDraft` | `gumroad smoke-drafts update --input-file updateGumroadSmokeDraft.json` |
| `planGumroadRelease` | `gumroad releases plan --input-file planGumroadRelease.json` |
| `createGumroadDraft` | `gumroad releases create-draft --input-file createGumroadDraft.json` |
| `updateGumroadBook` | `gumroad releases update --input-file updateGumroadBook.json` |
| `publishGumroadBook` | `gumroad releases publish --input-file publishGumroadBook.json` |
| `planGumroadFormats` | `gumroad formats plan --input-file planGumroadFormats.json` |
| `updateGumroadFormats` | `gumroad formats update --input-file updateGumroadFormats.json` |

Every complex operation's JSON schema is available as `gumroad schema get CAPABILITY`; its matching example above is the complete invocation. This includes uploads smoke-test, smoke-drafts create/update, releases plan/create-draft/update/publish and formats plan/update. Their input JSON uses the same field names as the Worker. Boolean approvals remain mandatory and false is never treated as approval.

### Shared commands

```bash
gumroad auth login
gumroad auth login --force
gumroad auth status --table
gumroad auth test
gumroad auth logout
gumroad auth profiles create alternate
gumroad auth profiles get alternate
gumroad auth profiles list --table
gumroad auth profiles rename alternate renamed
gumroad auth profiles select renamed
gumroad auth profiles delete renamed
gumroad auth profiles remove retired
gumroad cache clear
```

Use `gumroad auth --help`, `gumroad auth profiles --help` and `gumroad cache --help` for the installed shared infrastructure's full options. No API response cache is used for source/target freshness or approval checks.

## Release safety and recovery

Build PDF and EPUB serially from the same stable current Notion source. Builds attach derived artifacts/manifests; they never edit prose or chapter statuses. Review exact artifacts and current plan hashes before writing. New products are always unpublished. Publishing is separate and requires the exact product confirmation. A published-product update changes buyer downloads immediately and requires confirmLiveUpdate. The multi-format path preserves unchanged formats with ID-only entries and verifies delivered bytes and retained IDs; changed formats may receive new IDs. Unknown uploaded attachments, unsafe links, variants/bundles/subscriptions and stale plans fail closed. Single-PDF tools refuse an extra uploaded EPUB; use formats plan/update for later dual-format releases.

No audience email command exists. No automatic write retry exists. The Notion SDK retry mechanism is explicitly disabled. An ambiguous upload/attachment/product/publication result must be inspected before another attempt; a receipt failure after verified delivery is not permission to repeat the write. Serialise operations per book/product and avoid source edits during a release. Cross-provider snapshots are not atomic and the APIs offer no transactional rollback.

EPUB contains embedded PDF page images with extracted-text alternatives, not reconstructed reflowable guide pages. Run EPUBCheck and inspect the exact output before approving delivery. The original media/output budgets and renderer remain unchanged. The inherited renderer npm dependencies retain known high advisories; conversion does not claim a clean security audit.

## Provenance

Source: [Gumroad Builds and Deployments](https://app.notion.com/p/966cfdfb17f84c1b91e3370e915c0146), Worker bookwriter-gumroad v1.4.2, ID 01a17003-3747-77bb-9c36-373ec3fa4088. Portable archive SHA-256: `25990e2657957395f2150a18b57c4996555303641542a802eefd13e5f313964f`. `gumroad_cli/engine/SOURCE.json` records adaptations. Bundled third-party notices, fonts/license, renderer origin and original synthetic tests are preserved. Standalone PDF/Leanpub Workers are untouched. Current API implementation: https://github.com/antiwork/gumroad/blob/main/app/controllers/api/v2/links_controller.rb and https://github.com/antiwork/gumroad/blob/main/spec/requests/api/v2/product_files_params_spec.rb.
