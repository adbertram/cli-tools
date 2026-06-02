"""Chrome Web Store API models."""
from typing import Optional

from pydantic import Field

from .base import CLIModel


class WebStoreDistributionChannel(CLIModel):
    """Deployment information for a Chrome Web Store release channel."""

    deploy_percentage: int = Field(alias="deployPercentage")
    crx_version: str = Field(alias="crxVersion")


class WebStoreItemRevisionStatus(CLIModel):
    """Status of a Chrome Web Store item revision."""

    state: str
    distribution_channels: Optional[list[WebStoreDistributionChannel]] = Field(
        default=None,
        alias="distributionChannels",
    )


class WebStoreStatus(CLIModel):
    """Chrome Web Store item status."""

    name: str
    item_id: str = Field(alias="itemId")
    public_key: Optional[str] = Field(default=None, alias="publicKey")
    published_item_revision_status: Optional[WebStoreItemRevisionStatus] = Field(
        default=None,
        alias="publishedItemRevisionStatus",
    )
    submitted_item_revision_status: Optional[WebStoreItemRevisionStatus] = Field(
        default=None,
        alias="submittedItemRevisionStatus",
    )
    last_async_upload_state: Optional[str] = Field(
        default=None,
        alias="lastAsyncUploadState",
    )
    taken_down: Optional[bool] = Field(default=None, alias="takenDown")
    warned: Optional[bool] = None


class WebStoreUploadResult(CLIModel):
    """Chrome Web Store package upload result."""

    name: str
    item_id: str = Field(alias="itemId")
    crx_version: Optional[str] = Field(default=None, alias="crxVersion")
    upload_state: str = Field(alias="uploadState")


class WebStorePackageResult(CLIModel):
    """Chrome Web Store extension package result."""

    zip_path: str
    manifest_name: str
    manifest_version: str
    file_count: int
    files: list[str]


class WebStoreUploadExtensionResult(CLIModel):
    """Chrome Web Store package and upload result."""

    package: WebStorePackageResult
    upload: WebStoreUploadResult


class WebStorePublishResult(CLIModel):
    """Chrome Web Store publish submission result."""

    name: str
    item_id: str = Field(alias="itemId")
    state: str


class WebStoreReleaseResult(CLIModel):
    """Chrome Web Store package, upload, and publish result."""

    package: WebStorePackageResult
    upload: WebStoreUploadResult
    publish: WebStorePublishResult


class WebStoreOperationResult(CLIModel):
    """Result for Chrome Web Store API calls with empty response bodies."""

    name: str
    action: str
    success: bool


class WebStoreListingAsset(CLIModel):
    """Validated Chrome Web Store listing image asset."""

    kind: str
    path: str
    width: int
    height: int


class WebStoreListingData(CLIModel):
    """Parsed Chrome Web Store Store Listing tab data."""

    title: str
    summary: str
    description: str
    category: str
    language: str
    homepage_url: str
    support_url: str
    privacy_policy_url: str
    screenshots: list[WebStoreListingAsset]
    small_promo_tile: Optional[WebStoreListingAsset] = None
    marquee_promo_image: Optional[WebStoreListingAsset] = None


class WebStoreListingUpdateResult(CLIModel):
    """Result from updating Chrome Web Store listing data in the dashboard."""

    item_id: str
    dashboard_url: str
    updated_fields: list[str]
    uploaded_assets: list[WebStoreListingAsset]
    save_status: str
