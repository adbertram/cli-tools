import io
import json

import pytest

from frameio_cli import client

SHARE = "7f6203a3-8ec1-49fa-9c7c-07e3c1a8a9dd"
SHARE_URL = "https://next.frame.io/share/" + SHARE
ASSET = "5f14f9b8-b379-416d-98cb-40872e5f50bb"
IMAGE = "0b1d1f5e-3c0e-4d6e-9f41-5a8b0f0c2a11"
URL = client.stable_url(SHARE, ASSET)
SIGNED = "https://media.example/video.mp4?signature=fresh"


def metadata(url=SIGNED, **changes):
    asset = {"id": ASSET, "name": "approved.mp4", "__typename": "VideoAsset",
             "assetType": "FILE", "status": "TRANSCODED",
             "media": {"mimeType": "video/mp4", "filesize": 5,
                       "original": {"downloadUrl": url, "filesizeInBytes": 5}}}
    asset.update(changes)
    return asset


def image_metadata():
    return {"id": IMAGE, "name": "still.png", "__typename": "ImageAsset",
            "assetType": "FILE", "status": "TRANSCODED"}


def collection_of(*ids):
    return {"nodes": [{"id": i} for i in ids], "pageInfo": {"hasNextPage": False, "mode": "CURSOR"}}


def public_share(monkeypatch, *, settings=None, collection=None, asset=None, assets=None):
    """PublicShare whose GraphQL reads are served from the given payloads."""
    settings = settings if settings is not None else {
        "id": SHARE, "enabled": True, "downloadingEnabled": True, "expiration": None}
    collection = collection if collection is not None else collection_of(ASSET)
    assets = assets if assets is not None else {ASSET: metadata() if asset is None else asset}

    def read(self, operation, variables):
        if operation == "GetShareForShareReview":
            return {"share": settings}
        if operation == "GetShareCollectionAssets":
            assert variables["folderId"] is None
            if variables["assetType"] == "FOLDER":
                return {"share": {"id": SHARE, "collectionAssets": collection_of()}}
            assert variables == {"shareId": SHARE, "folderId": None, "assetType": "FILE", "page": {"first": 200}}
            return {"share": {"id": SHARE, "collectionAssets": collection}}
        if operation == "GetAssetForDownload":
            return {"asset": assets[variables["assetId"]]}
        pytest.fail("unknown Frame.io read")

    monkeypatch.setattr(client.PublicShare, "_read", read)
    return client.PublicShare(SHARE_URL)


class Response(io.BytesIO):
    def __init__(self, body=b"", *, url=SHARE_URL, headers=None, status=200):
        super().__init__(body)
        self.url, self.headers, self.status = url, headers or {}, status

    def geturl(self):
        return self.url


def graphql(document):
    return Response(json.dumps(document).encode())
