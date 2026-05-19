"""Looker Studio REST and Linking API helpers."""
from typing import Optional, Union
from urllib.parse import urlencode

from google.auth.transport.requests import AuthorizedSession

from .client import ClientError, GoogleClient
from .models.lookerstudio import (
    LookerStudioAsset,
    LookerStudioDataSourceParameter,
    LookerStudioPermissions,
    LookerStudioReportLink,
    LookerStudioRole,
)

API_BASE_URL = "https://datastudio.googleapis.com/v1"
REPORTING_CREATE_URL = "https://lookerstudio.google.com/reporting/create"
REPORTING_EMBED_CREATE_URL = "https://lookerstudio.google.com/embed/reporting/create"
DATASTUDIO_SCOPE = "https://www.googleapis.com/auth/datastudio"


def _format_link_value(value: Union[str, bool]) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return value


def parse_bool(value: str) -> bool:
    """Parse a strict boolean string."""
    normalized = value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"Expected boolean value true or false, got {value}")


def parse_linking_parameter(value: str) -> LookerStudioDataSourceParameter:
    """Parse alias.key=value into a Linking API data source parameter."""
    if "=" not in value:
        raise ValueError("Expected data source parameter in alias.key=value format")
    left, raw_value = value.split("=", 1)
    if "." not in left:
        raise ValueError("Expected data source parameter in alias.key=value format")
    alias, key = left.split(".", 1)
    if not alias or not key or raw_value == "":
        raise ValueError("Expected data source parameter in alias.key=value format")
    return LookerStudioDataSourceParameter(alias=alias, key=key, value=raw_value)


def build_report_link(
    *,
    report_id: str,
    report_name: Optional[str] = None,
    page_id: Optional[str] = None,
    mode: Optional[str] = None,
    explain: bool = False,
    measurement_id: Optional[str] = None,
    keep_measurement_id: Optional[bool] = None,
    data_source_parameters: Optional[list[LookerStudioDataSourceParameter]] = None,
    embed: bool = False,
) -> LookerStudioReportLink:
    """Build a Looker Studio Linking API URL for a report."""
    if mode is not None and mode not in {"view", "edit"}:
        raise ValueError("Expected mode to be view or edit")

    raw_parameters: list[tuple[str, str]] = [("c.reportId", report_id)]
    if page_id is not None:
        raw_parameters.append(("c.pageId", page_id))
    if mode is not None:
        raw_parameters.append(("c.mode", mode))
    if explain:
        raw_parameters.append(("c.explain", "true"))
    if report_name is not None:
        raw_parameters.append(("r.reportName", report_name))
    if measurement_id is not None:
        raw_parameters.append(("r.measurementId", measurement_id))
    if keep_measurement_id is not None:
        raw_parameters.append(("r.keepMeasurementId", _format_link_value(keep_measurement_id)))

    for parameter in data_source_parameters or []:
        raw_parameters.append(
            (
                f"ds.{parameter.alias}.{parameter.key}",
                _format_link_value(parameter.value),
            )
        )

    base_url = REPORTING_EMBED_CREATE_URL if embed else REPORTING_CREATE_URL
    query = urlencode(raw_parameters)
    parameters = {key: value for key, value in raw_parameters}
    return LookerStudioReportLink(
        report_id=report_id,
        url=f"{base_url}?{query}",
        embed=embed,
        parameters=parameters,
    )


class LookerStudioClient:
    """Direct REST client for Looker Studio API."""

    def __init__(self, session, profile: Optional[str] = None):
        self.session = session
        self.profile = profile

    @classmethod
    def from_google_client(
        cls,
        google_client: GoogleClient,
        profile: Optional[str] = None,
    ) -> "LookerStudioClient":
        """Create a Looker Studio client from an authenticated Google client."""
        return cls(AuthorizedSession(google_client.creds), profile=profile)

    def _auth_login_command(self) -> str:
        command = "google auth login"
        if self.profile is not None:
            command += f" --profile {self.profile}"
        return f"{command} --force"

    def _enable_service_command(self, project: str) -> str:
        command = f"google cloud services enable datastudio.googleapis.com --project {project}"
        if self.profile is not None:
            command += f" --profile {self.profile}"
        return command

    def _disabled_service_project(self, error_payload: dict) -> Optional[str]:
        for detail in error_payload.get("error", {}).get("details", []):
            if detail.get("reason") != "SERVICE_DISABLED":
                continue
            metadata = detail.get("metadata", {})
            if metadata.get("service") != "datastudio.googleapis.com":
                continue
            consumer = metadata.get("consumer")
            if isinstance(consumer, str) and consumer.startswith("projects/"):
                return consumer.removeprefix("projects/")
        return None

    def _disabled_service_error(self, project: str) -> ClientError:
        return ClientError(
            f"Looker Studio API is disabled for Google Cloud project {project}. "
            f"Enable it with `{self._enable_service_command(project)}`, then retry."
        )

    def _workspace_admin_authorization_error(self, request_url: str) -> ClientError:
        return ClientError(
            "Looker Studio REST API is not authorized for this Google Workspace / Cloud Identity "
            f"environment. Google returned 403 Forbidden for {request_url}. "
            f"The OAuth token can still be valid and include {DATASTUDIO_SCOPE}. "
            "If this profile uses a personal Gmail account, authenticate with a Google Workspace "
            "or Cloud Identity account instead. "
            "Ask the Google Workspace admin to authorize the OAuth app/client for Looker Studio API "
            f"access and the datastudio scope, then rerun `{self._auth_login_command()}`."
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json_body: Optional[dict] = None,
    ) -> dict:
        url = f"{API_BASE_URL}{path}"
        request_kwargs = {}
        if params is not None:
            request_kwargs["params"] = params
        if json_body is not None:
            request_kwargs["json"] = json_body
        response = self.session.request(method, url, **request_kwargs)
        try:
            response.raise_for_status()
        except Exception as error:
            if response.status_code == 403:
                project = self._disabled_service_project(response.json())
                if project is not None:
                    raise self._disabled_service_error(project) from error
                raise self._workspace_admin_authorization_error(
                    getattr(response, "url", url)
                ) from error
            raise ClientError(f"Looker Studio API request failed: {error}") from error
        return response.json()

    def _search_report_page(
        self,
        *,
        title: Optional[str],
        owner: Optional[str],
        include_trashed: bool,
        order_by: Optional[str],
        page_size: int,
        page_token: Optional[str],
    ) -> dict:
        params = {
            "assetTypes": ["REPORT"],
            "includeTrashed": include_trashed,
            "pageSize": page_size,
        }
        if title is not None:
            params["title"] = title
        if owner is not None:
            params["owner"] = owner
        if order_by is not None:
            params["orderBy"] = order_by
        if page_token is not None:
            params["pageToken"] = page_token
        return self._request("GET", "/assets:search", params=params)

    def search_reports(
        self,
        *,
        title: Optional[str] = None,
        owner: Optional[str] = None,
        include_trashed: bool = False,
        order_by: Optional[str] = None,
        page_size: int = 1000,
        page_token: Optional[str] = None,
    ) -> list[LookerStudioAsset]:
        """Search Looker Studio report assets."""
        response = self._search_report_page(
            title=title,
            owner=owner,
            include_trashed=include_trashed,
            order_by=order_by,
            page_size=page_size,
            page_token=page_token,
        )
        return [LookerStudioAsset(**asset) for asset in response.get("assets", [])]

    def get_report(self, report_id: str) -> LookerStudioAsset:
        """Find an accessible report by exact report ID."""
        page_token = None
        while True:
            response = self._search_report_page(
                title=None,
                owner=None,
                include_trashed=False,
                order_by=None,
                page_size=1000,
                page_token=page_token,
            )
            for asset in response.get("assets", []):
                if asset["name"] == report_id:
                    return LookerStudioAsset(**asset)
            page_token = response.get("nextPageToken")
            if not page_token:
                raise ClientError(f"Report not found: {report_id}")

    def get_permissions(self, asset_name: str) -> LookerStudioPermissions:
        """Get permissions for a Looker Studio asset."""
        response = self._request("GET", f"/assets/{asset_name}/permissions")
        return LookerStudioPermissions(**response)

    def patch_permissions(self, asset_name: str, permissions: dict) -> LookerStudioPermissions:
        """Patch permissions for a Looker Studio asset."""
        response = self._request(
            "PATCH",
            f"/assets/{asset_name}/permissions",
            json_body={"permissions": permissions},
        )
        return LookerStudioPermissions(**response)

    def add_members(
        self,
        asset_name: str,
        role: LookerStudioRole,
        members: list[str],
    ) -> LookerStudioPermissions:
        """Add members to a Looker Studio asset permission role."""
        response = self._request(
            "POST",
            f"/assets/{asset_name}/permissions:addMembers",
            json_body={"role": role.value, "members": members},
        )
        return LookerStudioPermissions(**response)

    def revoke_all_permissions(
        self,
        asset_name: str,
        members: list[str],
    ) -> LookerStudioPermissions:
        """Revoke all permissions for members on a Looker Studio asset."""
        response = self._request(
            "POST",
            f"/assets/{asset_name}/permissions:revokeAllPermissions",
            json_body={"members": members},
        )
        return LookerStudioPermissions(**response)
