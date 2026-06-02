"""Whisper wrapper client using subprocess to call underlying CLI."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any

from .config import get_config
from .models import Transcript, TranscriptSummary, WhisperModel, create_transcript


class ClientError(Exception):
    """Custom exception for Whisper wrapper errors."""
    pass


class WhisperClient:
    """Wrapper client for whisper CLI.

    Calls the underlying whisper CLI via subprocess and parses output
    to Pydantic models.
    """

    def __init__(self):
        """Initialize Whisper wrapper client."""
        self.config = get_config()

        if not self.config.is_cli_available():
            raise ClientError(
                f"Underlying CLI '{self.config.cli_command}' not found. "
                f"Please install it with: pipx install openai-whisper"
            )

    def _run_command(
        self,
        args: List[str],
        timeout: int = 600,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        """
        Run a command on the underlying whisper CLI.

        Args:
            args: Command arguments (without the CLI command itself)
            timeout: Command timeout in seconds (default 10 minutes for large files)
            check: If True, raise ClientError on non-zero exit

        Returns:
            CompletedProcess with stdout, stderr, and returncode

        Raises:
            ClientError: If command fails and check=True
        """
        cmd = [self.config.get_cli_executable()] + args

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if check and result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Command failed"
                raise ClientError(f"{self.config.cli_command} error: {error_msg}")

            return result

        except subprocess.TimeoutExpired:
            raise ClientError(f"Command timed out after {timeout} seconds")
        except FileNotFoundError:
            raise ClientError(f"CLI '{self.config.cli_command}' not found in PATH")
        except Exception as e:
            if isinstance(e, ClientError):
                raise
            raise ClientError(f"Failed to run command: {e}")

    # ==================== Auth Methods ====================
    # Whisper is a local CLI that doesn't require authentication

    def auth_login(self, force: bool = False, **kwargs) -> Dict[str, Any]:
        """
        No authentication required for local Whisper CLI.

        Args:
            force: Ignored (no authentication needed)

        Returns:
            Dict indicating no auth required
        """
        return {
            "success": True,
            "authenticated": True,
            "message": "No authentication required. Whisper runs locally.",
        }

    def auth_logout(self) -> Dict[str, Any]:
        """
        No authentication to clear for local Whisper CLI.

        Returns:
            Dict indicating no auth required
        """
        return {
            "success": True,
            "message": "No authentication to clear. Whisper runs locally.",
        }

    def auth_status(self) -> Dict[str, Any]:
        """
        Check Whisper CLI availability (no auth needed).

        Returns:
            Dict with CLI availability status
        """
        return {
            "authenticated": True,  # Always "authenticated" since no auth required
            "cli_command": self.config.cli_command,
            "cli_available": True,
            "cli_version": self.config.get_cli_version(),
            "message": "Whisper runs locally - no authentication required.",
        }

    # ==================== Transcription Methods ====================

    def transcribe(
        self,
        file_path: str,
        model: WhisperModel = WhisperModel.TURBO,
        language: str = "en",
        word_timestamps: bool = False,
        output_dir: Optional[str] = None,
        timeout: int = 600,
    ) -> Transcript:
        """
        Transcribe an audio/video file using Whisper.

        Args:
            file_path: Path to audio/video file
            model: Whisper model to use (tiny, base, small, medium, large, turbo)
            language: Language code (default: en)
            word_timestamps: Enable word-level timestamps
            output_dir: Directory to save output files (default: same as input)
            timeout: Command timeout in seconds (default: 10 minutes)

        Returns:
            Transcript model with text and segments

        Raises:
            ClientError: If file doesn't exist or transcription fails
        """
        # Validate file exists
        file_path = os.path.abspath(file_path)
        if not os.path.exists(file_path):
            raise ClientError(f"File not found: {file_path}")

        # Determine output directory
        if output_dir:
            out_dir = os.path.abspath(output_dir)
            os.makedirs(out_dir, exist_ok=True)
        else:
            out_dir = os.path.dirname(file_path)

        # Build command
        args = [
            file_path,
            "--model", model.value,
            "--language", language,
            "--output_format", "json",
            "--output_dir", out_dir,
        ]

        if word_timestamps:
            args.extend(["--word_timestamps", "True"])

        # Run transcription
        self._run_command(args, timeout=timeout)

        # Read the JSON output file
        base_name = Path(file_path).stem
        json_path = os.path.join(out_dir, f"{base_name}.json")

        if not os.path.exists(json_path):
            raise ClientError(f"Whisper did not produce expected output file: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return create_transcript(data, source_file=file_path, model=model.value)

    def get_models(self) -> List[str]:
        """
        Get list of available Whisper models.

        Returns:
            List of model names
        """
        return [m.value for m in WhisperModel]


# Module-level client instance - singleton pattern
_client: Optional[WhisperClient] = None


def get_client() -> WhisperClient:
    """Get or create the global Whisper client instance."""
    global _client
    if _client is None:
        _client = WhisperClient()
    return _client
