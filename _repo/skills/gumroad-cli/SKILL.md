---
name: gumroad-cli
description: >-
  Use for Gumroad service operations through the gumroad CLI: inspect products, upload existing local files, create unpublished digital products, update selected metadata/files, and publish an exact existing product. For CLI lifecycle work, route through cli-tool instead.
---

<objective>
Use the Gumroad-only Python API CLI. Product/file operations do not build documents or depend on any manuscript/workspace system.
</objective>

<project_overrides>
Before acting, run `~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh gumroad-cli`. Apply printed instructions; stop on nonzero exit.
</project_overrides>

<quick_start>
Read adjacent `usage.json` before running commands. Examples:

```bash
gumroad products list --table
gumroad products get PRODUCT_ID
gumroad files upload ./existing.zip --dry-run
gumroad files upload ./existing.zip --yes > upload.json
gumroad products create-draft --name "Product" --price-cents 1500 --currency usd --upload-receipt upload.json --dry-run
gumroad products update PRODUCT_ID --upload-receipt upload.json --replace-file-id CURRENT_FILE_ID --dry-run
gumroad products publish PRODUCT_ID --dry-run
```
</quick_start>

<essential_principles>
- Authenticate through `gumroad auth login`; own-account edit_products token belongs in the CLI-tools secret manager. Never pull hosted Worker secrets.
- Every write requires --yes or --dry-run. A dry run is not authorization to later execute. Real product writes require the user's authorized intent.
- Upload an existing local file only. The multipart receipt is private: preserve its exact canonical file_url from files/complete; never derive it from signed customer-download URLs. Use private local file permissions when saving receipts.
- Draft creation requires explicit name/price/currency and always remains unpublished. Publication is separate and requires exact --confirm-product-id plus --yes.
- Update only requested metadata. Replacing a file needs its exact current file ID; appending needs --append-file. Other attachments are retained by ID only. Published-product changes need --confirm-live-update. Use --expected-state when approval depends on prior inspection.
- No write retries. Inspect exact product/upload state after ambiguous results. Failed delivery verification after a successful product write is not permission to repeat the write. Explicit append may create duplicate attachments if deliberately repeated.
- JSON includes full API records, potentially private signed attachment URLs. Never expose these or canonical upload receipt URLs in public messages.
- Do not change real products merely to test setup. Use read-only products list/get and synthetic mutation tests.
</essential_principles>

<reference_index>
- `usage.json`: exact installed command/options contract.
- `/Users/adam/Dropbox/GitRepos/cli-tools/gumroad/README.md`: examples, private receipt format, API provenance and recovery behavior.
</reference_index>

<success_criteria>
Exact requested Gumroad operation succeeds, output is verified, private credentials/file URLs remain protected, and no unrelated service mutation occurs.
</success_criteria>
