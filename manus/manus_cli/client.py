"""Manus AI API client."""
import sys
import time
from typing import Any, Dict, List, Optional
import requests
from .config import get_config

_RATE_LIMIT_DELAYS = [30, 60, 120, 240]


class ClientError(Exception):
    """Custom exception for client errors."""
    pass


class ManusClient:
    """Client for Manus AI API."""

    def __init__(self, profile=None):
        self.config = get_config(profile=profile)
        missing = self.config.get_missing_credentials()
        if missing:
            raise ClientError(f"Missing credentials: {', '.join(missing)}. Run 'manus auth login' to configure.")
        self.base_url = self.config.base_url
        self.headers = {
            "API_KEY": self.config.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make an HTTP request with exponential backoff retry on 429 rate limits.

        Args:
            method: HTTP method (get, post, etc.)
            url: Full URL to request
            **kwargs: Passed to requests.request()

        Returns:
            Response object

        Raises:
            ClientError: On non-429 HTTP errors or after exhausting retries
        """
        for attempt, delay in enumerate(_RATE_LIMIT_DELAYS):
            response = requests.request(method, url, **kwargs)
            if response.status_code != 429:
                return response
            print(
                f"Rate limit hit, retrying in {delay}s... (attempt {attempt + 1}/{len(_RATE_LIMIT_DELAYS)})",
                file=sys.stderr,
            )
            time.sleep(delay)

        # Final attempt after all retries
        response = requests.request(method, url, **kwargs)
        return response

    def create_task(
        self,
        prompt: str,
        agent_profile: str = "manus-1.5",
        task_mode: str = "agent",
        task_id: Optional[str] = None,
        attachments: Optional[List[Dict]] = None,
        connectors: Optional[List[str]] = None,
        hide_in_task_list: bool = False,
        create_shareable_link: bool = False,
        locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new Manus AI task.

        Args:
            prompt: The task instruction or query
            agent_profile: Agent profile to use (manus-1.5 or manus-1.5-lite)
            task_mode: Task execution mode (chat, adaptive, agent)
            task_id: For continuing existing tasks
            attachments: File/image attachments
            connectors: List of connector IDs to enable
            hide_in_task_list: Hide from webapp task list
            create_shareable_link: Generate public link
            locale: Locale setting (e.g., "en-US")

        Returns:
            Task creation response with task_id, task_url, etc.
        """
        payload = {
            "prompt": prompt,
            "agentProfile": agent_profile,
            "taskMode": task_mode,
        }

        if task_id:
            payload["taskId"] = task_id
        if attachments:
            payload["attachments"] = attachments
        if connectors:
            payload["connectors"] = connectors
        if hide_in_task_list:
            payload["hideInTaskList"] = True
        if create_shareable_link:
            payload["createShareableLink"] = True
        if locale:
            payload["locale"] = locale

        response = self._request(
            "POST",
            f"{self.base_url}/tasks",
            headers=self.headers,
            json=payload,
        )

        if response.status_code != 200:
            raise ClientError(f"Task creation failed ({response.status_code}): {response.text}")

        return response.json()

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """
        Get task status and result.

        Args:
            task_id: The task ID to retrieve

        Returns:
            Task details including status and response content
        """
        response = self._request(
            "GET",
            f"{self.base_url}/tasks/{task_id}",
            headers=self.headers,
        )

        if response.status_code != 200:
            raise ClientError(f"Task retrieval failed ({response.status_code}): {response.text}")

        return response.json()

    def list_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        List recent tasks.

        Args:
            limit: Maximum number of tasks to return

        Returns:
            List of task summaries
        """
        response = self._request(
            "GET",
            f"{self.base_url}/tasks",
            headers=self.headers,
            params={"limit": limit},
        )

        if response.status_code != 200:
            raise ClientError(f"Task list failed ({response.status_code}): {response.text}")

        return response.json()

    def wait_for_task(
        self,
        task_id: str,
        poll_interval: float = 2.0,
        max_wait: float = 300.0,
        status_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Wait for a task to complete.

        Args:
            task_id: The task ID to wait for
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait
            status_callback: Optional callback for status updates

        Returns:
            Completed task details
        """
        start_time = time.time()

        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                raise ClientError(f"Task {task_id} timed out after {max_wait} seconds")

            task = self.get_task(task_id)
            status = task.get("status", "unknown")

            if status_callback:
                status_callback(status, elapsed)

            if status == "completed":
                return task
            elif status in ("failed", "error", "cancelled"):
                raise ClientError(f"Task {task_id} ended with status: {status}")

            time.sleep(poll_interval)

    def create_and_wait(
        self,
        prompt: str,
        agent_profile: str = "manus-1.5",
        task_mode: str = "agent",
        task_id: Optional[str] = None,
        attachments: Optional[List[Dict]] = None,
        connectors: Optional[List[str]] = None,
        hide_in_task_list: bool = False,
        create_shareable_link: bool = False,
        locale: Optional[str] = None,
        poll_interval: float = 2.0,
        max_wait: float = 300.0,
        status_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Create a task and wait for completion.

        Args:
            prompt: The task instruction or query
            agent_profile: Agent profile to use
            task_mode: Task execution mode
            task_id: For continuing existing tasks
            attachments: File/image attachments
            connectors: List of connector IDs
            hide_in_task_list: Hide from webapp task list
            create_shareable_link: Generate public link
            locale: Locale setting
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait
            status_callback: Optional callback for status updates

        Returns:
            Completed task details
        """
        create_response = self.create_task(
            prompt=prompt,
            agent_profile=agent_profile,
            task_mode=task_mode,
            task_id=task_id,
            attachments=attachments,
            connectors=connectors,
            hide_in_task_list=hide_in_task_list,
            create_shareable_link=create_shareable_link,
            locale=locale,
        )

        new_task_id = create_response.get("task_id")
        if not new_task_id:
            raise ClientError("Task creation did not return a task_id")

        # Brief delay to allow task to be registered in the system
        # The Manus API has eventual consistency - task may not be
        # immediately available for retrieval after creation
        time.sleep(1.0)

        return self.wait_for_task(
            task_id=new_task_id,
            poll_interval=poll_interval,
            max_wait=max_wait,
            status_callback=status_callback,
        )


_client: Optional[ManusClient] = None


def get_client(profile=None) -> ManusClient:
    """Get or create the global client instance."""
    global _client
    if _client is None or profile is not None:
        _client = ManusClient(profile=profile)
    return _client
