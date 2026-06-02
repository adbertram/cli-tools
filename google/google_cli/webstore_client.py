"""Chrome Web Store API v2 client."""
from pathlib import Path
from typing import Optional

from google.auth.credentials import Credentials as GoogleCredentials
from google.auth.transport.requests import AuthorizedSession

from .client import ClientError
from .models.webstore import (
    WebStoreOperationResult,
    WebStorePublishResult,
    WebStoreStatus,
    WebStoreUploadResult,
)


class ChromeWebStoreClient:
    """Client for Chrome Web Store API v2."""

    BASE_URL = "https://chromewebstore.googleapis.com"

    def __init__(
        self,
        credentials: Optional[GoogleCredentials] = None,
        access_token: Optional[str] = None,
        session=None,
    ):
        if credentials is None and access_token is None:
            raise ClientError("Chrome Web Store client requires Google credentials")

        self.access_token = access_token
        if session is not None:
            self.session = session
        else:
            self.session = AuthorizedSession(credentials)

    def _headers(self, extra_headers: Optional[dict[str, str]] = None) -> dict[str, str]:
        headers = {}
        if self.access_token is not None:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if extra_headers is not None:
            headers.update(extra_headers)
        return headers

    def _item_name(self, publisher_id: str, item_id: str) -> str:
        return f"publishers/{publisher_id}/items/{item_id}"

    def _request(self, method: str, path: str, **kwargs) -> dict:
        response = self.session.request(method, f"{self.BASE_URL}{path}", **kwargs)
        response.raise_for_status()
        if response.text == "":
            return {}
        return response.json()

    def fetch_status(self, publisher_id: str, item_id: str) -> WebStoreStatus:
        """Fetch Chrome Web Store item status."""
        name = self._item_name(publisher_id, item_id)
        payload = self._request(
            "GET",
            f"/v2/{name}:fetchStatus",
            headers=self._headers(),
        )
        return WebStoreStatus(**payload)

    def upload_package(
        self,
        publisher_id: str,
        item_id: str,
        package: Path,
    ) -> WebStoreUploadResult:
        """Upload a new package to an existing Chrome Web Store item."""
        name = self._item_name(publisher_id, item_id)
        payload = self._request(
            "POST",
            f"/upload/v2/{name}:upload",
            headers=self._headers({"Content-Type": "application/zip"}),
            data=package.read_bytes(),
        )
        return WebStoreUploadResult(**payload)

    def publish_item(
        self,
        publisher_id: str,
        item_id: str,
        publish_type: Optional[str],
        deploy_percentage: Optional[int],
        skip_review: bool,
    ) -> WebStorePublishResult:
        """Submit an item to be published in the Chrome Web Store."""
        body = {}
        if publish_type is not None:
            body["publishType"] = publish_type
        if deploy_percentage is not None:
            self._validate_percentage(deploy_percentage)
            body["deployInfos"] = [{"deployPercentage": deploy_percentage}]
        if skip_review:
            body["skipReview"] = True

        name = self._item_name(publisher_id, item_id)
        payload = self._request(
            "POST",
            f"/v2/{name}:publish",
            headers=self._headers(),
            json=body,
        )
        return WebStorePublishResult(**payload)

    def cancel_submission(self, publisher_id: str, item_id: str) -> WebStoreOperationResult:
        """Cancel the active Chrome Web Store submission for an item."""
        name = self._item_name(publisher_id, item_id)
        self._request(
            "POST",
            f"/v2/{name}:cancelSubmission",
            headers=self._headers(),
        )
        return WebStoreOperationResult(
            name=name,
            action="cancelSubmission",
            success=True,
        )

    def set_published_deploy_percentage(
        self,
        publisher_id: str,
        item_id: str,
        deploy_percentage: int,
    ) -> WebStoreOperationResult:
        """Set a higher target deploy percentage for the published revision."""
        self._validate_percentage(deploy_percentage)
        name = self._item_name(publisher_id, item_id)
        self._request(
            "POST",
            f"/v2/{name}:setPublishedDeployPercentage",
            headers=self._headers(),
            json={"deployPercentage": deploy_percentage},
        )
        return WebStoreOperationResult(
            name=name,
            action="setPublishedDeployPercentage",
            success=True,
        )

    def _validate_percentage(self, deploy_percentage: int):
        if deploy_percentage < 0 or deploy_percentage > 100:
            raise ClientError("deploy percentage must be between 0 and 100")
