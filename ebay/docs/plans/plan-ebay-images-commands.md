# Implementation Plan: eBay Image Upload Commands

## One-line Summary
Add `ebay images upload/list/get` commands for uploading images to eBay Picture Services via the Media API.

## Why This Approach
This is the simplest approach because:
- Uses existing CLI patterns (Typer commands, client methods, output helpers)
- No new dependencies required
- Local JSON storage for image tracking is minimal and sufficient (eBay has no "list images" API)
- Leverages eBay's server-side validation instead of adding local image validation complexity

## Discovery Summary

### Files Read
- `<cli-tools-root>/ebay/ebay_cli/client.py` - API client with `_make_request()` pattern
- `<cli-tools-root>/ebay/ebay_cli/commands/inventory.py` - Command structure pattern
- `<cli-tools-root>/ebay/ebay_cli/output.py` - Output helpers
- `<cli-tools-root>/ebay/ebay_cli/main.py` - App registration pattern
- `<cli-tools-root>/ebay/README.md` - Documentation format

### APIs Verified
- **eBay Media API** at `https://apim.ebay.com/commerce/media/v1_beta`:
  - `POST /image/create_image_from_file` - multipart/form-data upload
  - `POST /image/create_image_from_url` - JSON body with imageUrl
  - `GET /image/{image_id}` - get metadata
- OAuth scope `sell.inventory` already in client SCOPES
- Rate limit: 50 POST requests per 5 seconds
- Image ID returned in `Location` response header

### Key Patterns
- Commands use `app = typer.Typer()` with `@app.command()` decorators
- Client methods handle token refresh and error parsing
- Media API uses `apim.ebay.com` (different from `api.ebay.com` or `apiz.ebay.com`)
- Output: `print_json()` to stdout, `print_error/warning/success/info()` to stderr

---

## The Plan

### Step 1: Create storage module for local image tracking

**File:** `<cli-tools-root>/ebay/ebay_cli/storage.py` (CREATE)

Create new module with `ImageStorage` class:
- Storage location: `~/.ebay/images.json`
- Methods: `add_image()`, `get_all_images()`, `get_image()`, `update_image()`
- Auto-create `~/.ebay/` directory if missing
- Store: image_id, imageUrl, expirationDate, source (file/url), original path/url, uploaded_at

### Step 2: Add Media API methods to client

**File:** `<cli-tools-root>/ebay/ebay_cli/client.py` (MODIFY)

Add three methods to `EbayClient` class (insert after line ~700, before Policy methods):

1. `upload_image_from_file(file_path: str) -> Dict`
   - Direct `requests.post()` with multipart/form-data (cannot use `_make_request()`)
   - Base URL: `apim.ebay.com`
   - Endpoint: `/commerce/media/v1_beta/image/create_image_from_file`
   - Extract image_id from Location header
   - Handle token refresh on 401

2. `upload_image_from_url(image_url: str) -> Dict`
   - Direct `requests.post()` with JSON body
   - Base URL: `apim.ebay.com`
   - Endpoint: `/commerce/media/v1_beta/image/create_image_from_url`
   - Body: `{"imageUrl": "https://..."}`
   - Extract image_id from Location header

3. `get_image(image_id: str) -> Dict`
   - Direct `requests.get()`
   - Base URL: `apim.ebay.com`
   - Endpoint: `/commerce/media/v1_beta/image/{image_id}`
   - Returns: `{imageUrl, expirationDate}`

### Step 3: Create images command module

**File:** `<cli-tools-root>/ebay/ebay_cli/commands/images.py` (CREATE)

Create new command module with three commands:

**3.1 `upload` command:**
- Validation: exactly one of --file or --url required
- Process each image, continue on failures, collect results
- Store successful uploads to local storage
- Display warning about 30-day expiration
- Output: JSON with uploaded/errors arrays, or table format

**3.2 `list` command:**
- Read from local storage (`~/.ebay/images.json`)
- Show: image_id, imageUrl, expirationDate, source, original, uploaded_at
- Apply properties filter if specified

**3.3 `get` command:**
- Argument: image_id (required)
- Fetch fresh metadata from eBay API
- Update local storage if image exists there
- Output: image_id, imageUrl, expirationDate

──────────────────────────
🧪 CHECKPOINT: Verify steps 1-3
- Run: `ebay images --help` (should show subcommands)
- Run: `ebay images upload --help` (should show options)
- Run: `ebay images list` (should show empty storage message)
──────────────────────────

### Step 4: Register images app in main.py

**File:** `<cli-tools-root>/ebay/ebay_cli/main.py` (MODIFY)

1. Add import: `from .commands import images`
2. Add registration: `app.add_typer(images.app, name="images", help="Manage eBay images")`

### Step 5: Update README.md with images documentation

**File:** `<cli-tools-root>/ebay/README.md` (MODIFY)

Add new section after "Listings" section:

```markdown
### Images

Upload and manage images for eBay listings using the Media API.
Uploaded images expire after 30 days if not used in a listing.

```bash
# Upload from local file
ebay images upload --file /path/to/image.jpg
ebay images upload --file "/path/one.jpg,/path/two.jpg"

# Upload from URL
ebay images upload --url "https://example.com/image.jpg"
ebay images upload --url "https://a.com/1.jpg,https://b.com/2.jpg"

# List locally-stored uploaded images
ebay images list
ebay images list
ebay images list --properties "image_id,imageUrl,expirationDate"

# Get fresh metadata from eBay API
ebay images get IMAGE_ID
ebay images get IMAGE_ID
```

**Available fields:** image_id, imageUrl, expirationDate, source, original, uploaded_at

**Note:** Uploaded image metadata is stored locally in `~/.ebay/images.json`.
```

──────────────────────────
🧪 FINAL CHECKPOINT: Integration test
- Run: `ebay images upload --file /path/to/test-image.jpg` (with real image)
- Run: `ebay images get <image_id>` (should fetch fresh metadata)
──────────────────────────

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `ebay_cli/storage.py` | CREATE | Local JSON storage for image metadata |
| `ebay_cli/client.py` | MODIFY | Add 3 Media API methods |
| `ebay_cli/commands/images.py` | CREATE | New command module with upload/list/get |
| `ebay_cli/main.py` | MODIFY | Register images app |
| `README.md` | MODIFY | Add images command documentation |

---

## What's NOT Included
- Local image validation (dimensions, file size, format) - relying on eBay API errors
- Image deletion from local storage (can be added later if needed)
- Batch upload from directory (can use shell: `ebay images upload --file "$(ls *.jpg | tr '\n' ',')"`)
- Automatic retry on rate limit (existing client retry handles this for 429)

---

## Technical Details

### Media API Base URL
The Media API uses `apim.ebay.com` instead of the standard `api.ebay.com`. This requires direct `requests` calls rather than using `_make_request()`.

### Image ID Extraction
The API returns the image ID in the `Location` response header:
```
Location: https://apim.ebay.com/commerce/media/v1_beta/image/{image_id}
```
Extract by splitting on `/` and taking the last segment.

### Local Storage Format
`~/.ebay/images.json`:
```json
{
  "images": [
    {
      "image_id": "abc123",
      "imageUrl": "https://i.ebayimg.com/images/g/.../s.jpg",
      "expirationDate": "2025-02-02T10:00:00Z",
      "source": "file",
      "original": "/path/to/image.jpg",
      "uploaded_at": "2025-01-03T10:00:00Z"
    }
  ]
}
```

### Error Codes from eBay
- 190201: File size too large (max 12MB)
- 190202: Dimensions exceed limit (height + width > 15,000px)
- 190203: Unsupported format
- 190204: Cannot download from URL (for URL uploads)
- 190200: Image not found (for get)
