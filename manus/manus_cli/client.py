"""Manus AI API client."""
import json
import sys
import time
from collections.abc import Callable
from typing import Any, Optional

import requests

from .config import get_config

_RATE_LIMIT_DELAYS = [30, 60, 120, 240]
_RETRYABLE_NOT_FOUND_WINDOW = 10.0


class ClientError(Exception):
    """Custom exception for client errors."""


class ManusClient:
    """Client for Manus AI API v2."""

    def __init__(self, profile: Optional[str] = None):
        self.config = get_config(profile=profile)
        missing = self.config.get_missing_credentials()
        if missing:
            raise ClientError(
                f"Missing credentials: {', '.join(missing)}. Run 'manus auth login' to configure."
            )
        self.base_url = self.config.base_url.rstrip("/")
        self.headers = {
            "x-manus-api-key": self.config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Make an HTTP request with exponential backoff retry on 429 rate limits."""
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        kwargs.setdefault("timeout", 60)
        for attempt, delay in enumerate(_RATE_LIMIT_DELAYS):
            response = requests.request(method, url, **kwargs)
            if response.status_code != 429:
                return response
            print(
                f"Rate limit hit, retrying in {delay}s... (attempt {attempt + 1}/{len(_RATE_LIMIT_DELAYS)})",
                file=sys.stderr,
            )
            time.sleep(delay)

        return requests.request(method, url, **kwargs)

    def _error_text(self, response: requests.Response) -> str:
        """Extract the most useful error text from a failed response."""
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip() or response.reason or "Unknown API error"

        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

        return json.dumps(payload, ensure_ascii=True)

    def _request_json(self, action: str, method: str, path: str, **kwargs) -> dict[str, Any]:
        """Make an API request and return parsed JSON."""
        response = self._request(method, path, headers=self.headers, **kwargs)
        if response.status_code != 200:
            raise ClientError(f"{action} failed ({response.status_code}): {self._error_text(response)}")

        try:
            return response.json()
        except ValueError as exc:
            raise ClientError(f"{action} returned invalid JSON: {exc}") from exc

    def create_task(
        self,
        message: dict[str, Any],
        agent_profile: str = "manus-1.6",
        project_id: Optional[str] = None,
        locale: Optional[str] = None,
        interactive_mode: bool = False,
        hide_in_task_list: bool = False,
        share_visibility: str = "private",
        title: Optional[str] = None,
        structured_output_schema: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Create a new Manus AI task."""
        payload: dict[str, Any] = {
            "message": message,
            "agent_profile": agent_profile,
            "interactive_mode": interactive_mode,
            "hide_in_task_list": hide_in_task_list,
            "share_visibility": share_visibility,
        }
        if project_id:
            payload["project_id"] = project_id
        if locale:
            payload["locale"] = locale
        if title:
            payload["title"] = title
        if structured_output_schema is not None:
            payload["structured_output_schema"] = structured_output_schema

        return self._request_json("Task creation", "POST", "/v2/task.create", json=payload)

    def get_task(self, task_id: str) -> dict[str, Any]:
        """Get task metadata and status."""
        payload = self._request_json("Task retrieval", "GET", "/v2/task.detail", params={"task_id": task_id})
        task = payload.get("task")
        if not isinstance(task, dict):
            raise ClientError("Task retrieval failed: API response did not include a task object")
        return task

    def list_tasks(
        self,
        limit: int = 10,
        cursor: Optional[str] = None,
        order: str = "desc",
        scope: Optional[str] = None,
        agent_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """List recent tasks."""
        params: dict[str, Any] = {"limit": limit, "order": order}
        if cursor:
            params["cursor"] = cursor
        if scope:
            params["scope"] = scope
        if agent_id:
            params["agent_id"] = agent_id
        if project_id:
            params["project_id"] = project_id

        return self._request_json("Task list", "GET", "/v2/task.list", params=params)

    def send_message(
        self,
        task_id: str,
        message: dict[str, Any],
        agent_profile: Optional[str] = None,
        structured_output_schema: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Send a follow-up message to a task."""
        payload: dict[str, Any] = {"task_id": task_id, "message": message}
        if agent_profile:
            payload["agent_profile"] = agent_profile
        if structured_output_schema is not None:
            payload["structured_output_schema"] = structured_output_schema

        return self._request_json("Task send message", "POST", "/v2/task.sendMessage", json=payload)

    def list_messages(
        self,
        task_id: str,
        limit: int = 50,
        cursor: Optional[str] = None,
        order: str = "desc",
        verbose: bool = False,
        slides_format: Optional[str] = None,
    ) -> dict[str, Any]:
        """List event messages for a task."""
        params: dict[str, Any] = {
            "task_id": task_id,
            "limit": limit,
            "order": order,
        }
        if cursor:
            params["cursor"] = cursor
        if verbose:
            params["verbose"] = "true"
        if slides_format:
            params["slides_format"] = slides_format

        return self._request_json("Task list messages", "GET", "/v2/task.listMessages", params=params)

    def update_task(
        self,
        task_id: str,
        title: Optional[str] = None,
        share_visibility: Optional[str] = None,
        visible_in_task_list: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Update a task's metadata."""
        payload: dict[str, Any] = {"task_id": task_id}
        if title is not None:
            payload["title"] = title
        if share_visibility is not None:
            payload["share_visibility"] = share_visibility
        if visible_in_task_list is not None:
            payload["enable_visible_in_task_list"] = visible_in_task_list

        return self._request_json("Task update", "POST", "/v2/task.update", json=payload)

    def stop_task(self, task_id: str) -> dict[str, Any]:
        """Stop a running task."""
        return self._request_json("Task stop", "POST", "/v2/task.stop", json={"task_id": task_id})

    def delete_task(self, task_id: str) -> dict[str, Any]:
        """Delete a task."""
        return self._request_json("Task delete", "POST", "/v2/task.delete", json={"task_id": task_id})

    def confirm_action(
        self,
        task_id: str,
        event_id: str,
        input_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Confirm a pending task action."""
        payload: dict[str, Any] = {"task_id": task_id, "event_id": event_id}
        if input_data is not None:
            payload["input"] = input_data

        return self._request_json("Task confirm action", "POST", "/v2/task.confirmAction", json=payload)

    @staticmethod
    def _find_latest_status_update(messages: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        for message in messages:
            if message.get("type") == "status_update" and isinstance(message.get("status_update"), dict):
                return message
        return None

    @staticmethod
    def _extract_task_error(task_id: str, messages: list[dict[str, Any]], latest_status: Optional[dict[str, Any]]) -> str:
        for message in messages:
            if message.get("type") == "error_message":
                error_message = message.get("error_message") or {}
                content = error_message.get("content")
                if content:
                    return f"Task {task_id} failed: {content}"

        if latest_status:
            status_update = latest_status.get("status_update") or {}
            brief = status_update.get("brief") or status_update.get("description")
            if brief:
                return f"Task {task_id} failed: {brief}"

        return f"Task {task_id} ended with status: error"

    @staticmethod
    def _is_not_found_error(error: ClientError) -> bool:
        return "(404)" in str(error) or " 404" in str(error)

    @staticmethod
    def _waiting_event_detail(latest_status: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """Return the confirmable-event detail when the agent is paused for user action.

        A genuine pause is a status_update with agent_status "waiting" whose
        status_detail identifies the event to respond to (waiting_for_event_id /
        waiting_for_event_type). A task that reports "waiting" without such an
        event (for example while queued before the agent starts running) is not
        actionable and must keep polling.
        """
        status_update = (latest_status or {}).get("status_update") or {}
        if status_update.get("agent_status") != "waiting":
            return None
        status_detail = status_update.get("status_detail") or {}
        if status_detail.get("waiting_for_event_id") or status_detail.get("waiting_for_event_type"):
            return status_detail
        return None

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: float = 2.0,
        max_wait: float = 300.0,
        status_callback: Optional[Callable[[str, float, Optional[dict[str, Any]]], None]] = None,
        verbose_messages: bool = False,
    ) -> dict[str, Any]:
        """Wait until a task stops, errors, or pauses for a confirmable user action."""
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                raise ClientError(f"Task {task_id} timed out after {max_wait} seconds")

            task: Optional[dict[str, Any]] = None
            try:
                task = self.get_task(task_id)
            except ClientError as exc:
                if not (elapsed < _RETRYABLE_NOT_FOUND_WINDOW and self._is_not_found_error(exc)):
                    raise

            try:
                messages_payload = self.list_messages(
                    task_id=task_id,
                    limit=100,
                    order="desc",
                    verbose=verbose_messages,
                )
                messages = messages_payload.get("messages", [])
            except ClientError as exc:
                if elapsed < _RETRYABLE_NOT_FOUND_WINDOW and self._is_not_found_error(exc):
                    time.sleep(poll_interval)
                    continue
                raise

            latest_status = self._find_latest_status_update(messages)
            status = (
                (latest_status or {}).get("status_update", {}).get("agent_status")
                or (task or {}).get("status")
                or "running"
            )

            if status_callback:
                status_callback(status, elapsed, latest_status)

            # "waiting" is non-terminal unless the agent emitted a confirmable
            # event (interactive question or action confirmation). Newly created
            # tasks can report "waiting" before the agent starts running; that
            # state resolves on its own and must not end the wait.
            paused_for_user = status == "waiting" and self._waiting_event_detail(latest_status) is not None

            if status == "stopped" or paused_for_user:
                if task is None:
                    task = self.get_task(task_id)
                return {
                    "task": task,
                    "messages": messages,
                    "latest_status": latest_status,
                }

            if status == "error":
                raise ClientError(self._extract_task_error(task_id, messages, latest_status))

            time.sleep(poll_interval)

    def create_and_wait(
        self,
        message: dict[str, Any],
        agent_profile: str = "manus-1.6",
        project_id: Optional[str] = None,
        locale: Optional[str] = None,
        interactive_mode: bool = False,
        hide_in_task_list: bool = False,
        share_visibility: str = "private",
        title: Optional[str] = None,
        structured_output_schema: Optional[dict[str, Any]] = None,
        poll_interval: float = 2.0,
        max_wait: float = 300.0,
        status_callback: Optional[Callable[[str, float, Optional[dict[str, Any]]], None]] = None,
        verbose_messages: bool = False,
    ) -> dict[str, Any]:
        """Create a task and wait for completion state."""
        create_response = self.create_task(
            message=message,
            agent_profile=agent_profile,
            project_id=project_id,
            locale=locale,
            interactive_mode=interactive_mode,
            hide_in_task_list=hide_in_task_list,
            share_visibility=share_visibility,
            title=title,
            structured_output_schema=structured_output_schema,
        )

        new_task_id = create_response.get("task_id")
        if not new_task_id:
            raise ClientError("Task creation did not return a task_id")

        time.sleep(1.0)
        result = self.wait_for_task(
            task_id=new_task_id,
            poll_interval=poll_interval,
            max_wait=max_wait,
            status_callback=status_callback,
            verbose_messages=verbose_messages,
        )
        result["create_response"] = create_response
        return result

    def send_and_wait(
        self,
        task_id: str,
        message: dict[str, Any],
        agent_profile: Optional[str] = None,
        structured_output_schema: Optional[dict[str, Any]] = None,
        poll_interval: float = 2.0,
        max_wait: float = 300.0,
        status_callback: Optional[Callable[[str, float, Optional[dict[str, Any]]], None]] = None,
        verbose_messages: bool = False,
    ) -> dict[str, Any]:
        """Send a task message and wait for completion state."""
        send_response = self.send_message(
            task_id=task_id,
            message=message,
            agent_profile=agent_profile,
            structured_output_schema=structured_output_schema,
        )
        time.sleep(1.0)
        result = self.wait_for_task(
            task_id=task_id,
            poll_interval=poll_interval,
            max_wait=max_wait,
            status_callback=status_callback,
            verbose_messages=verbose_messages,
        )
        result["send_response"] = send_response
        return result


_client: Optional[ManusClient] = None


def get_client(profile=None) -> ManusClient:
    """Get or create the global client instance."""
    global _client
    if _client is None or profile is not None:
        _client = ManusClient(profile=profile)
    return _client
