"""Jira Cloud REST API client."""

import base64
import random
import re
import time
from typing import Any, Dict, List, Optional

import requests
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.token_manager import TokenManager

from .config import (
    OAUTH_3LO_AUTH_TYPE,
    SCOPED_API_TOKEN_AUTH_TYPE,
    SITE_BASIC_AUTH_TYPE,
    get_config,
)

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0
DEFAULT_JITTER = 0.1
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_FIELDS = [
    "summary",
    "status",
    "issuetype",
    "project",
    "assignee",
    "reporter",
    "priority",
    "created",
    "updated",
    "description",
    "labels",
]

JQL_FILTER_FIELDS = {
    "assignee": "assignee",
    "issue_type": "issuetype",
    "issuetype": "issuetype",
    "key": "key",
    "priority": "priority",
    "project": "project",
    "reporter": "reporter",
    "status": "status",
}

JQL_OPERATORS = {
    "eq": "=",
    "ne": "!=",
    "in": "in",
    "nin": "not in",
    "null": "is",
    "notnull": "is not",
}

ORDER_BY_RE = re.compile(r"\s+ORDER\s+BY\s+", re.IGNORECASE)
DEFAULT_TICKET_JQL = "updated >= -30d ORDER BY updated DESC"


def _display_name(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    return value.get("displayName") or value.get("name") or value.get("key")


def _field_name(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    return value.get("name") or value.get("key")


def _adf_plain_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return None

    def render(node: Any) -> str:
        if isinstance(node, list):
            rendered = [part for item in node if (part := render(item))]
            return "\n\n".join(rendered)
        if not isinstance(node, dict):
            return ""

        node_type = node.get("type")
        content = node.get("content") or []

        if node_type == "text":
            return node.get("text") or ""
        if node_type == "hardBreak":
            return "\n"
        if node_type in {"doc", "blockquote"}:
            rendered = [part for item in content if (part := render(item))]
            return "\n\n".join(rendered)
        if node_type in {"paragraph", "heading"}:
            return "".join(render(item) for item in content)
        if node_type == "listItem":
            rendered = [part for item in content if (part := render(item))]
            return "\n".join(rendered)
        if node_type in {"bulletList", "orderedList"}:
            items = []
            for index, item in enumerate(content, start=1):
                rendered_item = render(item).strip()
                if not rendered_item:
                    continue
                marker = f"{index}. " if node_type == "orderedList" else "- "
                items.append(f"{marker}{rendered_item.replace('\n', '\n  ')}")
            return "\n".join(items)
        return "".join(render(item) for item in content)

    text = render(value).strip()
    return text or None


def normalize_ticket(raw: dict) -> dict:
    """Map one Jira issue response to the CLI ticket record shape."""
    fields = raw.get("fields") or {}
    project = fields.get("project") or {}
    return {
        "id": raw.get("id"),
        "key": raw.get("key"),
        "summary": fields.get("summary"),
        "status": _field_name(fields.get("status")),
        "issue_type": _field_name(fields.get("issuetype")),
        "project": project.get("key") or project.get("name"),
        "project_name": project.get("name"),
        "assignee": _display_name(fields.get("assignee")) or "Unassigned",
        "reporter": _display_name(fields.get("reporter")),
        "priority": _field_name(fields.get("priority")),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "description": _adf_plain_text(fields.get("description")),
        "labels": fields.get("labels") or [],
        "self": raw.get("self"),
    }


def normalize_project(raw: dict) -> dict:
    """Map one Jira project response to the CLI project record shape."""
    category = raw.get("projectCategory") or {}
    insight = raw.get("insight") or {}
    return {
        "id": raw.get("id"),
        "key": raw.get("key"),
        "name": raw.get("name"),
        "project_type": raw.get("projectTypeKey"),
        "style": raw.get("style"),
        "simplified": raw.get("simplified"),
        "category": category.get("name"),
        "category_id": category.get("id"),
        "lead": _display_name(raw.get("lead")),
        "description": raw.get("description"),
        "url": raw.get("url"),
        "total_issue_count": insight.get("totalIssueCount"),
        "last_issue_update_time": insight.get("lastIssueUpdateTime"),
        "self": raw.get("self"),
    }


def adf_text(text: str) -> dict:
    """Return an Atlassian Document Format paragraph for plain text."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _quote_jql(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def filters_to_jql(filters: Optional[List[str]]) -> List[str]:
    """Convert supported shared filter syntax to Jira JQL clauses."""
    clauses: List[str] = []
    for filter_value in filters or []:
        for raw_part in filter_value.split(","):
            part = raw_part.strip()
            if not part:
                continue
            pieces = part.split(":", 2)
            if len(pieces) == 2:
                field, value = pieces
                op = "eq"
            elif len(pieces) == 3:
                field, op, value = pieces
            else:
                raise ClientError(f"Invalid filter: {part}")
            jira_field = JQL_FILTER_FIELDS.get(field)
            if jira_field is None:
                raise ClientError(
                    f"Unsupported Jira filter field: {field}. "
                    f"Supported fields: {', '.join(sorted(JQL_FILTER_FIELDS))}"
                )
            operator = JQL_OPERATORS.get(op)
            if operator is None:
                raise ClientError(
                    f"Unsupported Jira filter operator: {op}. "
                    f"Supported operators: {', '.join(sorted(JQL_OPERATORS))}"
                )
            if op in {"null", "notnull"}:
                clauses.append(f"{jira_field} {operator} EMPTY")
            elif op in {"in", "nin"}:
                values = [_quote_jql(item.strip()) for item in value.split("|") if item.strip()]
                if not values:
                    raise ClientError(f"Filter {part} must include at least one value")
                clauses.append(f"{jira_field} {operator} ({', '.join(values)})")
            else:
                clauses.append(f"{jira_field} {operator} {_quote_jql(value)}")
    return clauses


def combine_jql(jql: Optional[str], filters: Optional[List[str]]) -> str:
    """Combine raw JQL and structured filters into one bounded query."""
    raw_jql = (jql or "").strip()
    filter_clauses = filters_to_jql(filters)
    if not raw_jql and not filter_clauses:
        return DEFAULT_TICKET_JQL

    if not filter_clauses:
        return raw_jql

    order_by = "ORDER BY updated DESC"
    clauses = []
    if raw_jql:
        order_match = ORDER_BY_RE.search(raw_jql)
        if order_match:
            clauses.append(raw_jql[: order_match.start()].strip())
            order_by = raw_jql[order_match.start() :].strip()
        elif raw_jql.upper().startswith("ORDER BY "):
            order_by = raw_jql
        else:
            clauses.append(raw_jql)
    clauses.extend(filter_clauses)

    query = " AND ".join(
        f"({clause})" if " " in clause else clause
        for clause in clauses
    )
    return f"{query} {order_by}"


class JiraClient:
    """Client for interacting with Jira Cloud REST API v3."""

    def __init__(
        self,
        config=None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_BASE_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
        jitter: float = DEFAULT_JITTER,
    ):
        self.config = config or get_config()
        if not self.config.has_credentials():
            missing = self.config.get_missing_credentials()
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. "
                "Run 'jira auth login --profile <name>' for the active Jira auth type."
            )
        self.auth_type = self._validate_auth_type(self.config.auth_type)
        self.site_url = self._validate_site_url(self.config.base_url)
        self.base_url = self._resolve_api_base_url()
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.tokens = (
            TokenManager(self.config, on_refresh=self._update_headers)
            if self.auth_type == OAUTH_3LO_AUTH_TYPE
            else None
        )
        self._update_headers()

    def _validate_auth_type(self, auth_type: Optional[str]) -> str:
        if auth_type in {SITE_BASIC_AUTH_TYPE, OAUTH_3LO_AUTH_TYPE, SCOPED_API_TOKEN_AUTH_TYPE}:
            return str(auth_type)
        raise ClientError(
            "Jira auth profile is missing AUTH_TYPE. Recreate it with "
            "'jira auth profiles create <name> --auth-type ...'."
        )

    def _validate_site_url(self, base_url: str) -> str:
        normalized = (base_url or "").rstrip("/")
        if not normalized or "your-domain.atlassian.net" in normalized:
            raise ClientError(
                "BASE_URL must be set to your Jira Cloud site, for example "
                "https://example.atlassian.net."
            )
        if "/rest/api/" in normalized:
            raise ClientError("BASE_URL must be the Jira site root, not a /rest/api path.")
        return normalized

    def _resolve_api_base_url(self) -> str:
        if self.auth_type == SITE_BASIC_AUTH_TYPE:
            return self.site_url

        cloud_id = (self.config.cloud_id or "").strip()
        if not cloud_id:
            raise ClientError(
                "CLOUD_ID is required for Jira gateway auth. "
                "Use 'jira auth profiles create <name> --auth-type "
                f"{SCOPED_API_TOKEN_AUTH_TYPE} --auth-param CLOUD_ID=<cloud-id>' "
                "or complete OAuth login again so the CLI can store it."
            )
        return f"https://api.atlassian.com/ex/jira/{cloud_id}"

    def _basic_token(self) -> str:
        value = f"{self.config.username}:{self.config.password}".encode("utf-8")
        return base64.b64encode(value).decode("ascii")

    def _update_headers(self) -> None:
        authorization = (
            f"Bearer {self.config.access_token}"
            if self.auth_type == OAUTH_3LO_AUTH_TYPE
            else f"Basic {self._basic_token()}"
        )
        self.headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": authorization,
        }

    def _calculate_retry_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_delay)
        delay = self.base_delay * (2**attempt)
        jitter_range = delay * self.jitter
        return min(delay + random.uniform(-jitter_range, jitter_range), self.max_delay)

    def _get_retry_after(self, response: requests.Response) -> Optional[float]:
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def _extract_error_detail(self, response: requests.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict):
            messages = body.get("errorMessages")
            if isinstance(messages, list) and messages:
                return "; ".join(str(message) for message in messages)
            errors = body.get("errors")
            if isinstance(errors, dict) and errors:
                return "; ".join(f"{key}: {value}" for key, value in errors.items())
            if body.get("message"):
                return str(body["message"])
        return str(body)[:500]

    def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        retry: bool = True,
    ) -> Dict:
        url = f"{self.base_url}{endpoint}"
        last_exception: Optional[Exception] = None
        last_response: Optional[requests.Response] = None
        max_attempts = (self.max_retries + 1) if retry else 1

        if self.tokens is not None:
            self.tokens.ensure_valid()

        for attempt in range(max_attempts):
            try:
                response = requests.request(method, url, headers=self.headers, json=data, params=params)
                last_response = response
                if (
                    self.tokens is not None
                    and response.status_code == 401
                    and attempt < self.max_retries
                ):
                    self.tokens.force_refresh()
                    continue
                if retry and response.status_code in RETRYABLE_STATUS_CODES and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt, self._get_retry_after(response)))
                    continue
                break
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ) as exc:
                last_exception = exc
                if retry and attempt < self.max_retries:
                    time.sleep(self._calculate_retry_delay(attempt))
                    continue
                break

        if last_exception is not None and last_response is None:
            raise ClientError(f"Request failed after {attempt + 1} attempts: {last_exception}")
        if last_response is None:
            raise ClientError("Request failed: no response received")
        if not last_response.ok:
            raise ClientError(f"HTTP {last_response.status_code}: {self._extract_error_detail(last_response)}")
        if last_response.status_code == 204:
            return {}
        return last_response.json()

    def get_myself(self) -> dict:
        """Return the authenticated Jira user."""
        return self._make_request("GET", "/rest/api/3/myself")

    def list_tickets(
        self,
        *,
        limit: int = 100,
        jql: Optional[str] = None,
        filters: Optional[List[str]] = None,
        next_page_token: Optional[str] = None,
    ) -> List[dict]:
        """List tickets with Jira JQL enhanced search."""
        body: Dict[str, Any] = {
            "jql": combine_jql(jql, filters),
            "maxResults": limit,
            "fields": DEFAULT_FIELDS,
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token
        data = self._make_request("POST", "/rest/api/3/search/jql", data=body)
        return [normalize_ticket(issue) for issue in data.get("issues", [])]

    def get_ticket(self, issue_id_or_key: str) -> dict:
        """Get one Jira ticket by issue id or key."""
        params = {"fields": ",".join(DEFAULT_FIELDS)}
        return normalize_ticket(self._make_request("GET", f"/rest/api/3/issue/{issue_id_or_key}", params=params))

    def list_projects(
        self,
        *,
        limit: int = 100,
        query: Optional[str] = None,
    ) -> List[dict]:
        """List Jira projects visible to the caller."""
        params: Dict[str, Any] = {"maxResults": limit}
        if query:
            params["query"] = query
        data = self._make_request("GET", "/rest/api/3/project/search", params=params)
        return [normalize_project(project) for project in data.get("values", [])]

    def get_project(self, project_id_or_key: str) -> dict:
        """Get one Jira project by project id or key."""
        return normalize_project(self._make_request("GET", f"/rest/api/3/project/{project_id_or_key}"))

    def create_ticket(
        self,
        *,
        project: str,
        issue_type: str,
        summary: str,
        description: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> dict:
        """Create a Jira ticket and return the created ticket."""
        fields: Dict[str, Any] = {
            "project": {"key": project},
            "issuetype": {"name": issue_type},
            "summary": summary,
        }
        if description:
            fields["description"] = adf_text(description)
        if assignee:
            fields["assignee"] = {"id": assignee}
        if priority:
            fields["priority"] = {"name": priority}
        if labels:
            fields["labels"] = labels
        created = self._make_request("POST", "/rest/api/3/issue", data={"fields": fields})
        return self.get_ticket(created["key"])

    def update_ticket(
        self,
        issue_id_or_key: str,
        *,
        summary: Optional[str] = None,
        description: Optional[str] = None,
        assignee: Optional[str] = None,
        priority: Optional[str] = None,
        labels: Optional[List[str]] = None,
    ) -> dict:
        """Update mutable Jira ticket fields and return the updated ticket."""
        fields: Dict[str, Any] = {}
        if summary is not None:
            fields["summary"] = summary
        if description is not None:
            fields["description"] = adf_text(description)
        if assignee is not None:
            fields["assignee"] = {"id": assignee}
        if priority is not None:
            fields["priority"] = {"name": priority}
        if labels is not None:
            fields["labels"] = labels
        if not fields:
            raise ClientError("No ticket updates provided.")
        self._make_request("PUT", f"/rest/api/3/issue/{issue_id_or_key}", data={"fields": fields})
        return self.get_ticket(issue_id_or_key)

    def delete_ticket(self, issue_id_or_key: str, *, delete_subtasks: bool = False) -> dict:
        """Delete one Jira ticket by issue id or key."""
        params = {"deleteSubtasks": "true"} if delete_subtasks else None
        self._make_request(
            "DELETE",
            f"/rest/api/3/issue/{issue_id_or_key}",
            params=params,
            retry=False,
        )
        return {"key": issue_id_or_key, "deleted": True}

    def add_comment(self, issue_id_or_key: str, body: str) -> dict:
        """Add a comment to a Jira ticket."""
        return self._make_request(
            "POST",
            f"/rest/api/3/issue/{issue_id_or_key}/comment",
            data={"body": adf_text(body)},
        )

    def list_transitions(self, issue_id_or_key: str) -> List[dict]:
        """List available workflow transitions for a Jira ticket."""
        data = self._make_request("GET", f"/rest/api/3/issue/{issue_id_or_key}/transitions")
        transitions = []
        for transition in data.get("transitions", []):
            target = transition.get("to") or {}
            category = target.get("statusCategory") or {}
            transitions.append(
                {
                    "id": transition.get("id"),
                    "name": transition.get("name"),
                    "to_name": target.get("name"),
                    "status_category": category.get("name"),
                }
            )
        return transitions

    def transition_ticket(
        self,
        issue_id_or_key: str,
        transition_id: str,
        *,
        comment: Optional[str] = None,
    ) -> dict:
        """Apply a workflow transition and return the ticket."""
        body: Dict[str, Any] = {"transition": {"id": transition_id}}
        if comment:
            body["update"] = {"comment": [{"add": {"body": adf_text(comment)}}]}
        self._make_request("POST", f"/rest/api/3/issue/{issue_id_or_key}/transitions", data=body)
        return self.get_ticket(issue_id_or_key)


_client: Optional[JiraClient] = None


def get_client() -> JiraClient:
    """Get or create the global Jira client instance."""
    global _client
    if _client is None:
        _client = JiraClient()
    return _client
