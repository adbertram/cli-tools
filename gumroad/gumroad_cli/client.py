"""Gumroad API operations. Writes are single-attempt and files retain explicit IDs."""
import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import quote, urlsplit, parse_qsl, urlencode

import requests
from cli_tools_shared.exceptions import ClientError
from .config import API_URL, get_config
PART_SIZE = 100 * 1024 * 1024
MAX_FILE_SIZE = 20 * 1024 * 1024 * 1024


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_+=-]{1,150}", value):
        raise ClientError("Expected an exact Gumroad product/file ID, not a URL.")
    return quote(value, safe="")


def upload_url(value, *, signed=False):
    if not isinstance(value, str):
        raise ClientError("Invalid Gumroad upload URL.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ClientError("Invalid Gumroad upload URL.") from exc
    if (any(ord(c) < 33 for c in value) or parsed.scheme != "https" or not parsed.hostname or
            not parsed.hostname.endswith(".amazonaws.com") or parsed.username or
            parsed.password or port not in (None, 443) or parsed.fragment or
            (not signed and (parsed.query or "/attachments/" not in parsed.path))):
        raise ClientError("Invalid Gumroad upload URL; use the exact files/complete result.")
    return value


def read_receipt(path):
    try:
        receipt = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise ClientError("Upload receipt must be a readable JSON file.") from exc
    fields = {"kind", "version", "filename", "size", "sha256", "upload"}
    if not isinstance(receipt, dict) or set(receipt) != fields:
        raise ClientError("Invalid Gumroad upload receipt fields.")
    if (receipt["kind"] != "gumroad-upload" or type(receipt["version"]) is not int or receipt["version"] != 1 or
            not isinstance(receipt["filename"], str) or not receipt["filename"].strip() or
            type(receipt["size"]) is not int or not 0 < receipt["size"] <= MAX_FILE_SIZE or
            not isinstance(receipt["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", receipt["sha256"]) or
            not isinstance(receipt["upload"], dict) or receipt["upload"].get("success") is not True):
        raise ClientError("Invalid Gumroad upload receipt values.")
    upload_url(receipt["upload"].get("file_url"))
    return receipt


def file_info(path):
    path = Path(path)
    if not path.is_file():
        raise ClientError("Upload source must be an existing regular file.")
    size = path.stat().st_size
    if not 0 < size <= MAX_FILE_SIZE:
        raise ClientError("Gumroad uploads must be nonempty and no larger than 20 GiB.")
    return path, size


def metadata(name=None, price=None, currency=None, description=None):
    body = {}
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            raise ClientError("Product name cannot be blank.")
        body["name"] = name
    if price is not None:
        if type(price) is not int or price < 0:
            raise ClientError("Price must be a nonnegative integer in smallest currency units.")
        body["price"] = price
    if currency is not None:
        if not isinstance(currency, str) or not re.fullmatch(r"[a-z]{3}", currency):
            raise ClientError("Currency must be an explicit lowercase three-letter code.")
        body["price_currency_type"] = currency
    if description is not None:
        if not isinstance(description, str):
            raise ClientError("Description must be HTML text.")
        body["description"] = description
    return body


def draft_body(fields, receipt=None):
    body = {**fields, "native_type": "digital", "draft": True, "published": False}
    if receipt:
        body["files"] = [{"url": receipt["upload"]["file_url"]}]
    return body


def draft_preview(fields, receipt=None):
    return {"dry_run": True, "method": "POST", "path": "/products", "body": draft_body(fields, receipt)}


def validate_update(fields, receipt, replace_file_id, append_file):
    if not fields and not receipt:
        raise ClientError("Select at least one metadata field or upload receipt to update.")
    if receipt and bool(replace_file_id) == bool(append_file):
        raise ClientError("Choose exactly one: --replace-file-id or --append-file.")
    if not receipt and (replace_file_id or append_file):
        raise ClientError("File targeting options require --upload-receipt.")


def state_hash(product):
    """Exclude expiring download URLs and sales counters from the editable-state hash."""
    files = product_files(product)
    state = {key: product.get(key) for key in ("id", "name", "published", "price", "currency", "description", "variants", "bundle_products", "subscription_duration")}
    state["files"] = [{**{key: item.get(key) for key in ("id", "name", "size", "filetype")},
        **({"url": item.get("url")} if item.get("filetype") == "link" else {})} for item in files]
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def product_files(product):
    files = product.get("files")
    if (not isinstance(files, list) or any(not isinstance(f, dict) or not isinstance(f.get("id"), str) for f in files)
            or len({f["id"] for f in files}) != len(files)):
        raise ClientError("Product response lacks a complete, unique attachment ID list.")
    return files


class GumroadClient:
    def __init__(self, config=None, *, session=None, transfer=None):
        self.config = config or get_config()
        self.session = session or requests.Session()
        self.transfer = transfer or requests.Session()
        # Bearer credentials are per API request, never on the transfer session.
        self.last_request = 0.0

    def call(self, method, path, body=None):
        parsed = urlsplit(API_URL + path)
        if (not path.startswith("/") or parsed.scheme != "https" or parsed.netloc != "api.gumroad.com" or
                not re.fullmatch(r"/v2/(products(?:/[A-Za-z0-9_%=+.-]+(?:/enable)?)?|files/(presign|complete|abort))", parsed.path)):
            raise ClientError("Unsupported Gumroad API path.")
        token = self.config.personal_access_token
        if not token:
            raise ClientError("Missing Gumroad token. Run gumroad auth login.")
        time.sleep(max(0, 1.1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        try:
            response = self.session.request(method, API_URL + path, json=body,
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                timeout=45, allow_redirects=False)
        except requests.RequestException as exc:
            raise ClientError("Gumroad request failed/timed out; completion unconfirmed. Inspect the product/upload before retrying.") from exc
        if not response.ok or 300 <= response.status_code < 400:
            raise ClientError(f"Gumroad HTTP {response.status_code}; no automatic retries.")
        try:
            data = response.json()
        except ValueError as exc:
            raise ClientError("Invalid Gumroad JSON; completion unconfirmed. Do not retry writes.") from exc
        if not isinstance(data, dict) or data.get("success") is not True:
            raise ClientError("Gumroad rejected the operation; inspect account diagnostics before retrying.")
        return data

    def list_products(self):
        rows, seen, path = [], set(), "/products"
        for _ in range(100):
            if path in seen:
                raise ClientError("Gumroad pagination loop.")
            seen.add(path)
            data = self.call("GET", path)
            if not isinstance(data.get("products"), list) or any(not isinstance(p, dict) for p in data["products"]):
                raise ClientError("Invalid Gumroad product list.")
            rows.extend(data["products"])
            if not data.get("next_page_url"):
                return rows
            url = urlsplit(data["next_page_url"])
            if url.scheme != "https" or url.netloc != "api.gumroad.com" or url.path != "/v2/products" or url.fragment:
                raise ClientError("Unsafe Gumroad pagination URL.")
            query = urlencode([(k, v) for k, v in parse_qsl(url.query) if k != "access_token"])
            path = "/products" + ("?" + query if query else "")
        raise ClientError("Product list exceeds 100 pages.")

    def get_product(self, product_id):
        data = self.call("GET", "/products/" + identifier(product_id))
        if not isinstance(data.get("product"), dict) or data["product"].get("id") != product_id:
            raise ClientError("Product identity mismatch.")
        return data

    def upload_file(self, path):
        path, size = file_info(path)
        with path.open("rb") as source:
            initial = path.stat()
            reservation = self.call("POST", "/files/presign", {"filename": path.name, "file_size": size})
            upload_id, key, parts = reservation.get("upload_id"), reservation.get("key"), reservation.get("parts")
            if not isinstance(upload_id, str) or not upload_id or not isinstance(key, str) or not key or not isinstance(parts, list):
                raise ClientError("Malformed upload reservation; no product changed. Inspect the upload before retrying.")
            completing = False
            try:
                if len(parts) != math.ceil(size / PART_SIZE):
                    raise ClientError("Unexpected Gumroad multipart count.")
                completed, digest = [], hashlib.sha256()
                for index, part in enumerate(parts, 1):
                    if not isinstance(part, dict) or part.get("part_number") != index:
                        raise ClientError("Invalid Gumroad multipart order.")
                    url = upload_url(part.get("presigned_url"), signed=True)
                    chunk = source.read(min(PART_SIZE, size - (index - 1) * PART_SIZE))
                    if not chunk or len(chunk) != min(PART_SIZE, size - (index - 1) * PART_SIZE):
                        raise ClientError("Upload source changed size; completion not attempted.")
                    digest.update(chunk)
                    try:
                        response = self.transfer.put(url, data=chunk, timeout=90, allow_redirects=False)
                    except requests.RequestException as exc:
                        raise ClientError("Upload part failed; completion not attempted.") from exc
                    if not response.ok or 300 <= response.status_code < 400 or not response.headers.get("ETag"):
                        raise ClientError("Upload part failed or missing ETag.")
                    completed.append({"part_number": index, "etag": response.headers["ETag"]})
                current = path.stat()
                if source.read(1) or (initial.st_ino, initial.st_size, initial.st_mtime_ns) != (current.st_ino, current.st_size, current.st_mtime_ns):
                    raise ClientError("Upload source changed; completion not attempted.")
                completing = True
                result = self.call("POST", "/files/complete", {"upload_id": upload_id, "key": key, "parts": completed})
                upload_url(result.get("file_url"))
                return {"kind": "gumroad-upload", "version": 1, "filename": path.name, "size": size, "sha256": digest.hexdigest(), "upload": result}
            except (ClientError, OSError) as exc:
                if completing:
                    raise ClientError(f"Upload completion unconfirmed (upload_id={upload_id!r}); inspect this upload before retrying. Do not abort or repeat completion.") from exc
                try:
                    aborted = self.call("POST", "/files/abort", {"upload_id": upload_id, "key": key})
                    status = aborted.get("status")
                except ClientError:
                    status = None
                suffix = "abort accepted, cleanup not yet confirmed" if status == "accepted" else "abort confirmed" if status == "already_gone" else "abort unconfirmed"
                raise ClientError(f"Upload failed (upload_id={upload_id!r}); {suffix}. No product attachment attempted.") from exc

    def _check_state(self, product_id, expected):
        current = self.get_product(product_id)["product"]
        if state_hash(current) != expected:
            raise ClientError("Product changed; re-inspect before writing.")

    def _verify_metadata(self, product, fields, original=None):
        mapping = {"price_currency_type": "currency"}
        for key in ("name", "price", "price_currency_type"):
            target = mapping.get(key, key)
            expected = fields.get(key, original.get(target) if original else None)
            if expected is not None and product.get(target) != expected:
                raise ClientError(f"Product {target} verification failed after write. Inspect before retrying.")
        if original is not None and "description" not in fields and product.get("description") != original.get("description"):
            raise ClientError("Unmodified description changed after write. Inspect before retrying.")
        if original is not None and product.get("published") != original.get("published"):
            raise ClientError("Product publication state changed unexpectedly. Inspect before retrying.")

    def _verify_upload(self, product, receipt, retained):
        files = product_files(product)
        actual_ids = {f["id"] for f in files}
        if not set(retained).issubset(actual_ids):
            raise ClientError("Existing attachment retention failed after write. Inspect before retrying.")
        added = [f for f in files if f["id"] not in retained]
        if len(added) != 1 or len(files) != len(retained) + 1:
            raise ClientError("New attachment could not be uniquely verified. Inspect before retrying.")
        url = added[0].get("url")
        if not isinstance(url, str):
            raise ClientError("Delivered attachment URL missing; product write succeeded but delivery unconfirmed.")
        verified = self._download_digest(url, receipt["size"])
        if verified != {"size": receipt["size"], "sha256": receipt["sha256"]}:
            raise ClientError("Delivered file hash differs after write. Inspect before retrying.")
        return {"file_id": added[0]["id"], **verified}

    def _download_digest(self, url, maximum):
        digest, size, visited = hashlib.sha256(), 0, set()
        for _ in range(6):
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443) or
                    not (parsed.hostname.endswith(".amazonaws.com") or parsed.hostname == "files.gumroad.com" or parsed.hostname.endswith(".gumroad.com")) or url in visited):
                raise ClientError("Unsafe delivered-file URL; inspect the completed product write.")
            visited.add(url)
            try:
                response = self.transfer.get(url, timeout=60, stream=True, allow_redirects=False)
            except requests.RequestException as exc:
                raise ClientError("Attachment verification download failed. Inspect product state before retrying any write.") from exc
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise ClientError("Delivered-file redirect lacks a destination.")
                from urllib.parse import urljoin
                url = urljoin(url, location)
                continue
            break
        else:
            raise ClientError("Delivered-file redirect limit exceeded.")
        try:
            if not response.ok:
                raise ClientError("Attachment download failed. Inspect product state before retrying any write.")
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise ClientError("Attachment exceeds expected size. Inspect product state before retrying any write.")
                digest.update(chunk)
        finally:
            response.close()
        return {"size": size, "sha256": digest.hexdigest()}

    def create_draft(self, fields, receipt=None, *, dry_run=False):
        body = draft_body(fields, receipt)
        if dry_run:
            return draft_preview(fields, receipt)
        result = self.call("POST", "/products", body)
        product = result.get("product")
        if not isinstance(product, dict) or not isinstance(product.get("id"), str):
            raise ClientError("Draft creation response missing product ID; completion unconfirmed. Do not retry.")
        actual = self.get_product(product["id"])
        if actual["product"].get("published") is not False:
            raise ClientError("New product did not remain unpublished. Inspect immediately.")
        self._verify_metadata(actual["product"], fields)
        verification = self._verify_upload(actual["product"], receipt, []) if receipt else None
        return {**result, "verified_product": actual["product"], "delivery": verification}

    def update_product(self, product_id, fields, receipt=None, *, replace_file_id=None, append_file=False, expected_state=None, confirm_live=False, dry_run=False):
        validate_update(fields, receipt, replace_file_id, append_file)
        before = self.get_product(product_id)["product"]
        before_hash = state_hash(before)
        if expected_state and before_hash != expected_state:
            raise ClientError("Product differs from expected state; re-inspect before writing.")
        if before.get("published") is True and not confirm_live and not dry_run:
            raise ClientError("Published product updates affect buyers immediately; pass --confirm-live-update.")
        body, retained = dict(fields), []
        unchanged_file = None
        if receipt and replace_file_id:
            current_file = next((item for item in product_files(before) if item["id"] == replace_file_id), None)
            if current_file is None:
                raise ClientError("Replacement file ID is not attached to this product.")
            if current_file.get("size") == receipt["size"] and isinstance(current_file.get("url"), str):
                actual = self._download_digest(current_file["url"], receipt["size"])
                if actual == {"size": receipt["size"], "sha256": receipt["sha256"]}:
                    unchanged_file = {"file_id": replace_file_id, **actual}
                    receipt = None
                    replace_file_id = None
        if receipt:
            files = product_files(before)
            retained = [f["id"] for f in files if f["id"] != replace_file_id]
            body["files"] = [{"id": value} for value in retained] + [{"external_id": "cli-" + receipt["sha256"][:24], "url": receipt["upload"]["file_url"]}]
        if dry_run:
            return {"dry_run": True, "method": "PUT", "path": "/products/" + identifier(product_id), "state_hash": before_hash, "body": body, "changed": bool(body)}
        self._check_state(product_id, before_hash)
        if not body:
            return {"success": True, "changed": False, "product": before, "delivery": unchanged_file}
        result = self.call("PUT", "/products/" + identifier(product_id), body)
        actual = self.get_product(product_id)
        self._verify_metadata(actual["product"], fields, before)
        delivery = self._verify_upload(actual["product"], receipt, retained) if receipt else unchanged_file
        if not receipt and [f["id"] for f in product_files(actual["product"])] != [f["id"] for f in product_files(before)]:
            raise ClientError("Metadata update changed attachment IDs. Inspect before retrying.")
        return {**result, "verified_product": actual["product"], "delivery": delivery}

    def publish_product(self, product_id, *, confirmation=None, expected_state=None, dry_run=False):
        if not dry_run and confirmation != product_id:
            raise ClientError("Publishing requires --confirm-product-id matching the exact product ID.")
        before = self.get_product(product_id)["product"]
        before_hash = state_hash(before)
        if expected_state and before_hash != expected_state:
            raise ClientError("Product differs from expected state; re-inspect before publishing.")
        if dry_run:
            return {"dry_run": True, "method": "PUT", "path": "/products/" + identifier(product_id) + "/enable", "state_hash": before_hash}
        if before.get("published") is True:
            return {"success": True, "changed": False, "product": before}
        self._check_state(product_id, before_hash)
        result = self.call("PUT", "/products/" + identifier(product_id) + "/enable")
        actual = self.get_product(product_id)["product"]
        if actual.get("published") is not True:
            raise ClientError("Publication unconfirmed. Inspect product state before retrying.")
        if state_hash({**actual, "published": before.get("published")}) != before_hash:
            raise ClientError("Product metadata/files changed during publication. Inspect before retrying.")
        return {**result, "verified_product": actual, "changed": True}
