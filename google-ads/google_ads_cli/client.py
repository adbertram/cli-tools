"""Complete SDK gateway. Read-only retries; mutations never replay automatically."""
import json
import math

from google.ads.googleads.client import GoogleAdsClient as SDKClient
from google.ads.googleads.errors import GoogleAdsException
from google.oauth2.credentials import Credentials
from google.api_core.exceptions import GoogleAPICallError, TooManyRequests, ServerError
from google.api_core.retry import Retry, if_exception_type
from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.exceptions import ClientError, CredentialError
from cli_tools_shared.token_manager import TokenManager

from .config import get_config
from .schema import DEFAULT_API_VERSION, method_info, request_message, to_dict

logger = get_activity_logger("google-ads")
def retryable_read_error(exc):
    """Retry transient SDK errors; never retry authentication or invalid requests."""
    if isinstance(exc, GoogleAdsException):
        return exc.error.code().name in {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"}
    return if_exception_type(TooManyRequests, ServerError)(exc)


READ_RETRY = Retry(predicate=retryable_read_error, initial=1.0, multiplier=2.0, maximum=30.0, timeout=120.0)


class GoogleAdsClient:
    def __init__(self, config=None, version=DEFAULT_API_VERSION, sdk=None):
        self.config = config
        self.version = version
        self._sdk = sdk

    def _client(self):
        if self._sdk is None:
            self.config = self.config or get_config()
            if not self.config.has_credentials():
                raise CredentialError("Missing Google Ads OAuth credentials. Run 'google-ads auth login'.")
            TokenManager(self.config).ensure_valid()
            credentials = Credentials(token=self.config.access_token, refresh_token=self.config.refresh_token,
                                      token_uri=self.config.OAUTH_TOKEN_URL, client_id=self.config.client_id,
                                      client_secret=self.config.client_secret, scopes=self.config.OAUTH_SCOPES)
            self._sdk = SDKClient(credentials=credentials, version=self.version, use_proto_plus=True,
                                  login_customer_id=self.config._get("LOGIN_CUSTOMER_ID"),
                                  linked_customer_id=self.config._get("LINKED_CUSTOMER_ID"))
        return self._sdk

    def call(self, service, method, body, *, yes=False, dry_run=False, validate_only=False,
             all_pages=False, stream=False, timeout=60.0):
        info = method_info(service, method, self.version)
        if not isinstance(body, dict):
            raise ClientError("Request JSON must be an object.")
        body = dict(body)
        if validate_only:
            from .schema import protobuf_class
            if "validate_only" not in protobuf_class(info["request_class"]).DESCRIPTOR.fields_by_name:
                raise ClientError(f"{service}.{method} does not support validate_only.")
            body.pop("validateOnly", None)
            body["validate_only"] = True
        request = request_message(service, method, body, self.version)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ClientError("Timeout must be finite and greater than zero.")
        if all_pages and not info["paged"]:
            raise ClientError(f"{service}.{method} is not paginated.")
        if stream and not info["stream"]:
            raise ClientError(f"{service}.{method} is not server-streaming.")
        if dry_run:
            return {"api_version": self.version, "service": service, "method": method, "request": to_dict(request),
                    "read_only": info["read_only"], "timeout": timeout, "all_pages": all_pages}
        # JSON-specified validate_only is as safe as the flag, after strict schema parsing.
        validation = bool(getattr(request, "validate_only", False))
        if not info["read_only"] and not yes and not validation:
            raise ClientError("Refusing to change Google Ads without --yes, --validate-only, or --dry-run.")
        logger.info("RPC %s.%s version=%s validate_only=%s", service, method, self.version, validation)
        try:
            if info.get("operations"):
                operations = self._client().get_service("BatchJobService", version=self.version).transport.operations_client
                rpc = getattr(operations, "_" + method)
                response = rpc(request, retry=READ_RETRY if info["read_only"] else None, timeout=timeout)
                if all_pages:
                    pages = [self._checked_dict(response)]
                    seen = {request.page_token} if request.page_token else set()
                    while response.next_page_token:
                        if response.next_page_token in seen:
                            raise ClientError("Operations pagination returned a repeated page token.")
                        seen.add(response.next_page_token)
                        request.page_token = response.next_page_token
                        response = rpc(request, retry=READ_RETRY, timeout=timeout)
                        pages.append(self._checked_dict(response))
                    return {"pages": pages}
                return self._checked_dict(response)
            response = getattr(self._client().get_service(service, version=self.version), method)(
                request=request, retry=READ_RETRY if info["read_only"] or validation else None, timeout=timeout)
            if info["stream"]:
                return self._stream_responses(response)
            if info["paged"]:
                if all_pages:
                    return {"pages": self._collect_pages(response.pages, request.page_token)}
                return self._checked_dict(response._response)
            return self._checked_dict(response)
        except (GoogleAdsException, GoogleAPICallError) as exc:
            raise self._api_error(exc) from exc

    def _collect_pages(self, pages, initial_token=""):
        """Reject pagination cycles before asking the SDK pager for another page."""
        seen = {initial_token} if initial_token else set()
        result = []
        for page in pages:
            result.append(self._checked_dict(page))
            token = page.next_page_token
            if token:
                if token in seen:
                    raise ClientError("Google Ads pagination returned a repeated page token.")
                seen.add(token)
        return result

    def _stream_responses(self, responses):
        try:
            for response in responses:
                yield self._checked_dict(response)
        except (GoogleAdsException, GoogleAPICallError) as exc:
            raise self._api_error(exc) from exc

    @staticmethod
    def _checked_dict(response):
        result = to_dict(response)
        # Preserve the complete partial-failure response and make failure explicit.
        failure = result.get("partial_failure_error")
        if failure and failure.get("code", 0):
            raise ClientError(json.dumps({"error": "partial_failure", "response": result}, ensure_ascii=False))
        return result

    @staticmethod
    def _api_error(exc):
        if isinstance(exc, GoogleAdsException):
            return ClientError(json.dumps({"request_id": exc.request_id, "failure": to_dict(exc.failure)}, ensure_ascii=False))
        return ClientError(f"Google Ads API request failed: {exc}")


def get_client(version=DEFAULT_API_VERSION):
    return GoogleAdsClient(version=version)
