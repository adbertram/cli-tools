# Gumroad CLI

## DESCRIPTION

The `gumroad` CLI manages Gumroad products and uploads existing local files through the Gumroad API. Use it to inspect products, stage files, create unpublished digital products, update selected metadata or attachments, and publish an explicitly selected product.

## Installation and authentication

Install with the cli-tools installer. This is a Python CLI with no Node.js, renderer, manuscript system, or external workspace dependency.

```bash
gumroad auth login
gumroad auth status
```

Generate an own-account access token with `edit_products` at https://gumroad.com/settings/advanced. Enter the access token, not an application secret. The shared auth flow stores reusable credentials in the CLI-tools secret manager and saves only a reference in the auth profile; never put credentials in command arguments, source files or `.env`. Service commands accept `--profile` for another saved account/profile.

## Product inspection

```bash
gumroad products list --table
gumroad products list --filter 'published:eq:true' --limit 20 --properties 'id,name,price,currency'
gumroad products get 'PRODUCT_ID'
```

Lists return complete product records. `--filter/-f`, `--limit/-l`, `--properties/-p` and `--table/-t` are supported. Filtering and limiting are client-side: the API product catalog is paginated first, with a 100-page safety bound, then filters and the matching-result limit are applied. Get returns the complete API response plus `state_hash`, a stable hash of editable product metadata and attachment identities that excludes expiring download URLs and sales counters. Supply it as `--expected-state` when an update or publication must match a prior inspection.

JSON is the default stdout format. Progress and errors go to stderr. Full product responses can contain private signed attachment URLs; handle the output as private account data.

## Upload an existing file

```bash
gumroad files upload ./existing-file.zip --dry-run
umask 077
gumroad files upload ./existing-file.zip --yes > upload.json
```

Upload accepts any existing nonempty file up to the Gumroad API's 20 GiB limit. It sends 100 MiB parts through presign → signed S3 PUTs with ETags → complete. Memory is bounded to one part. A dry run computes the local file's size and SHA-256 without API calls. A successful real upload returns this JSON receipt shape:

```json
{
  "kind": "gumroad-upload",
  "version": 1,
  "filename": "existing-file.zip",
  "size": 1234,
  "sha256": "EXACT_64_CHARACTER_LOWERCASE_SHA256",
  "upload": {"success": true, "file_url": "EXACT_CANONICAL_URL_FROM_GUMROAD_FILES_COMPLETE"}
}
```

The actual receipt contains the complete upload-completion response. Its canonical `file_url` is a private attachment input, not a customer download URL or an authentication token. Preserve it exactly; don't construct it from signed download URLs or share it publicly. Passing a receipt stages/attaches those exact bytes; the upload alone neither creates nor changes a product. Malformed receipts fail before product API mutations.

## Create an unpublished product

```bash
gumroad products create-draft --name 'My Product' --price-cents 1500 --currency usd --upload-receipt upload.json --dry-run
gumroad products create-draft --name 'My Product' --price-cents 1500 --currency usd --description-file description.html --upload-receipt upload.json --yes
```

Name, integer price in smallest currency units, and lowercase currency are explicit. `--description-file` reads UTF-8 HTML; omitting it leaves description creation to Gumroad. `--upload-receipt` is optional. Creation explicitly sends `native_type:digital`, `draft:true` and `published:false`, then verifies the product remains unpublished. It never guesses a price or publishes automatically. A repeated creation is a new-product request; inspect after an ambiguous result rather than rerunning it.

## Update metadata or a selected attachment

```bash
gumroad products update 'PRODUCT_ID' --name 'Updated Name' --price-cents 1800 --dry-run
gumroad products update 'PRODUCT_ID' --description-file revised.html --yes
gumroad products update 'PRODUCT_ID' --upload-receipt upload.json --replace-file-id 'EXACT_CURRENT_FILE_ID' --expected-state 'STATE_HASH' --dry-run
gumroad products update 'PRODUCT_ID' --upload-receipt upload.json --replace-file-id 'EXACT_CURRENT_FILE_ID' --confirm-live-update --yes
gumroad products update 'PRODUCT_ID' --upload-receipt upload.json --append-file --yes
```

Only supplied metadata fields are sent: `--name`, `--price-cents`, `--currency` and `--description-file`. Omitted fields retain their current values; an empty description file explicitly clears the description. Gumroad may sanitize supplied HTML; read the returned product to review its canonical description.

A file update requires either an exact attached `--replace-file-id` or explicit `--append-file`. Every other current attachment is retained using an ID-only entry, including existing uploaded files. The CLI never resubmits signed download URLs as canonical upload URLs. Gumroad's files array replaces the complete attachment set, so the CLI builds it from the current product and rechecks state immediately before writing. A selected file with identical delivered bytes is retained as a verified no-op (or only requested metadata is changed). Explicit append adds another attachment and may duplicate content if deliberately repeated; it is never automatically retried.

Published-product updates require `--confirm-live-update` because metadata/download changes affect buyers immediately. Metadata-only updates omit the files array. Post-write reads verify publication state, requested name/price/currency, preserved description when omitted, retained attachment IDs and the delivered new file's size/SHA-256. No file format or manuscript status is imposed. Provider restrictions such as files still referenced by rich content are returned as failures; the CLI does not rewrite buyer content to bypass them.

## Publish separately

```bash
gumroad products publish 'PRODUCT_ID' --dry-run
gumroad products publish 'PRODUCT_ID' --confirm-product-id 'PRODUCT_ID' --expected-state 'STATE_HASH' --yes
```

Publication requires exact product-ID confirmation and a separate write authorization. It publishes the existing product without uploading/replacing files, and verifies the resulting publication state and unchanged metadata/file identities. An already-published product is a verified no-op.

## Write confirmation and recovery

Every mutating command requires `--yes` or `--dry-run`. File upload and draft-creation previews are offline; update/publication previews read current product state but perform no writes. Dry-run requests and real requests share the same payload construction.

No API/product/upload-completion write is retried automatically. Failed parts receive one abort attempt; accepted abort means cleanup is not yet confirmed. An ambiguous completion is never followed by abort or repeated completion. Upload errors identify the non-secret `upload_id` for investigation. Product/write/readback failures must be investigated through `products get` before another attempt. A verified API write followed by a delivery-check failure does not mean the write failed. Operations are not transactional across service calls; avoid concurrent edits to the same product.

## Shared commands

```bash
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

No response caching is used for mutation freshness checks. The CLI exposes only `products`, `files`, `auth` and `cache`; no sales, audience email or other unrelated operations are added.

## API contract and provenance

The Gumroad API interactions were translated from the Gumroad-specific portions of `bookwriter-gumroad` v1.4.2, portable archive SHA-256 `25990e2657957395f2150a18b57c4996555303641542a802eefd13e5f313964f`. Current provider source was checked against [product create/update/enable](https://github.com/antiwork/gumroad/blob/main/app/controllers/api/v2/links_controller.rb), [multipart file endpoints](https://github.com/antiwork/gumroad/blob/main/app/controllers/api/v2/files_controller.rb), [ID-only retention tests](https://github.com/antiwork/gumroad/blob/main/spec/requests/api/v2/product_files_params_spec.rb) and [digital type definitions](https://github.com/antiwork/gumroad/blob/main/app/models/link.rb). Generic book building and publishing orchestration are outside this service CLI.

Run focused synthetic tests with `uv run --with pytest python -m pytest tests` from this tool directory. Live validation uses authenticated product reads only; synthetic fixtures cover mutation bodies, confirmation refusal, private upload receipts, attachment retention, delivery hashes and ambiguous failures without changing real products.
