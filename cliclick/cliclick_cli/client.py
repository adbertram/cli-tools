"""Cliclick wrapper client using subprocess to call underlying CLI."""
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

from .config import get_config
from .applescript import (
    check_accessibility_permissions,
    test_cliclick_permissions,
    get_accessibility_instructions,
)
from .models import (
    Position,
    Color,
    Script,
    ExecutionResult,
    CliclickStatus,
    create_position,
    create_color,
    create_script,
    create_execution_result,
    create_status,
)


class ClientError(Exception):
    """Custom exception for Cliclick wrapper errors."""

    pass


class CliclickClient:
    """Wrapper client for cliclick CLI.

    Provides a Pythonic interface to cliclick's mouse and keyboard
    automation commands. Handles permission checking, output parsing,
    and script management.
    """

    # Template variable pattern: {{variable_name}}
    TEMPLATE_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")

    def __init__(self, skip_availability_check: bool = False):
        """Initialize Cliclick wrapper client.

        Args:
            skip_availability_check: If True, don't check CLI availability on init.
                                     Used for auth status check when CLI may not exist.
        """
        self.config = get_config()
        self._skip_check = skip_availability_check

        if not skip_availability_check and not self.config.is_cli_available():
            raise ClientError(
                f"cliclick not found. Install with: brew install cliclick\n"
                f"Documentation: https://github.com/BlueM/cliclick"
            )

    def _run_command(
        self,
        args: List[str],
        input_text: Optional[str] = None,
        timeout: int = 60,
        check: bool = True,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run a cliclick command.

        Args:
            args: Command arguments (cliclick command strings)
            input_text: Optional text to pass to stdin
            timeout: Command timeout in seconds
            check: If True, raise ClientError on non-zero exit
            verbose: If True, add -m verbose flag
            test_mode: If True, add -m test flag (no actual execution)
            restore: If True, add -r flag to restore mouse position

        Returns:
            CompletedProcess with stdout, stderr, and returncode

        Raises:
            ClientError: If command fails and check=True
        """
        cmd = [self.config.get_cli_executable()]

        # Add mode flags
        if test_mode:
            cmd.extend(["-m", "test"])
        elif verbose:
            cmd.extend(["-m", "verbose"])

        # Add restore flag (default on)
        if restore:
            cmd.append("-r")

        # Add command arguments
        cmd.extend(args)

        try:
            result = subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if check and result.returncode != 0:
                error_msg = (
                    result.stderr.strip() or result.stdout.strip() or "Command failed"
                )
                raise ClientError(f"cliclick error: {error_msg}")

            return result

        except subprocess.TimeoutExpired:
            raise ClientError(f"Command timed out after {timeout} seconds")
        except FileNotFoundError:
            raise ClientError(
                "cliclick not found. Install with: brew install cliclick"
            )
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to run command: {e}")

    def _run_from_file(
        self,
        file_path: str,
        timeout: int = 60,
        check: bool = True,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run cliclick commands from a file.

        Args:
            file_path: Path to file containing cliclick commands
            Other args: Same as _run_command

        Returns:
            CompletedProcess result
        """
        cmd = [self.config.get_cli_executable()]

        if test_mode:
            cmd.extend(["-m", "test"])
        elif verbose:
            cmd.extend(["-m", "verbose"])

        if restore:
            cmd.append("-r")

        cmd.extend(["-f", file_path])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if check and result.returncode != 0:
                error_msg = (
                    result.stderr.strip() or result.stdout.strip() or "Command failed"
                )
                raise ClientError(f"cliclick error: {error_msg}")

            return result

        except subprocess.TimeoutExpired:
            raise ClientError(f"Script timed out after {timeout} seconds")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to run script: {e}")

    def _run_from_stdin(
        self,
        commands: str,
        timeout: int = 60,
        check: bool = True,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> subprocess.CompletedProcess:
        """Run cliclick commands from stdin.

        Args:
            commands: Newline-separated cliclick commands
            Other args: Same as _run_command

        Returns:
            CompletedProcess result
        """
        cmd = [self.config.get_cli_executable()]

        if test_mode:
            cmd.extend(["-m", "test"])
        elif verbose:
            cmd.extend(["-m", "verbose"])

        if restore:
            cmd.append("-r")

        cmd.extend(["-f", "-"])  # Read from stdin

        try:
            result = subprocess.run(
                cmd,
                input=commands,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if check and result.returncode != 0:
                error_msg = (
                    result.stderr.strip() or result.stdout.strip() or "Command failed"
                )
                raise ClientError(f"cliclick error: {error_msg}")

            return result

        except subprocess.TimeoutExpired:
            raise ClientError(f"Commands timed out after {timeout} seconds")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to run commands: {e}")

    # ==================== Auth Methods ====================

    def auth_login(self, force: bool = False) -> Dict[str, Any]:
        """Stub login - cliclick requires no authentication.

        Args:
            force: Ignored, kept for interface compatibility

        Returns:
            Dict with success status and message
        """
        # Check if cliclick is available and has permissions
        status = self.auth_status()

        if status["authenticated"]:
            return {
                "success": True,
                "message": "cliclick is available and Accessibility permissions are granted.",
            }
        else:
            return {
                "success": False,
                "message": status.get("message", "cliclick not ready"),
            }

    def auth_logout(self) -> Dict[str, Any]:
        """Stub logout - cliclick requires no authentication.

        Returns:
            Dict with success status and message
        """
        return {
            "success": True,
            "message": "cliclick is a local tool with no authentication to clear.",
        }

    def auth_status(self) -> Dict[str, Any]:
        """Check cliclick availability and Accessibility permissions.

        Returns:
            Dict with:
            - authenticated: True if cliclick works (available + permissions)
            - cli_available: True if cliclick binary found
            - cli_path: Path to cliclick binary
            - version: cliclick version string
            - accessibility_permissions: True if permissions granted
            - message: Human-readable status message
        """
        cli_available = self.config.is_cli_available()
        cli_path = self.config.get_cli_executable() if cli_available else None
        version = self.config.get_cli_version() if cli_available else None

        if not cli_available:
            return {
                "authenticated": False,
                "cli_available": False,
                "cli_path": None,
                "version": None,
                "accessibility_permissions": False,
                "message": "cliclick not found. Install with: brew install cliclick",
            }

        # Test actual cliclick execution (this checks real permissions)
        has_permissions = test_cliclick_permissions(cli_path)

        if has_permissions:
            return {
                "authenticated": True,
                "cli_available": True,
                "cli_path": cli_path,
                "version": version,
                "accessibility_permissions": True,
                "message": "cliclick is ready.",
            }
        else:
            return {
                "authenticated": False,
                "cli_available": True,
                "cli_path": cli_path,
                "version": version,
                "accessibility_permissions": False,
                "message": get_accessibility_instructions(),
            }

    # ==================== Mouse Methods ====================

    def click(
        self,
        x: int,
        y: int,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Click at coordinates.

        Args:
            x: X coordinate
            y: Y coordinate
            verbose: Enable verbose output
            test_mode: Don't actually click
            restore: Restore mouse position after

        Returns:
            ExecutionResult with command outcome
        """
        start = time.time()
        result = self._run_command(
            [f"c:{x},{y}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def double_click(
        self,
        x: int,
        y: int,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Double-click at coordinates."""
        start = time.time()
        result = self._run_command(
            [f"dc:{x},{y}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def right_click(
        self,
        x: int,
        y: int,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Right-click at coordinates."""
        start = time.time()
        result = self._run_command(
            [f"rc:{x},{y}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def triple_click(
        self,
        x: int,
        y: int,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Triple-click at coordinates."""
        start = time.time()
        result = self._run_command(
            [f"tc:{x},{y}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def move(
        self,
        x: int,
        y: int,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Move mouse to coordinates."""
        start = time.time()
        result = self._run_command(
            [f"m:{x},{y}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def drag_start(
        self,
        x: int,
        y: int,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Start drag at coordinates (mouse down)."""
        start = time.time()
        result = self._run_command(
            [f"dd:{x},{y}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def drag_move(
        self,
        x: int,
        y: int,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Continue drag to coordinates (while mouse down)."""
        start = time.time()
        result = self._run_command(
            [f"dm:{x},{y}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def drag_end(
        self,
        x: int,
        y: int,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """End drag at coordinates (mouse up)."""
        start = time.time()
        result = self._run_command(
            [f"du:{x},{y}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def get_position(self) -> Position:
        """Get current mouse position.

        Returns:
            Position model with x, y coordinates
        """
        result = self._run_command(["p"], restore=False)
        output = result.stdout.strip()

        # Parse "x,y" format
        try:
            x_str, y_str = output.split(",")
            return create_position(int(x_str), int(y_str))
        except (ValueError, IndexError):
            raise ClientError(f"Failed to parse position from: {output}")

    def get_color_at(self, x: int, y: int) -> Color:
        """Get color at screen coordinates.

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            Color model with r, g, b values
        """
        result = self._run_command([f"cp:{x},{y}"], restore=False)
        output = result.stdout.strip()

        # Parse "r g b" format (space-separated)
        try:
            parts = output.split()
            if len(parts) >= 3:
                return create_color(int(parts[0]), int(parts[1]), int(parts[2]))
            raise ValueError("Not enough color components")
        except (ValueError, IndexError):
            raise ClientError(f"Failed to parse color from: {output}")

    # ==================== Keyboard Methods ====================

    def type_text(
        self,
        text: str,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Type text into the active application.

        Args:
            text: Text to type
            verbose: Enable verbose output
            test_mode: Don't actually type
            restore: Restore mouse position after

        Returns:
            ExecutionResult with command outcome
        """
        start = time.time()
        # Quote text if it contains spaces
        result = self._run_command(
            [f"t:{text}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def key_press(
        self,
        key: str,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Press a key.

        Args:
            key: Key to press (e.g., "return", "tab", "esc", "f1")
            verbose: Enable verbose output
            test_mode: Don't actually press
            restore: Restore mouse position after

        Returns:
            ExecutionResult with command outcome
        """
        start = time.time()
        result = self._run_command(
            [f"kp:{key}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def key_down(
        self,
        keys: str,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Press and hold modifier keys.

        Args:
            keys: Comma-separated modifier keys (e.g., "cmd,shift")
            verbose: Enable verbose output
            test_mode: Don't actually press
            restore: Restore mouse position after

        Returns:
            ExecutionResult with command outcome
        """
        start = time.time()
        result = self._run_command(
            [f"kd:{keys}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def key_up(
        self,
        keys: str,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Release modifier keys.

        Args:
            keys: Comma-separated modifier keys (e.g., "cmd,shift")
            verbose: Enable verbose output
            test_mode: Don't actually release
            restore: Restore mouse position after

        Returns:
            ExecutionResult with command outcome
        """
        start = time.time()
        result = self._run_command(
            [f"ku:{keys}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    # ==================== Utility Methods ====================

    def wait(
        self,
        milliseconds: int,
        verbose: bool = False,
        test_mode: bool = False,
    ) -> ExecutionResult:
        """Wait for specified milliseconds.

        Args:
            milliseconds: Time to wait
            verbose: Enable verbose output
            test_mode: Don't actually wait

        Returns:
            ExecutionResult with command outcome
        """
        start = time.time()
        result = self._run_command(
            [f"w:{milliseconds}"],
            verbose=verbose,
            test_mode=test_mode,
            restore=False,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
        )

    def execute_raw(
        self,
        commands: str,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Execute raw cliclick command string.

        Args:
            commands: Space-separated cliclick commands (e.g., "c:100,200 w:500 t:hello")
            verbose: Enable verbose output
            test_mode: Don't actually execute
            restore: Restore mouse position after

        Returns:
            ExecutionResult with command outcome
        """
        start = time.time()
        # Split command string into args
        args = commands.split()
        result = self._run_command(
            args,
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
            commands_executed=len(args),
        )

    # ==================== Script Methods ====================

    def _get_scripts_dir(self) -> Path:
        """Get the scripts directory path."""
        return Path(__file__).parent / "scripts"

    def list_scripts(self, limit: int = 100) -> List[Script]:
        """List all scripts in the scripts directory.

        Args:
            limit: Maximum number of scripts to return

        Returns:
            List of Script models
        """
        scripts_dir = self._get_scripts_dir()
        if not scripts_dir.exists():
            scripts_dir.mkdir(parents=True, exist_ok=True)
            return []

        scripts = []
        for script_file in scripts_dir.glob("*.cliclick"):
            content = script_file.read_text()
            # Find template variables
            variables = list(set(self.TEMPLATE_VAR_PATTERN.findall(content)))
            # Count non-empty, non-comment lines
            command_count = sum(
                1
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            )

            scripts.append(
                create_script(
                    name=script_file.stem,
                    path=str(script_file),
                    variables=variables,
                    command_count=command_count,
                )
            )

        return scripts[:limit]

    def get_script(self, name: str) -> Script:
        """Get a script by name.

        Args:
            name: Script name (without .cliclick extension)

        Returns:
            Script model

        Raises:
            ClientError: If script not found
        """
        scripts_dir = self._get_scripts_dir()
        script_path = scripts_dir / f"{name}.cliclick"

        if not script_path.exists():
            raise ClientError(f"Script not found: {name}")

        content = script_path.read_text()
        variables = list(set(self.TEMPLATE_VAR_PATTERN.findall(content)))
        command_count = sum(
            1
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

        return create_script(
            name=name,
            path=str(script_path),
            variables=variables,
            command_count=command_count,
        )

    def create_script(
        self, name: str, content: str, description: Optional[str] = None
    ) -> Script:
        """Create a new script.

        Args:
            name: Script name (without .cliclick extension)
            content: Script content (cliclick commands, one per line)
            description: Optional description (added as comment at top)

        Returns:
            Created Script model

        Raises:
            ClientError: If script already exists
        """
        scripts_dir = self._get_scripts_dir()
        scripts_dir.mkdir(parents=True, exist_ok=True)

        script_path = scripts_dir / f"{name}.cliclick"
        if script_path.exists():
            raise ClientError(f"Script already exists: {name}")

        # Add description as comment if provided
        if description:
            content = f"# {description}\n{content}"

        script_path.write_text(content)

        variables = list(set(self.TEMPLATE_VAR_PATTERN.findall(content)))
        command_count = sum(
            1
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

        return create_script(
            name=name,
            path=str(script_path),
            description=description,
            variables=variables,
            command_count=command_count,
        )

    def delete_script(self, name: str) -> bool:
        """Delete a script.

        Args:
            name: Script name (without .cliclick extension)

        Returns:
            True if deleted

        Raises:
            ClientError: If script not found
        """
        scripts_dir = self._get_scripts_dir()
        script_path = scripts_dir / f"{name}.cliclick"

        if not script_path.exists():
            raise ClientError(f"Script not found: {name}")

        script_path.unlink()
        return True

    def run_script(
        self,
        name: str,
        variables: Optional[Dict[str, str]] = None,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Run a script by name.

        Args:
            name: Script name (without .cliclick extension)
            variables: Template variable substitutions (e.g., {"x": "100", "y": "200"})
            verbose: Enable verbose output
            test_mode: Don't actually execute
            restore: Restore mouse position after

        Returns:
            ExecutionResult with command outcome

        Raises:
            ClientError: If script not found or missing variables
        """
        script = self.get_script(name)
        content = Path(script.path).read_text()

        # Substitute template variables
        if variables:
            for var_name, var_value in variables.items():
                content = content.replace(f"{{{{{var_name}}}}}", var_value)

        # Check for remaining unsubstituted variables
        remaining = self.TEMPLATE_VAR_PATTERN.findall(content)
        if remaining:
            raise ClientError(
                f"Missing template variables: {', '.join(set(remaining))}"
            )

        start = time.time()
        result = self._run_from_stdin(
            content,
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
            commands_executed=script.command_count,
        )

    def run_stdin(
        self,
        commands: str,
        verbose: bool = False,
        test_mode: bool = False,
        restore: bool = True,
    ) -> ExecutionResult:
        """Run commands from stdin content.

        Args:
            commands: Newline-separated cliclick commands
            verbose: Enable verbose output
            test_mode: Don't actually execute
            restore: Restore mouse position after

        Returns:
            ExecutionResult with command outcome
        """
        start = time.time()
        result = self._run_from_stdin(
            commands,
            verbose=verbose,
            test_mode=test_mode,
            restore=restore,
        )
        duration = (time.time() - start) * 1000

        command_count = sum(
            1
            for line in commands.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

        return create_execution_result(
            success=result.returncode == 0,
            output=result.stdout.strip(),
            error=result.stderr.strip() if result.returncode != 0 else None,
            duration_ms=duration,
            commands_executed=command_count,
        )


# Module-level client instance - singleton pattern
_client: Optional[CliclickClient] = None


def get_client(skip_availability_check: bool = False) -> CliclickClient:
    """Get or create the global Cliclick client instance.

    Args:
        skip_availability_check: If True, don't check CLI availability

    Returns:
        CliclickClient instance
    """
    global _client
    if _client is None:
        _client = CliclickClient(skip_availability_check=skip_availability_check)
    return _client
