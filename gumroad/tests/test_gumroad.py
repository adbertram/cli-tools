"""Synthetic Gumroad API and CLI checks. No real product writes."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from typer.testing import CliRunner
from cli_tools_shared.exceptions import ClientError
from gumroad_cli import client, main

runner = CliRunner()
FILE_URL = "https://bucket.s3.amazonaws.com/attachments/seller/guid/original/data.zip"
PART_URL = "https://bucket.s3.amazonaws.com/part?X-Amz-Signature=private"
DELIVERED = "https://files.gumroad.com/download?signature=private"
BYTES = b"arbitrary existing file bytes"


class Response:
    def __init__(self, data=None, status=200, headers=None, content=BYTES):
        self.data, self.status_code = data, status
        self.ok = 200 <= status < 400
        self.headers, self.content = headers or {}, content
        self.closed = False
    def json(self):
        if isinstance(self.data, Exception):
            raise self.data
        return self.data
    def iter_content(self, size):
        yield self.content
    def close(self):
        self.closed = True


class Session:
    def __init__(self, handler):
        self.handler, self.calls = handler, []
    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.handler(method, url, kwargs)
    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)
    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)


@pytest.fixture(autouse=True)
def no_wait_and_synthetic_credential_gate(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda seconds: None)
    from gumroad_cli.config import Config
    monkeypatch.setattr(Config, "_get", lambda self, field: "synthetic" if field == "PERSONAL_ACCESS_TOKEN" else None)


def api(handler, transfer=None):
    return client.GumroadClient(SimpleNamespace(personal_access_token="secret-token"),
        session=Session(handler), transfer=transfer or Session(lambda *a: Response()))


def receipt():
    return {"kind": "gumroad-upload", "version": 1, "filename": "data.zip", "size": len(BYTES),
        "sha256": hashlib.sha256(BYTES).hexdigest(), "upload": {"success": True, "file_url": FILE_URL}}


def product(published=False):
    return {"id": "prod==", "name": "Original", "price": 1500, "currency": "usd", "description": "<p>Keep</p>",
        "published": published, "files": [{"id": "old", "filetype": "zip", "size": 3, "url": DELIVERED},
        {"id": "keep", "filetype": "epub", "size": 100, "custom": "preserve", "url": DELIVERED}],
        "provider_extra": {"preserve": True}}


@pytest.mark.parametrize("data", [None, [], "bad", {"success": False}, ValueError("bad")])
def test_transport_rejects_invalid_json_and_never_retries(data):
    instance = api(lambda *a: Response(data))
    with pytest.raises(ClientError):
        instance.call("POST", "/products", {})
    assert len(instance.session.calls) == 1


def test_transport_does_not_retry_ambiguous_write():
    def fail(*a):
        raise requests.Timeout()
    instance = api(fail)
    with pytest.raises(ClientError, match="completion unconfirmed"):
        instance.call("PUT", "/products/prod", {})
    assert len(instance.session.calls) == 1


def test_pagination_preserves_every_field_and_strips_credential_query():
    def page(method, url, kwargs):
        if url.endswith("/products"):
            return Response({"success": True, "products": [{"id": "1", "extra": 42}],
                "next_page_url": "https://api.gumroad.com/v2/products?page=2&access_token=do-not-forward"})
        assert "access_token" not in url
        return Response({"success": True, "products": [{"id": "2", "other": [1]}]})
    instance = api(page)
    assert instance.list_products() == [{"id": "1", "extra": 42}, {"id": "2", "other": [1]}]
    assert all(c[2]["headers"]["Authorization"] == "Bearer secret-token" for c in instance.session.calls)


def test_unsafe_pagination_and_identity_fail():
    instance = api(lambda *a: Response({"success": True, "products": [], "next_page_url": "https://evil.example/v2/products"}))
    with pytest.raises(ClientError, match="Unsafe"):
        instance.list_products()
    instance = api(lambda *a: Response({"success": True, "product": {"id": "other"}}))
    with pytest.raises(ClientError, match="identity"):
        instance.get_product("prod")


def upload_api(tmp_path, *, fail_part=False, ambiguous=False):
    path = tmp_path / "existing.bin"
    path.write_bytes(BYTES)
    def request(method, url, kwargs):
        if url.endswith("/presign"):
            assert kwargs["json"] == {"filename": path.name, "file_size": len(BYTES)}
            return Response({"success": True, "upload_id": "upload-123", "key": "private-key",
                "parts": [{"part_number": 1, "presigned_url": PART_URL}]})
        if url.endswith("/complete"):
            assert kwargs["json"]["parts"] == [{"part_number": 1, "etag": '"etag"'}]
            if ambiguous:
                raise requests.Timeout()
            return Response({"success": True, "file_url": FILE_URL, "provider_extra": 7})
        if url.endswith("/abort"):
            return Response({"success": True, "status": "accepted"})
        pytest.fail(url)
    def transfer(method, url, kwargs):
        assert "headers" not in kwargs
        assert "secret-token" not in json.dumps(kwargs, default=str)
        if fail_part:
            raise requests.Timeout()
        assert kwargs["data"] == BYTES
        return Response(headers={"ETag": '"etag"'})
    return api(request, Session(transfer)), path


def test_upload_exact_bytes_and_receipt(tmp_path):
    instance, path = upload_api(tmp_path)
    result = instance.upload_file(path)
    assert result["sha256"] == receipt()["sha256"]
    assert result["size"] == len(BYTES)
    assert result["upload"]["provider_extra"] == 7
    assert [c[0] for c in instance.session.calls] == ["POST", "POST"]
    saved = tmp_path / "receipt.json"
    saved.write_text(json.dumps(result))
    assert client.read_receipt(saved) == result


def test_failed_part_aborts_once_and_reports_upload_id(tmp_path):
    instance, path = upload_api(tmp_path, fail_part=True)
    with pytest.raises(ClientError, match="upload-123.*abort accepted"):
        instance.upload_file(path)
    assert not any(c[1].endswith("/complete") for c in instance.session.calls)
    assert sum(c[1].endswith("/abort") for c in instance.session.calls) == 1


def test_ambiguous_complete_never_aborts_or_retries(tmp_path):
    instance, path = upload_api(tmp_path, ambiguous=True)
    with pytest.raises(ClientError, match="completion unconfirmed.*upload-123"):
        instance.upload_file(path)
    assert len(instance.session.calls) == 2
    assert not any(c[1].endswith("/abort") for c in instance.session.calls)


@pytest.mark.parametrize("url", ["https://evil.example/attachments/x", "http://bucket.s3.amazonaws.com/attachments/x", "https://user@bucket.s3.amazonaws.com/attachments/x", FILE_URL + "?signed=1", "https://bucket.s3.amazonaws.com:bad/attachments/x"])
def test_receipts_reject_untrusted_or_signed_canonical_urls(tmp_path, url):
    data = receipt(); data["upload"]["file_url"] = url
    saved = tmp_path / "receipt.json"; saved.write_text(json.dumps(data))
    with pytest.raises(ClientError):
        client.read_receipt(saved)


@pytest.mark.parametrize("mutation", [lambda d: d.update(size=True), lambda d: d.update(sha256="bad"), lambda d: d.update(version=2), lambda d: d.update(version=True), lambda d: d.update(extra=True), lambda d: d.pop("upload")])
def test_malformed_receipts_fail_before_client(tmp_path, monkeypatch, mutation):
    data = receipt(); mutation(data)
    saved = tmp_path / "receipt.json"; saved.write_text(json.dumps(data))
    monkeypatch.setattr(main, "GumroadClient", lambda *a: pytest.fail("Network client created"))
    result = runner.invoke(main.app, ["products", "create-draft", "--name", "A", "--price-cents", "10", "--currency", "usd", "--upload-receipt", str(saved), "--yes"])
    assert result.exit_code != 0


def product_api(initial=None):
    state = {"product": initial or product(), "writes": []}
    def request(method, url, kwargs):
        if method == "GET":
            return Response({"success": True, "product": copy.deepcopy(state["product"])})
        body = kwargs.get("json"); state["writes"].append((url, copy.deepcopy(body)))
        if method == "POST":
            state["product"] = {**product(), "name": body["name"], "price": body["price"], "currency": body["price_currency_type"], "files": []}
            if "files" in body:
                state["product"]["files"] = [{"id": "new", "filetype": "zip", "size": len(BYTES), "url": DELIVERED}]
        elif url.endswith("/enable"):
            state["product"]["published"] = True
        else:
            for key, value in body.items():
                if key == "files":
                    prior = state["product"]["files"]
                    state["product"]["files"] = [next(copy.deepcopy(f) for f in prior if f["id"] == entry["id"]) if "id" in entry else {"id": "new", "filetype": "zip", "size": len(BYTES), "url": DELIVERED} for entry in value]
                else:
                    state["product"]["currency" if key == "price_currency_type" else key] = value
        return Response({"success": True, "product": copy.deepcopy(state["product"]), "provider_extra": "kept"})
    transfer = Session(lambda method, url, kwargs: Response(content=BYTES))
    return api(request, transfer), state


def test_create_draft_preview_equals_actual_request_and_stays_draft():
    instance, state = product_api()
    fields = client.metadata("New", 1700, "usd", "Approved")
    preview = instance.create_draft(fields, receipt(), dry_run=True)
    assert not state["writes"]
    result = instance.create_draft(fields, receipt())
    assert state["writes"][0][1] == preview["body"] == client.draft_body(fields, receipt())
    assert preview["body"]["native_type"] == "digital"
    assert preview["body"]["published"] is False and preview["body"]["draft"] is True
    assert result["verified_product"]["published"] is False
    assert result["delivery"]["sha256"] == receipt()["sha256"]
    assert result["provider_extra"] == "kept"
    assert all("headers" not in c[2] for c in instance.transfer.calls)


def test_replace_retains_all_other_uploaded_files_id_only():
    instance, state = product_api()
    result = instance.update_product("prod==", {}, receipt(), replace_file_id="old")
    assert state["writes"][0][1]["files"][0] == {"id": "keep"}
    assert result["verified_product"]["files"][0]["custom"] == "preserve"
    assert result["verified_product"]["price"] == 1500
    assert result["delivery"]["file_id"] == "new"


def test_metadata_update_omits_files_and_preserves_description():
    instance, state = product_api()
    result = instance.update_product("prod==", {"name": "Renamed"})
    assert state["writes"][0][1] == {"name": "Renamed"}
    assert result["verified_product"]["description"] == "<p>Keep</p>"
    assert [f["id"] for f in result["verified_product"]["files"]] == ["old", "keep"]


def test_live_update_gate_and_stale_target_stop_before_write():
    instance, state = product_api(product(True))
    with pytest.raises(ClientError, match="confirm-live-update"):
        instance.update_product("prod==", {"name": "Renamed"})
    with pytest.raises(ClientError, match="expected state"):
        instance.update_product("prod==", {"name": "Renamed"}, expected_state="stale", confirm_live=True)
    assert not state["writes"]


def test_identical_selected_file_replacement_is_verified_noop():
    original = product(); original["files"][0]["size"] = len(BYTES)
    instance, state = product_api(original)
    result = instance.update_product("prod==", {}, receipt(), replace_file_id="old")
    assert result["changed"] is False
    assert result["delivery"]["file_id"] == "old"
    assert not state["writes"]


def test_publish_exact_confirmation_and_noop():
    instance, state = product_api()
    with pytest.raises(ClientError, match="confirm-product-id"):
        instance.publish_product("prod==", confirmation="other")
    assert not state["writes"]
    result = instance.publish_product("prod==", confirmation="prod==")
    assert result["verified_product"]["published"] is True
    assert state["writes"][0][0].endswith("/products/prod%3D%3D/enable")
    result = instance.publish_product("prod==", confirmation="prod==")
    assert result["changed"] is False and len(state["writes"]) == 1


@pytest.mark.parametrize("args", [["files", "upload"], ["products", "create-draft", "--name", "A", "--price-cents", "0", "--currency", "usd"], ["products", "update", "prod", "--name", "A"], ["products", "publish", "prod", "--confirm-product-id", "prod"]])
def test_mutations_refuse_without_yes_or_dryrun(monkeypatch, tmp_path, args):
    if args == ["files", "upload"]:
        path = tmp_path / "file.bin"; path.write_bytes(BYTES); args += [str(path)]
    monkeypatch.setattr(main, "GumroadClient", lambda *a: pytest.fail("Client created"))
    result = runner.invoke(main.app, args)
    assert result.exit_code != 0
    assert "--yes or --dry-run" in result.output


def test_offline_previews_need_no_client(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "GumroadClient", lambda *a: pytest.fail("Client created"))
    path = tmp_path / "file.bin"; path.write_bytes(BYTES)
    for args in [["files", "upload", str(path), "--dry-run"], ["products", "create-draft", "--name", "A", "--price-cents", "0", "--currency", "usd", "--dry-run"]]:
        result = runner.invoke(main.app, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["dry_run"] is True


def test_list_properties_table_and_filter_before_limit(monkeypatch):
    instance = SimpleNamespace(list_products=lambda: [{"id": "1", "name": "other"}, {"id": "2", "name": "match"}, {"id": "3", "name": "match"}])
    monkeypatch.setattr(main, "GumroadClient", lambda *a: instance)
    result = runner.invoke(main.app, ["products", "list", "-f", "name:eq:match", "-l", "1", "-p", "id"])
    assert result.exit_code == 0 and json.loads(result.stdout) == [{"id": "2"}]
    result = runner.invoke(main.app, ["products", "list", "-p", "id", "-t"])
    assert result.exit_code == 0 and "Name" not in result.output and "Price" not in result.output


def test_cli_draft_preview_matches_client_preview(monkeypatch):
    monkeypatch.setattr(main, "GumroadClient", lambda *a: pytest.fail("Offline preview created client"))
    result = runner.invoke(main.app, ["products", "create-draft", "--name", "A", "--price-cents", "20", "--currency", "usd", "--dry-run"])
    assert result.exit_code == 0, result.output
    instance, _ = product_api()
    assert json.loads(result.stdout) == instance.create_draft(client.metadata("A", 20, "usd"), dry_run=True)


@pytest.mark.parametrize("fields,upload,replace,append", [({}, None, None, False), ({"name":"A"}, None, "old", False), ({}, receipt(), None, False), ({}, receipt(), "old", True)])
def test_direct_update_invalid_targeting_never_reads_api(fields, upload, replace, append):
    instance = api(lambda *a: pytest.fail("API read before input validation"))
    with pytest.raises(ClientError):
        instance.update_product("prod", fields, upload, replace_file_id=replace, append_file=append)


def test_state_hash_ignores_signed_download_rotation_but_tracks_external_link_changes():
    original = product()
    changed = copy.deepcopy(original)
    changed["files"][0]["url"] = "https://files.gumroad.com/new-signed-download"
    assert client.state_hash(original) == client.state_hash(changed)
    original["files"][0]["filetype"] = changed["files"][0]["filetype"] = "link"
    assert client.state_hash(original) != client.state_hash(changed)
