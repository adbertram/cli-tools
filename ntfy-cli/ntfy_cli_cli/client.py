"""Safe subprocess boundary for official ntfy executable."""

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Sequence

from cli_tools_shared import ClientError
from cli_tools_shared.activity_log import get_activity_logger
from .commands.registry import COMMAND_REGISTRY, SENSITIVE_OPTIONS
from .config import Config, get_config
from .parsers import parse_ndjson, parse_publish

activity = get_activity_logger(Config.DIST_NAME)


SERVER_TABLE_SCHEMA = {
    "users": ("user", "role"),
    "access": ("user", "topic", "access"),
    "tokens": ("token", "user", "expires", "label"),
}


@dataclass(frozen=True)
class Result:
    stdout: str
    stderr: str
    returncode: int


class NtfyClient:
    """Run ntfy without owning its configuration or credentials."""

    SERVER_COMMANDS = {"serve", "user", "access", "token"}
    def __init__(self) -> None:
        self.config = get_config()

    @property
    def executable(self) -> str:
        path = self.config.get_cli_executable()
        if not shutil.which(path):
            raise ClientError("ntfy executable not found; install it with Homebrew or set CLI_PATH")
        return path

    def capabilities(self) -> set[str]:
        result = self.run(("--help",), timeout=10)
        return {
            name
            for name in self.SERVER_COMMANDS
            if re.search(rf"^[ \\t]+{re.escape(name)}[ \\t]{{2,}}", result.stdout, re.MULTILINE)
        }

    def require_server(self) -> None:
        if not self.SERVER_COMMANDS.intersection(self.capabilities()):
            raise ClientError("This ntfy build has no server commands. macOS packages support publish and subscribe only.")

    def run(self, args: Sequence[str], *, stdin: str | bytes | None = None, timeout: int | None = 60, check: bool = True) -> Result:
        command = [self.executable, *args]
        safe_args = []
        redact_next = False
        for item in args:
            if redact_next:
                safe_args.append("<redacted>")
                redact_next = False
            else:
                safe_args.append(item)
                redact_next = item in SENSITIVE_OPTIONS
        activity.info("upstream ntfy argv=%s", safe_args)
        try:
            completed = subprocess.run(command, input=stdin, text=isinstance(stdin, str) or stdin is None, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            activity.error("upstream ntfy timed out argv=%s", safe_args)
            raise ClientError(f"ntfy timed out after {timeout} seconds") from exc
        except OSError as exc:
            raise ClientError(f"Unable to run ntfy: {exc}") from exc
        result = Result(completed.stdout, completed.stderr, completed.returncode)
        activity.info("upstream ntfy exit=%s", result.returncode)
        if check and result.returncode:
            raise ClientError(result.stderr.strip() or result.stdout.strip() or "ntfy command failed")
        if result.returncode == 0 and result.stderr:
            sys.stderr.write(result.stderr)
        return result

    def publish(self, args: Sequence[str], body: str | None) -> dict:
        result = self.run((*COMMAND_REGISTRY["publish"]["argv"], *args), stdin=body)
        return parse_publish(result.stdout)

    def poll(self, args: Sequence[str]) -> list[dict]:
        result = self.run((*COMMAND_REGISTRY["poll"]["argv"], *args))
        return parse_ndjson(result.stdout)

    def passthrough(self, args: Iterable[str]) -> int:
        try:
            process = subprocess.Popen([self.executable, *args])
        except OSError as exc:
            raise ClientError(f"Unable to run ntfy: {exc}") from exc
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.terminate()
            process.wait()
            return 130


_client: NtfyClient | None = None


def get_client() -> NtfyClient:
    global _client
    if _client is None:
        _client = NtfyClient()
    return _client
