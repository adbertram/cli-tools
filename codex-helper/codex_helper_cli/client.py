"""Client for Codex local app-server JSON-RPC methods."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any, Optional

from cli_tools_shared.exceptions import ClientError

from .config import get_config


def _local_timestamp(epoch_seconds: Any) -> Optional[str]:
    if epoch_seconds is None:
        return None
    return datetime.fromtimestamp(epoch_seconds).astimezone().isoformat(timespec="seconds")


def _limit_window(raw: Optional[dict]) -> Optional[dict]:
    if raw is None:
        return None
    used_percent = raw.get("usedPercent")
    if used_percent is None:
        used_percent = raw.get("used_percent")
    resets_at = raw.get("resetsAt")
    if resets_at is None:
        resets_at = raw.get("resets_at")
    return {
        "used_percent": used_percent,
        "left_percent": None if used_percent is None else max(0, 100 - used_percent),
        "window_duration_mins": raw.get("windowDurationMins") or raw.get("window_duration_mins"),
        "resets_at": resets_at,
        "resets_at_local": _local_timestamp(resets_at),
    }


def _limit_record(limit_id: str, raw: dict, account_plan_type: Optional[str]) -> dict:
    return {
        "limit_id": limit_id,
        "limit_name": raw.get("limitName") or raw.get("limit_name"),
        "plan_type": raw.get("planType") or raw.get("plan_type") or account_plan_type,
        "primary": _limit_window(raw.get("primary")),
        "secondary": _limit_window(raw.get("secondary")),
        "rate_limit_reached_type": raw.get("rateLimitReachedType")
        or raw.get("rate_limit_reached_type"),
    }


def normalize_usage(account_result: dict, rate_limits_result: dict) -> dict:
    """Normalize Codex app-server account and rate-limit payloads."""
    account_raw = account_result.get("account") or account_result
    plan_type = account_raw.get("planType") or account_raw.get("plan_type")
    rate_limits = rate_limits_result["rateLimits"]

    limits = [_limit_record("codex", rate_limits, plan_type)]
    for limit_id, limit_raw in sorted((rate_limits_result.get("rateLimitsByLimitId") or {}).items()):
        if limit_id == "codex":
            continue
        limits.append(_limit_record(limit_id, limit_raw, plan_type))

    credits_raw = rate_limits_result.get("credits") or {}
    reset_credits_raw = rate_limits_result.get("rateLimitResetCredits") or {}
    return {
        "account": {
            "email": account_raw.get("email"),
            "plan_type": plan_type,
        },
        "limits": limits,
        "credits": {
            "has_credits": credits_raw.get("hasCredits") or credits_raw.get("has_credits") or False,
            "unlimited": credits_raw.get("unlimited") or False,
            "balance": str(credits_raw.get("balance", "0")),
        },
        "rate_limit_reset_credits": {
            "available_count": reset_credits_raw.get("availableCount")
            or reset_credits_raw.get("available_count")
            or 0,
        },
    }


class CodexHelperClient:
    """Wrapper client for Codex app-server."""

    def __init__(self):
        self.config = get_config()
        if not self.config.is_cli_available():
            raise ClientError(f"Underlying CLI '{self.config.cli_command}' not found.")

    def read_usage(self, timeout: int = 30) -> dict:
        """Read account and rate-limit usage from Codex app-server."""
        responses = self._json_rpc(
            [
                {
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "clientInfo": {
                            "name": "codex-helper",
                            "version": "0.1.0",
                        }
                    },
                },
                {"method": "initialized", "params": {}},
                {"id": 2, "method": "account/rateLimits/read", "params": {}},
                {"id": 3, "method": "account/read", "params": {}},
            ],
            response_ids={2, 3},
            timeout=timeout,
        )
        return normalize_usage(
            account_result=responses[3],
            rate_limits_result=responses[2],
        )

    def _json_rpc(self, requests: list[dict], response_ids: set[int], timeout: int) -> dict[int, dict]:
        cmd = [self.config.get_cli_executable(), "-s", "read-only", "-a", "untrusted", "app-server"]
        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ClientError(f"CLI '{self.config.cli_command}' not found in PATH") from exc

        assert process.stdin is not None
        assert process.stdout is not None

        for request in requests:
            process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            process.stdin.flush()

        results: dict[int, dict] = {}
        while response_ids - results.keys():
            line = process.stdout.readline()
            if not line:
                break
            payload = json.loads(line)
            response_id = payload.get("id")
            if response_id not in response_ids:
                continue
            if "error" in payload:
                raise ClientError(f"Codex app-server error for id {response_id}: {payload['error']}")
            results[response_id] = payload["result"]

        process.stdin.close()
        try:
            stderr = process.stderr.read() if process.stderr is not None else ""
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            raise ClientError(f"Codex app-server timed out after {timeout} seconds")

        if process.returncode not in (0, None):
            message = stderr.strip() or "Codex app-server exited with an error"
            raise ClientError(message)
        missing_ids = response_ids - results.keys()
        if missing_ids:
            raise ClientError(f"Codex app-server response missing ids: {sorted(missing_ids)}")
        return results


_client: Optional[CodexHelperClient] = None


def get_client() -> CodexHelperClient:
    """Get or create the global CodexHelper client instance."""
    global _client
    if _client is None:
        _client = CodexHelperClient()
    return _client
