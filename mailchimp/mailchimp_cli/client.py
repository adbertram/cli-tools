"""Mailchimp API client with automatic token management."""
from datetime import datetime
from typing import Dict, List, Optional, Any
import requests

from cli_tools_shared.filters import validate_filters, FilterValidationError

from .config import get_config


class ClientError(Exception):
    """Custom exception for Mailchimp API errors."""
    pass


class MailchimpClient:
    """Client for interacting with Mailchimp API with automatic token management."""

    def __init__(self, config=None):
        """Initialize Mailchimp client from configuration."""
        self.config = config or get_config()

        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'mailchimp auth login' to authenticate."
            )

        # Extract data center from API key (format: key-dc)
        api_key = self.config.api_key or self.config.access_token
        if api_key and '-' in api_key:
            dc = api_key.split('-')[-1]
            self.base_url = f"https://{dc}.api.mailchimp.com/3.0"
        else:
            self.base_url = self.config.base_url

        self._update_headers()

    def _update_headers(self):
        """Update request headers with current credentials."""
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Mailchimp uses HTTP Basic Auth with 'anystring' as username and API key as password
        # We'll use requests.auth.HTTPBasicAuth instead of setting header directly
        self.auth = None
        if self.config.api_key:
            import requests.auth
            self.auth = requests.auth.HTTPBasicAuth('anystring', self.config.api_key)
        elif self.config.access_token:
            self.headers["Authorization"] = f"Bearer {self.config.access_token}"

    def _is_token_expired(self) -> bool:
        """Check if access token is expired or about to expire."""
        expires_at = self.config.token_expires_at
        if not expires_at:
            return False  # No expiry tracking, assume valid

        try:
            expires_timestamp = float(expires_at)
            # Consider expired if less than 5 minutes remaining
            return datetime.now().timestamp() > (expires_timestamp - 300)
        except (ValueError, TypeError):
            return False

    def _refresh_token(self):
        """Refresh the access token using the refresh token."""
        refresh_token = self.config.refresh_token
        if not refresh_token:
            raise ClientError(
                "No refresh token available. Run 'mailchimp auth login' to re-authenticate."
            )

        # TODO: Implement token refresh for your specific API
        # token_url = f"{self.base_url}/oauth/token"
        # response = requests.post(token_url, data={...})
        # self.config.save_tokens(new_access, new_refresh, expires_at)
        # self._update_headers()
        raise ClientError("Token refresh not implemented. Run 'mailchimp auth login'.")

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Dict:
        """
        Make an HTTP request to the Mailchimp API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            endpoint: API endpoint path (e.g., "/users")
            data: Request body data
            params: Query parameters

        Returns:
            Response JSON data

        Raises:
            ClientError: If request fails
        """
        url = f"{self.base_url}{endpoint}"

        # Check if token needs refresh
        if self._is_token_expired():
            try:
                self._refresh_token()
            except Exception:
                pass  # Try with existing token

        # Make the request
        response = requests.request(
            method=method,
            url=url,
            headers=self.headers,
            auth=self.auth,
            json=data,
            params=params,
        )

        # If 401, try refreshing token and retry (for OAuth)
        if response.status_code == 401 and self.config.access_token:
            try:
                self._refresh_token()
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    auth=self.auth,
                    json=data,
                    params=params,
                )
            except Exception as e:
                raise ClientError(f"Authentication failed: {e}")

        if not response.ok:
            # Try to get error details from response
            try:
                error_data = response.json()
                error_msg = error_data.get("message") or error_data.get("error") or response.text
            except Exception:
                error_msg = response.text
            raise ClientError(f"API request failed ({response.status_code}): {error_msg}")

        # Handle empty response (204 No Content)
        if response.status_code == 204:
            return {}

        return response.json()

    # ==================== API Methods ====================

    # Lists/Audiences
    def list_audiences(self, count: int = 10, offset: int = 0, **kwargs) -> Dict:
        """
        Get all lists/audiences in the account.

        Args:
            count: Number of records to return
            offset: Number of records to skip
            **kwargs: Additional query parameters

        Returns:
            Response with lists
        """
        params = {"count": count, "offset": offset, **kwargs}
        return self._make_request("GET", "/lists", params=params)

    def get_audience(self, list_id: str, **kwargs) -> Dict:
        """
        Get information about a specific list/audience.

        Args:
            list_id: The unique ID for the list
            **kwargs: Additional query parameters

        Returns:
            List details
        """
        params = kwargs if kwargs else None
        return self._make_request("GET", f"/lists/{list_id}", params=params)

    def create_audience(self, data: Dict) -> Dict:
        """
        Create a new list/audience.

        Args:
            data: List configuration data

        Returns:
            Created list details
        """
        return self._make_request("POST", "/lists", data=data)

    # Signup Forms
    def list_signup_forms(self, list_id: str) -> List[Dict]:
        """
        Get signup forms for a specific list.

        Args:
            list_id: The unique ID for the list

        Returns:
            Signup forms for the list
        """
        response = self._make_request("GET", f"/lists/{list_id}/signup-forms")
        return response["signup_forms"]

    def list_all_signup_forms(self, count: int) -> List[Dict]:
        """
        Get signup forms for audiences in the account.

        Args:
            count: Maximum number of audiences to inspect

        Returns:
            Signup forms for the account audiences
        """
        response = self.list_audiences(count=count, offset=0)
        forms = []
        for audience in response["lists"]:
            forms.extend(self.list_signup_forms(audience["id"]))
        return forms

    def get_signup_form(self, list_id: str) -> Dict:
        """
        Get the default signup form for a specific list.

        Args:
            list_id: The unique ID for the list

        Returns:
            The default signup form for the list
        """
        forms = self.list_signup_forms(list_id)
        if len(forms) != 1:
            raise ClientError(f"Expected exactly one signup form, got {len(forms)}")
        return forms[0]

    def customize_signup_form(
        self,
        list_id: str,
        header_text: str,
        signup_message: str,
        signup_thank_you_title: str,
    ) -> Dict:
        """
        Customize a list's default signup form.

        Args:
            list_id: The unique ID for the list
            header_text: Header text for the signup form
            signup_message: Signup message body content
            signup_thank_you_title: Thank-you page title

        Returns:
            Customized signup form
        """
        data = {
            "header": {"text": header_text},
            "contents": [
                {"section": "signup_message", "value": signup_message},
                {
                    "section": "signup_thank_you_title",
                    "value": signup_thank_you_title,
                },
            ],
        }

        return self._make_request("POST", f"/lists/{list_id}/signup-forms", data=data)

    # Members/Subscribers
    def list_members(self, list_id: str, count: int = 10, offset: int = 0, **kwargs) -> Dict:
        """
        Get members of a specific list.

        Args:
            list_id: The unique ID for the list
            count: Number of records to return
            offset: Number of records to skip
            **kwargs: Additional query parameters (status, etc.)

        Returns:
            Response with members
        """
        params = {"count": count, "offset": offset, **kwargs}
        return self._make_request("GET", f"/lists/{list_id}/members", params=params)

    def get_member(self, list_id: str, subscriber_hash: str) -> Dict:
        """
        Get information about a specific list member.

        Args:
            list_id: The unique ID for the list
            subscriber_hash: The MD5 hash of the lowercase email address

        Returns:
            Member details
        """
        return self._make_request("GET", f"/lists/{list_id}/members/{subscriber_hash}")

    def add_member(self, list_id: str, data: Dict) -> Dict:
        """
        Add a new member to a list.

        Args:
            list_id: The unique ID for the list
            data: Member data (email_address, status, merge_fields, etc.)

        Returns:
            Created member details
        """
        return self._make_request("POST", f"/lists/{list_id}/members", data=data)

    def update_member(self, list_id: str, subscriber_hash: str, data: Dict) -> Dict:
        """
        Update a list member.

        Args:
            list_id: The unique ID for the list
            subscriber_hash: The MD5 hash of the lowercase email address
            data: Updated member data

        Returns:
            Updated member details
        """
        return self._make_request("PATCH", f"/lists/{list_id}/members/{subscriber_hash}", data=data)

    def delete_member(self, list_id: str, subscriber_hash: str) -> Dict:
        """
        Remove a member from a list.

        Args:
            list_id: The unique ID for the list
            subscriber_hash: The MD5 hash of the lowercase email address

        Returns:
            Empty response on success
        """
        return self._make_request("DELETE", f"/lists/{list_id}/members/{subscriber_hash}")

    def search_members(self, query: str, list_id: Optional[str] = None) -> Dict:
        """
        Search for list members by email address.

        Args:
            query: The search query (email address)
            list_id: Optional list ID to search within

        Returns:
            Search results
        """
        params = {"query": query}
        if list_id:
            params["list_id"] = list_id
        return self._make_request("GET", "/search-members", params=params)

    # Campaigns
    def list_campaigns(self, count: int = 10, offset: int = 0, **kwargs) -> Dict:
        """
        Get all campaigns in the account.

        Args:
            count: Number of records to return
            offset: Number of records to skip
            **kwargs: Additional query parameters (status, type, etc.)

        Returns:
            Response with campaigns
        """
        params = {"count": count, "offset": offset, **kwargs}
        return self._make_request("GET", "/campaigns", params=params)

    def get_campaign(self, campaign_id: str) -> Dict:
        """
        Get information about a specific campaign.

        Args:
            campaign_id: The unique ID for the campaign

        Returns:
            Campaign details
        """
        return self._make_request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, data: Dict) -> Dict:
        """
        Create a new campaign.

        Args:
            data: Campaign configuration data

        Returns:
            Created campaign details
        """
        return self._make_request("POST", "/campaigns", data=data)

    def send_campaign(self, campaign_id: str) -> Dict:
        """
        Send a campaign.

        Args:
            campaign_id: The unique ID for the campaign

        Returns:
            Send confirmation
        """
        return self._make_request("POST", f"/campaigns/{campaign_id}/actions/send")

    def pause_rss_campaign(self, campaign_id: str) -> Dict:
        """
        Pause an RSS-Driven campaign.

        Args:
            campaign_id: The unique ID for the RSS campaign

        Returns:
            Empty response on success
        """
        return self._make_request("POST", f"/campaigns/{campaign_id}/actions/pause")

    def resume_rss_campaign(self, campaign_id: str) -> Dict:
        """
        Resume a paused RSS-Driven campaign.

        Args:
            campaign_id: The unique ID for the RSS campaign

        Returns:
            Empty response on success
        """
        return self._make_request("POST", f"/campaigns/{campaign_id}/actions/resume")

    def get_campaign_report(self, campaign_id: str) -> Dict:
        """
        Get report for a specific campaign.

        Args:
            campaign_id: The unique ID for the campaign

        Returns:
            Campaign report
        """
        return self._make_request("GET", f"/reports/{campaign_id}")

    def get_campaign_sub_reports(self, campaign_id: str, count: int = 100, offset: int = 0) -> Dict:
        """
        Get sub-reports for child campaigns of an RSS, A/B test, or multivariate campaign.

        Args:
            campaign_id: The unique ID for the parent campaign
            count: Number of records to return
            offset: Number of records to skip

        Returns:
            Response with child campaign reports
        """
        params = {"count": count, "offset": offset}
        return self._make_request("GET", f"/reports/{campaign_id}/sub-reports", params=params)

    def get_campaign_content(self, campaign_id: str) -> Dict:
        """
        Get the content (HTML, plain text, archive URL) for a specific campaign.

        Args:
            campaign_id: The unique ID for the campaign

        Returns:
            Campaign content including html, plain_text, and archive_html
        """
        return self._make_request("GET", f"/campaigns/{campaign_id}/content")

    # Templates
    def list_templates(self, count: int = 10, offset: int = 0, **kwargs) -> Dict:
        """
        Get all templates.

        Args:
            count: Number of records to return
            offset: Number of records to skip
            **kwargs: Additional query parameters

        Returns:
            Response with templates
        """
        params = {"count": count, "offset": offset, **kwargs}
        return self._make_request("GET", "/templates", params=params)

    def get_template(self, template_id: str) -> Dict:
        """
        Get information about a specific template.

        Args:
            template_id: The unique ID for the template

        Returns:
            Template details
        """
        return self._make_request("GET", f"/templates/{template_id}")

    # Account/Root
    def get_account(self) -> Dict:
        """
        Get account information.

        Returns:
            Account details
        """
        return self._make_request("GET", "/")


# Module-level client instance - singleton pattern
_client: Optional[MailchimpClient] = None


def get_client() -> MailchimpClient:
    """Get or create the global Mailchimp client instance."""
    global _client
    if _client is None:
        _client = MailchimpClient()
    return _client
