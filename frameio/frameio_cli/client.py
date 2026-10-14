"""Read public Frame.io shares without persisting signed media URLs.

The request fields below were captured from the public share web app. Cursor input
semantics were not established, so shares requiring another page fail explicitly.
"""

import base64
import json
import uuid
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from cli_tools_shared.exceptions import ClientError

ENDPOINT = "https://api.frame.io/graphql"
USER_AGENT = "frameio-cli/0.1"
MAX_ASSETS = 200
MAX_RESPONSE = 2 * 1024 * 1024
QUERIES = {
    "GetShareForShareReview": """query GetShareForShareReview($shareId: ID!) {
      share(shareId: $shareId) { id enabled downloadingEnabled expiration }
    }""",
    "GetShareCollectionAssets": """query GetShareCollectionAssets(
      $shareId: ID!, $assetType: ChildAssetTypeInput, $page: PageInput!) {
      share(shareId: $shareId) {
        id
        collectionAssets(page: $page, assetType: $assetType) {
          pageInfo { endCursor hasNextPage mode }
          nodes { id }
        }
      }
    }""",
    "GetAssetForDownload": """query GetAssetForDownload($assetId: ID!) {
      asset(assetId: $assetId) {
        id name assetType status __typename
        ... on VideoAsset {
          media {
            filesize mimeType
            original { key downloadUrl filesizeInBytes }
          }
        }
      }
    }""",
}


class FrameIOError(ClientError):
    pass


def _uuid(value: object, field: str, *, returned: bool = True) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        message = f"Frame.io returned an invalid {field}" if returned else f"invalid Frame.io {field}: {value}"
        raise FrameIOError(message) from None


def _https_url(url: str):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise FrameIOError("Frame.io returned an invalid HTTPS URL") from None


def _share_id(url: str) -> str:
    parsed = _https_url(url)
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname != "next.frame.io" or len(parts) < 2 or parts[0] != "share":
        raise FrameIOError("Frame.io share did not resolve to a supported public share URL")
    return _uuid(parts[1], "share ID")


def share_url(share_id: str) -> str:
    return "https://next.frame.io/share/%s" % _uuid(share_id, "share ID")


def stable_url(share_id: str, asset_id: str) -> str:
    return "%s/view/%s" % (share_url(share_id), _uuid(asset_id, "asset ID"))


class PublicShare:
    """One unauthenticated share session, bounded to the observed first-page contract."""

    def __init__(self, url: str):
        parsed = _https_url(url)
        if parsed.hostname not in {"f.io", "next.frame.io"}:
            raise FrameIOError("unsupported Frame.io share URL")
        if parsed.hostname == "f.io":
            try:
                with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as response:
                    url = response.geturl()
            except (HTTPError, URLError, TimeoutError, OSError):
                raise FrameIOError("could not resolve the public Frame.io share") from None
        self.share_id = _share_id(url)
        self.session_id = str(uuid.uuid4())

    def _read(self, operation: str, variables: dict) -> dict:
        body = json.dumps({"operationName": operation, "variables": variables,
                           "query": QUERIES[operation]}).encode()
        headers = {"user-agent": USER_AGENT, "content-type": "application/json",
                   "apollographql-client-name": "web-app",
                   "apollographql-client-version": "@frameio/next-web-app@724.0",
                   "x-gql-op": operation, "x-frameio-session-id": self.session_id,
                   "x-frameio-share-authentication": base64.b64encode(self.share_id.encode()).decode(),
                   "referer": "https://next.frame.io/"}
        try:
            with urlopen(Request(ENDPOINT, data=body, headers=headers), timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise FrameIOError("Frame.io metadata exceeds the response limit")
            document = json.loads(raw)
        except (HTTPError, URLError, TimeoutError, OSError):
            raise FrameIOError(f"Frame.io {operation} request failed") from None
        except (ValueError, UnicodeError):
            raise FrameIOError("Frame.io returned malformed JSON") from None
        if not isinstance(document, dict) or document.get("errors") or not isinstance(document.get("data"), dict):
            raise FrameIOError(f"Frame.io {operation} returned errors or missing data")
        return document["data"]

    def _settings(self) -> dict:
        settings = self._read("GetShareForShareReview", {"shareId": self.share_id}).get("share")
        if not isinstance(settings, dict) or settings.get("id") != self.share_id:
            raise FrameIOError("Frame.io public share is unavailable or protected")
        return settings

    def share(self) -> dict:
        """Share settings: {"id","url","enabled","downloadingEnabled","expiration"}."""
        settings = self._settings()
        enabled, downloading = settings.get("enabled"), settings.get("downloadingEnabled")
        if type(enabled) is not bool or type(downloading) is not bool or "expiration" not in settings:
            raise FrameIOError("Frame.io share returned malformed settings")
        return {"id": self.share_id, "url": share_url(self.share_id), "enabled": enabled,
                "downloadingEnabled": downloading, "expiration": settings["expiration"]}

    def asset_ids(self) -> list[str]:
        settings = self._settings()
        if settings.get("enabled") is not True:
            raise FrameIOError("Frame.io share is disabled or missing enabled permission")
        if settings.get("downloadingEnabled") is not True:
            raise FrameIOError("Frame.io share does not allow downloads")
        if "expiration" not in settings:
            raise FrameIOError("Frame.io share is missing expiration metadata")
        if settings["expiration"] is not None:
            try:
                expiration = datetime.fromisoformat(settings["expiration"].replace("Z", "+00:00"))
                if expiration.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError, AttributeError):
                raise FrameIOError("Frame.io share has malformed expiration metadata") from None
            if expiration <= datetime.now(timezone.utc):
                raise FrameIOError("Frame.io share has expired")
        share = self._read("GetShareCollectionAssets", {
            "shareId": self.share_id, "assetType": "FILE", "page": {"first": MAX_ASSETS}}).get("share")
        if not isinstance(share, dict) or share.get("id") != self.share_id:
            raise FrameIOError("Frame.io share returned no asset collection")
        collection = share.get("collectionAssets")
        if not isinstance(collection, dict) or not isinstance(collection.get("nodes"), list):
            raise FrameIOError("Frame.io share returned malformed assets")
        page = collection.get("pageInfo")
        if not isinstance(page, dict) or type(page.get("hasNextPage")) is not bool:
            raise FrameIOError("Frame.io share returned malformed pagination")
        if page["hasNextPage"] or len(collection["nodes"]) > MAX_ASSETS:
            raise FrameIOError("Frame.io share exceeds supported discovery; cursor pagination is not verified")
        ids = [_uuid(node.get("id") if isinstance(node, dict) else None, "asset ID")
               for node in collection["nodes"]]
        if len(set(ids)) != len(ids):
            raise FrameIOError("Frame.io share returned duplicate asset IDs")
        return ids

    def _asset(self, asset_id: str) -> dict:
        asset = self._read("GetAssetForDownload", {"assetId": asset_id}).get("asset")
        if not isinstance(asset, dict) or asset.get("id") != asset_id or not isinstance(asset.get("name"), str) or not asset["name"]:
            raise FrameIOError("Frame.io returned malformed asset metadata")
        if not isinstance(asset.get("__typename"), str):
            raise FrameIOError("Frame.io asset is missing its media type")
        row = {"id": asset_id, "share_id": self.share_id, "name": asset["name"],
               "type": asset["__typename"], "video": asset["__typename"] == "VideoAsset",
               "size": None, "mime_type": None, "status": asset.get("status"),
               "url": stable_url(self.share_id, asset_id), "download_url": None}
        if not row["video"]:
            return row
        media = asset.get("media")
        original = media.get("original") if isinstance(media, dict) else None
        if not isinstance(original, dict):
            raise FrameIOError("Frame.io video is missing original media")
        size = original.get("filesizeInBytes")
        url = original.get("downloadUrl")
        if type(size) is not int or size <= 0 or not isinstance(url, str):
            raise FrameIOError("Frame.io video is missing a valid original download URL or size")
        _https_url(url)
        row.update(size=size, mime_type=media.get("mimeType"), download_url=url)
        return row

    def list_assets(self, limit: int = 100) -> list[dict]:
        """Rows for the first `limit` assets of the share's FILE collection, in API order."""
        return [self._asset(asset_id) for asset_id in self.asset_ids()[:limit]]

    def get_asset(self, asset_id: str) -> dict:
        asset_id = _uuid(asset_id, "asset ID", returned=False)
        if asset_id not in self.asset_ids():
            raise FrameIOError("Frame.io asset is not in the share")
        return self._asset(asset_id)

    def _video(self, asset_id: str) -> dict:
        asset = self.get_asset(asset_id)
        if not asset["video"]:
            raise FrameIOError("Frame.io asset is not a video")
        return asset

    def download(self, asset_id: str, destination: Path) -> dict:
        """Resolve an original URL immediately before each attempt; publish only complete files."""
        if not destination.parent.is_dir() or destination.is_dir():
            raise FrameIOError(f"download path is not a file in an existing directory: {destination}")
        partial = destination.with_name(destination.name + ".part")
        try:
            for attempt in range(2):
                asset = self._video(asset_id)
                try:
                    with urlopen(Request(asset["download_url"], headers={"User-Agent": USER_AGENT}), timeout=60) as response, partial.open("wb") as output:
                        received = 0
                        while chunk := response.read(min(1024 * 1024, asset["size"] - received + 1)):
                            received += len(chunk)
                            if received > asset["size"]:
                                raise FrameIOError("Frame.io download size does not match original media")
                            output.write(chunk)
                    if partial.stat().st_size != asset["size"]:
                        raise FrameIOError("Frame.io download size does not match original media")
                    partial.replace(destination)
                    return asset
                except HTTPError as error:
                    if error.code in {401, 403} and attempt == 0:
                        continue
                    raise FrameIOError(f"Frame.io original download failed (HTTP {error.code})") from None
                except (URLError, TimeoutError, OSError, HTTPException):
                    raise FrameIOError("Frame.io original download failed") from None
        finally:
            partial.unlink(missing_ok=True)
