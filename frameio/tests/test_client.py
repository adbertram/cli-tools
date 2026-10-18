import base64
import json
from urllib.error import HTTPError

import pytest

from frameio_cli import client

from conftest import (ASSET, IMAGE, SHARE, SHARE_URL, SIGNED, URL, Response, collection_of,
                      graphql, image_metadata, metadata, public_share)


def test_public_redirect_and_session_contract(monkeypatch):
    requests = []

    def opened(request, timeout):
        requests.append(request)
        if request.full_url.startswith("https://f.io/"):
            assert request.get_header("User-agent") == client.USER_AGENT
            return Response()
        assert request.full_url == "https://api.frame.io/graphql"
        assert timeout == 30
        return graphql({"data": {"share": {"id": SHARE}}})

    monkeypatch.setattr(client, "urlopen", opened)
    first = client.PublicShare("https://f.io/public")
    second = client.PublicShare("https://f.io/public")
    assert first.share_id == SHARE
    assert first.session_id != second.session_id
    first._read("GetShareForShareReview", {"shareId": SHARE})
    request = requests[-1]
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["x-frameio-share-authentication"] == base64.b64encode(SHARE.encode()).decode()
    assert headers["x-frameio-session-id"] == first.session_id
    assert headers["x-gql-op"] == "GetShareForShareReview"
    assert headers["apollographql-client-name"] == "web-app"
    assert headers["apollographql-client-version"] == "@frameio/next-web-app@724.0"
    assert headers["referer"] == "https://next.frame.io/"
    body = json.loads(request.data)
    assert body["operationName"] == "GetShareForShareReview"
    assert body["variables"] == {"shareId": SHARE}
    assert body["query"] == client.QUERIES["GetShareForShareReview"]


@pytest.mark.parametrize("url", ["http://next.frame.io/share/" + SHARE, "https://evil.example/share/" + SHARE,
                                 "https://user:pw@next.frame.io/share/" + SHARE])
def test_unsupported_share_urls_are_rejected(url):
    with pytest.raises(client.FrameIOError, match="invalid HTTPS URL|unsupported"):
        client.PublicShare(url)


def test_share_url_must_name_a_uuid_share(monkeypatch):
    with pytest.raises(client.FrameIOError, match="invalid share ID"):
        client.PublicShare("https://next.frame.io/share/not-a-uuid")
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: Response(url="https://next.frame.io/projects/x"))
    with pytest.raises(client.FrameIOError, match="supported public share URL"):
        client.PublicShare("https://f.io/public")


@pytest.mark.parametrize("settings,message", [
    ({"id": SHARE, "enabled": False}, "disabled"),
    ({"id": SHARE, "enabled": True, "downloadingEnabled": False}, "allow downloads"),
    ({"id": SHARE, "enabled": True, "downloadingEnabled": True}, "missing expiration"),
    ({"id": SHARE, "enabled": True, "downloadingEnabled": True,
      "expiration": "2000-01-01T00:00:00Z"}, "expired"),
    ({"id": SHARE, "enabled": True, "downloadingEnabled": True,
      "expiration": "tomorrow"}, "malformed expiration"),
    ({"id": SHARE, "enabled": True, "downloadingEnabled": True,
      "expiration": "2999-01-01T00:00:00"}, "malformed expiration"),
    ({"id": "different", "enabled": True}, "protected"),
])
def test_download_permission_is_required(monkeypatch, settings, message):
    share = public_share(monkeypatch, settings=settings)
    with pytest.raises(client.FrameIOError, match=message):
        share.list_assets()


def test_future_expiration_is_allowed(monkeypatch):
    share = public_share(monkeypatch, settings={
        "id": SHARE, "enabled": True, "downloadingEnabled": True, "expiration": "2999-01-01T00:00:00Z"})
    assert [row["id"] for row in share.list_assets()] == [ASSET]


@pytest.mark.parametrize("document", [[], {}, {"data": None},
    {"data": {"share": {}}, "errors": [{"message": "secret"}]}])
def test_malformed_graphql_fails_without_leaking_output(monkeypatch, document):
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: graphql(document))
    with pytest.raises(client.FrameIOError, match="errors or missing data") as error:
        client.PublicShare(SHARE_URL)._read("GetShareForShareReview", {"shareId": SHARE})
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("body", [b"not JSON", b'{"data":{}' + b" " * client.MAX_RESPONSE])
def test_invalid_and_oversized_metadata_fail(monkeypatch, body):
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: Response(body))
    with pytest.raises(client.FrameIOError, match="malformed JSON|response limit"):
        client.PublicShare(SHARE_URL)._read("GetShareForShareReview", {"shareId": SHARE})


@pytest.mark.parametrize("collection,message", [
    ({"nodes": [{"id": ASSET}], "pageInfo": {"hasNextPage": True}}, "pagination is not verified"),
    ({"nodes": [{"id": ASSET}], "pageInfo": {}}, "malformed pagination"),
    ({"nodes": [{"id": "bad"}], "pageInfo": {"hasNextPage": False}}, "invalid asset ID"),
    ({"nodes": [{"id": ASSET}, {"id": ASSET}], "pageInfo": {"hasNextPage": False}}, "duplicate"),
    ({"nodes": "bad", "pageInfo": {"hasNextPage": False}}, "malformed assets"),
])
def test_incomplete_or_malformed_discovery_fails(monkeypatch, collection, message):
    share = public_share(monkeypatch, collection=collection)
    with pytest.raises(client.FrameIOError, match=message):
        share.list_assets(limit=1)


@pytest.mark.parametrize("asset,message", [
    ({}, "malformed asset"),
    (metadata(media={}), "missing original"),
    (metadata(media={"original": {"downloadUrl": "http://media.example/v", "filesizeInBytes": 5}}), "invalid HTTPS"),
    (metadata(media={"original": {"downloadUrl": "https://[", "filesizeInBytes": 5}}), "invalid HTTPS"),
    (metadata(media={"original": {"downloadUrl": "https://media.example/v", "filesizeInBytes": 0}}), "valid original"),
])
def test_missing_original_metadata_is_explicit(monkeypatch, asset, message):
    share = public_share(monkeypatch, asset=asset)
    with pytest.raises(client.FrameIOError, match=message):
        share.list_assets()


def test_asset_rows_have_the_documented_shape(monkeypatch):
    share = public_share(monkeypatch, collection=collection_of(ASSET, IMAGE),
                         assets={ASSET: metadata(), IMAGE: image_metadata()})
    assert share.list_assets() == [
        {"id": ASSET, "share_id": SHARE, "name": "approved.mp4", "type": "VideoAsset", "video": True,
         "size": 5, "mime_type": "video/mp4", "status": "TRANSCODED", "url": URL, "download_url": SIGNED},
        {"id": IMAGE, "share_id": SHARE, "name": "still.png", "type": "ImageAsset", "video": False,
         "size": None, "mime_type": None, "status": "TRANSCODED", "url": client.stable_url(SHARE, IMAGE),
         "download_url": None},
    ]
    assert share.get_asset(IMAGE)["download_url"] is None


def test_limit_bounds_asset_lookups(monkeypatch):
    share = public_share(monkeypatch, collection=collection_of(IMAGE, ASSET),
                         assets={ASSET: metadata(), IMAGE: image_metadata()})
    assert [row["id"] for row in share.list_assets(limit=1)] == [IMAGE]


def test_non_video_is_not_treated_as_video(monkeypatch):
    share = public_share(monkeypatch, asset=metadata(__typename="ImageAsset"))
    assert share.list_assets()[0]["video"] is False
    with pytest.raises(client.FrameIOError, match="not a video"):
        share._video(ASSET)


def test_asset_id_must_be_a_uuid(monkeypatch):
    share = public_share(monkeypatch)
    with pytest.raises(client.FrameIOError, match="invalid Frame.io asset ID"):
        share.get_asset("nope")


def test_download_must_belong_to_share(monkeypatch):
    share = public_share(monkeypatch, collection=collection_of())
    with pytest.raises(client.FrameIOError, match="not in the share"):
        share.get_asset(ASSET)
    with pytest.raises(client.FrameIOError, match="not in the share"):
        share._video(ASSET)


def test_expired_signed_url_is_refreshed_once(monkeypatch, tmp_path):
    share = public_share(monkeypatch)
    reads, downloads = [], []

    def info(asset_id):
        reads.append(asset_id)
        return {"id": ASSET, "name": "approved.mp4", "size": 5, "url": URL,
                "download_url": "https://media.example/%d" % len(reads)}

    def opened(request, timeout):
        downloads.append(request.full_url)
        if len(downloads) == 1:
            raise HTTPError(request.full_url, 403, "expired", None, None)
        return Response(b"video")

    monkeypatch.setattr(share, "_video", info)
    monkeypatch.setattr(client, "urlopen", opened)
    result = share.download(ASSET, tmp_path / "video.mp4")
    assert downloads == ["https://media.example/1", "https://media.example/2"]
    assert result["url"] == URL
    assert (tmp_path / "video.mp4").read_bytes() == b"video"
    assert not (tmp_path / "video.mp4.part").exists()


def test_failed_download_does_not_replace_complete_file(monkeypatch, tmp_path):
    share = public_share(monkeypatch)
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: Response(b"shorter than claimed"))
    target = tmp_path / "video.mp4"
    target.write_bytes(b"prior")
    with pytest.raises(client.FrameIOError, match="size does not match"):
        share.download(ASSET, target)
    assert target.read_bytes() == b"prior"
    assert not target.with_suffix(".mp4.part").exists()


def test_short_download_fails_size_check(monkeypatch, tmp_path):
    share = public_share(monkeypatch)
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: Response(b"abc"))
    with pytest.raises(client.FrameIOError, match="size does not match"):
        share.download(ASSET, tmp_path / "video.mp4")
    assert list(tmp_path.iterdir()) == []


def test_repeated_expired_url_fails_after_one_refresh(monkeypatch, tmp_path):
    share = public_share(monkeypatch)
    calls = []

    def opened(request, **kwargs):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 403, "expired signature", None, None)

    monkeypatch.setattr(client, "urlopen", opened)
    with pytest.raises(client.FrameIOError, match="HTTP 403"):
        share.download(ASSET, tmp_path / "video.mp4")
    assert len(calls) == 2
    assert list(tmp_path.iterdir()) == []


def test_non_auth_http_error_is_not_retried(monkeypatch, tmp_path):
    share = public_share(monkeypatch)
    calls = []

    def opened(request, **kwargs):
        calls.append(request.full_url)
        raise HTTPError(request.full_url, 500, "boom", None, None)

    monkeypatch.setattr(client, "urlopen", opened)
    with pytest.raises(client.FrameIOError, match="HTTP 500"):
        share.download(ASSET, tmp_path / "video.mp4")
    assert len(calls) == 1


def test_download_destination_must_be_a_file_in_an_existing_directory(monkeypatch, tmp_path):
    share = public_share(monkeypatch)
    for bad in (tmp_path, tmp_path / "missing" / "video.mp4"):
        with pytest.raises(client.FrameIOError, match="existing directory"):
            share.download(ASSET, bad)


def test_signed_urls_are_never_written_to_disk(monkeypatch, tmp_path):
    share = public_share(monkeypatch)
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: Response(b"video"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    share.download(ASSET, tmp_path / "video.mp4")
    for path in tmp_path.rglob("*"):
        if path.is_file() and path.name != "video.mp4":
            assert "signature" not in path.read_text(errors="ignore")


def folder_share(monkeypatch, collections):
    share = public_share(monkeypatch)
    original_read = share._read

    def read(operation, variables):
        if operation == "GetShareCollectionAssets":
            assert "folderId: $folderId" in client.QUERIES[operation]
            return {"share": {"id": SHARE, "collectionAssets":
                collections.get((variables["folderId"], variables["assetType"]), collection_of())}}
        return original_read(operation, variables)

    monkeypatch.setattr(share, "_read", read)
    return share


def test_nested_share_files_are_discovered_and_download_membership_verified(monkeypatch):
    folder = "a5274655-1aac-4d2b-b728-11b16bed7dcb"
    nested = "d5274655-1aac-4d2b-b728-11b16bed7dcb"
    share = folder_share(monkeypatch, {
        (None, "FOLDER"): collection_of(folder),
        (folder, "FOLDER"): collection_of(nested),
        (nested, "FILE"): collection_of(ASSET),
    })
    assert share.asset_ids() == [ASSET]
    assert share.list_assets()[0]["id"] == ASSET
    assert share.get_asset(ASSET)["video"] is True
    with pytest.raises(client.FrameIOError, match="not in the share"):
        share.get_asset(IMAGE)


def test_folder_cycles_fail_without_looping(monkeypatch):
    share = folder_share(monkeypatch, {
        (None, "FOLDER"): collection_of(IMAGE),
        (IMAGE, "FOLDER"): collection_of(IMAGE),
    })
    with pytest.raises(client.FrameIOError, match="duplicate"):
        share.asset_ids()


def test_nested_pagination_cannot_silently_omit_files(monkeypatch):
    share = folder_share(monkeypatch, {
        (None, "FOLDER"): collection_of(IMAGE),
        (IMAGE, "FILE"): {"nodes": [{"id": ASSET}], "pageInfo": {"hasNextPage": True}},
    })
    with pytest.raises(client.FrameIOError, match="pagination is not verified"):
        share.list_assets(limit=1)


def test_total_discovery_budget_includes_folders(monkeypatch):
    monkeypatch.setattr(client, "MAX_ASSETS", 1)
    share = folder_share(monkeypatch, {
        (None, "FOLDER"): collection_of(IMAGE),
        (IMAGE, "FILE"): collection_of(ASSET),
    })
    with pytest.raises(client.FrameIOError, match="exceeds supported discovery"):
        share.asset_ids()
