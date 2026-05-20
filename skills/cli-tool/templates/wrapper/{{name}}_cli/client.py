"""{{Name}} wrapper client using subprocess to call the underlying CLI."""

import fnmatch
import subprocess
from typing import Dict, List, Optional, Union

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .parsers import OutputFormat, parse_cli_output


def normalize_item(raw: dict) -> dict:
    """Map one parsed CLI record to the public wrapper output shape."""
    return {
        "id": raw["id"],
        "name": raw["name"],
        "status": raw["status"],
    }


def normalize_item_detail(raw: dict) -> dict:
    """Map one parsed CLI detail record to the public wrapper output shape."""
    return normalize_item(raw)


class {{Name}}Client:
    """Wrapper client for {{cli_command}} CLI."""

    def __init__(self):
        self.config = get_config()
        if not self.config.is_cli_available():
            raise ClientError(f"Underlying CLI '{self.config.cli_command}' not found.")

    def _run_command(
        self,
        args: List[str],
        input_text: Optional[str] = None,
        timeout: int = 60,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        cmd = [self.config.get_cli_executable()] + args
        try:
            result = subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ClientError(f"Command timed out after {timeout} seconds")
        except FileNotFoundError:
            raise ClientError(f"CLI '{self.config.cli_command}' not found in PATH")

        if check and result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "Command failed"
            raise ClientError(f"{self.config.cli_command} error: {message}")
        return result

    def _parse_output(self, output: str, format: OutputFormat = OutputFormat.AUTO) -> Union[Dict, List, str]:
        return parse_cli_output(output, format)

    def auth_login(self, **kwargs) -> Dict[str, object]:
        result = self._run_command(["login"], check=False)
        return {
            "success": result.returncode == 0,
            "message": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        }

    def auth_logout(self) -> Dict[str, object]:
        result = self._run_command(["logout"], check=False)
        return {
            "success": result.returncode == 0,
            "message": result.stdout.strip() if result.returncode == 0 else result.stderr.strip(),
        }

    def auth_status(self) -> Dict[str, object]:
        result = self._run_command(["status"], check=False)
        return {
            "authenticated": result.returncode == 0,
            "cli_command": self.config.cli_command,
            "cli_available": True,
            "cli_version": self.config.get_cli_version(),
            "output": result.stdout.strip() if result.returncode == 0 else None,
            "error": result.stderr.strip() if result.returncode != 0 else None,
        }

    def list_items(self, limit: int = 100) -> List[dict]:
        result = self._run_command(["ls"])
        raw_items = self._parse_output(result.stdout)
        if not isinstance(raw_items, list):
            raise ClientError("Expected list output from the underlying CLI parser.")
        return [normalize_item(raw) for raw in raw_items[:limit]]

    def get_item(self, item_id: str) -> dict:
        result = self._run_command(["show", item_id])
        raw_item = self._parse_output(result.stdout)
        if not isinstance(raw_item, dict):
            raise ClientError("Expected object output from the underlying CLI parser.")
        return normalize_item_detail(raw_item)

    def search_items(self, query: str, limit: int = 100) -> List[dict]:
        pattern = query.lower()
        if "*" not in pattern:
            pattern = f"*{pattern}*"
        results = []
        for item in self.list_items(limit=limit):
            if any(fnmatch.fnmatch(str(value).lower(), pattern) for value in item.values()):
                results.append(item)
        return results[:limit]


_client: Optional[{{Name}}Client] = None


def get_client() -> {{Name}}Client:
    """Get or create the global {{Name}} client instance."""
    global _client
    if _client is None:
        _client = {{Name}}Client()
    return _client
