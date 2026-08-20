"""{{Name}} wrapper client using subprocess to call the underlying CLI."""

import subprocess
from typing import List, Optional

from cli_tools_shared.exceptions import ClientError

from .config import get_config


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

    def list_items(self, limit: int = 100) -> List[dict]:
        raise NotImplementedError(
            "Implement list_items() with the wrapped CLI's real list command and normalize the parsed records."
        )

    def get_item(self, item_id: str) -> dict:
        raise NotImplementedError(
            "Implement get_item() with the wrapped CLI's real detail command and normalize the parsed record."
        )

    def search_items(self, query: str, limit: int = 100) -> List[dict]:
        raise NotImplementedError(
            "Implement search_items() with the wrapped CLI's real search flow or delegate to list_items() "
            "plus deterministic client-side filtering."
        )


_client: Optional[{{Name}}Client] = None


def get_client() -> {{Name}}Client:
    """Get or create the global {{Name}} client instance."""
    global _client
    if _client is None:
        _client = {{Name}}Client()
    return _client
