"""macspeech client — drives the local MacSpeech.app helper.

The helper is a compiled Swift binary inside a `MacSpeech.app` bundle. It is
launched via LaunchServices (`open -W -n MacSpeech.app --args ...`) so the app
is its own responsible process for the macOS Speech Recognition TCC check; a
directly-exec'd binary hard-crashes (SIGABRT, missing
NSSpeechRecognitionUsageDescription). Because `open` discards stdout, the helper
writes its JSON result to an output-file path passed as an argument, and this
client reads that file.

Fail-fast: a missing audio file, an uninstalled app, a helper non-zero exit, a
helper-reported error, a missing/empty output file, or a timeout all raise a
ClientError. There is never a silent empty transcript.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from cli_tools_shared.exceptions import ClientError

from .config import DEFAULT_TIMEOUT, get_config, language_to_locale


# Extra seconds granted to the `open -W` subprocess over the helper's own
# watchdog, so the helper reports its clearer timeout error before the
# subprocess wrapper would.
_SUBPROCESS_TIMEOUT_GRACE = 15


# Authorization status raw values from SFSpeechRecognizer.authorizationStatus().
AUTHORIZATION_STATUS_LABELS = {
    0: "notDetermined",
    1: "denied",
    2: "restricted",
    3: "authorized",
}


def build_transcript(raw: dict, language: str) -> dict:
    """Map the helper's JSON to the uniform transcript output shape.

    The helper returns {"transcript": <str>, "words": [{text,start,end,confidence}]}.
    We rename `transcript` -> `text` so output is uniform with the whisper tools
    (top-level `text`, `language`, `words`); start/end stay in seconds.
    """
    return {
        "text": raw["transcript"],
        "language": language,
        "words": raw.get("words", []),
    }


class MacspeechClient:
    """Client that runs the local MacSpeech.app helper."""

    def __init__(self):
        self.config = get_config()

    def _ensure_installed(self) -> None:
        if not self.config.is_app_installed():
            raise ClientError(
                f"MacSpeech.app is not installed at {self.config.app_path}. "
                f"Build it with: {self.config.build_script}"
            )

    def _run_app(self, args: List[str], timeout: int) -> None:
        """Launch MacSpeech.app via `open -W -n` and wait for it to exit.

        `open -W` waits for the app to terminate; `-n` opens a fresh instance so
        each invocation is isolated. The helper writes its result to the output
        file in `args`; we only inspect `open`'s exit status here.
        """
        cmd = ["open", "-W", "-n", str(self.config.app_path), "--args", *args]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ClientError(f"macspeech-helper timed out after {timeout} seconds")
        except FileNotFoundError:
            raise ClientError("`open` not found in PATH (required to launch MacSpeech.app)")

        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "Command failed"
            raise ClientError(f"macspeech-helper launch failed: {message}")

    def _read_helper_output(self, out_path: Path) -> dict:
        """Read and parse the helper's JSON output file, failing fast on errors."""
        if not out_path.is_file():
            raise ClientError(
                f"macspeech-helper produced no output file at {out_path} "
                "(the .app may lack Speech Recognition permission)"
            )
        text = out_path.read_text(encoding="utf-8").strip()
        if not text:
            raise ClientError(f"macspeech-helper produced an empty output file at {out_path}")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClientError(f"macspeech-helper produced invalid JSON: {exc}")
        if isinstance(payload, dict) and "error" in payload:
            raise ClientError(f"macspeech-helper error: {payload['error']}")
        return payload

    def authorization_status(self, timeout: int = 30) -> dict:
        """Read Speech Recognition authorization status PASSIVELY (never prompts).

        Runs the helper's `--status` mode, which reads
        SFSpeechRecognizer.authorizationStatus() without calling
        requestAuthorization, so it cannot pop the TCC dialog.
        """
        self._ensure_installed()
        with tempfile.TemporaryDirectory(prefix="macspeech-") as tmp:
            out_path = Path(tmp) / "status.json"
            self._run_app(["--status", str(out_path)], timeout=timeout)
            payload = self._read_helper_output(out_path)
        raw_status = payload.get("authorizationStatus")
        if raw_status is None:
            raise ClientError("macspeech-helper did not report an authorization status")
        return {
            "authorization_status": raw_status,
            "authorization_status_label": AUTHORIZATION_STATUS_LABELS.get(raw_status, "unknown"),
            "authorized": raw_status == 3,
            "app_path": str(self.config.app_path),
        }

    def transcribe(
        self,
        file_path: str,
        language: str = "en",
        contextual_strings: Optional[List[str]] = None,
        punctuation: bool = True,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> dict:
        """Transcribe an audio file on-device via MacSpeech.app.

        Args:
            file_path: Path to the audio file.
            language: Language code; `en` maps to locale `en-US`, others pass through.
            contextual_strings: Phrases fed to SFSpeechRecognitionRequest.contextualStrings
                for vocabulary biasing. None falls back to the configured default.
            punctuation: Sets SFSpeechRecognitionRequest.addsPunctuation (macOS 13+).
            timeout: Max seconds to wait for the helper.

        Returns:
            Uniform transcript dict: {"text", "language", "words"}.

        Raises:
            ClientError: on any failure (missing file, uninstalled app, helper
            error, empty/missing output, timeout).
        """
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path):
            raise ClientError(f"Audio file not found: {file_path}")

        self._ensure_installed()

        locale = language_to_locale(language)
        phrases = self.config.default_contextual_strings if contextual_strings is None else contextual_strings

        with tempfile.TemporaryDirectory(prefix="macspeech-") as tmp:
            tmp_dir = Path(tmp)
            out_path = tmp_dir / "result.json"
            helper_args = [abs_path, locale, str(out_path)]

            if phrases:
                ctx_path = tmp_dir / "contextual_strings.txt"
                ctx_path.write_text("\n".join(phrases) + "\n", encoding="utf-8")
                helper_args += ["--contextual-strings-file", str(ctx_path)]

            helper_args += ["--punctuation", "1" if punctuation else "0"]
            # Pass the caller's timeout so the helper's internal watchdog tracks
            # it (never silently caps a long transcription).
            helper_args += ["--timeout", str(timeout)]

            # Give `open -W` a grace margin so the helper's own (clearer) timeout
            # error surfaces before the subprocess wrapper would time out.
            self._run_app(helper_args, timeout=timeout + _SUBPROCESS_TIMEOUT_GRACE)
            payload = self._read_helper_output(out_path)

        if "transcript" not in payload:
            raise ClientError(f"macspeech-helper output missing 'transcript' key: got keys {list(payload.keys())}")

        return build_transcript(payload, language)


_client: Optional[MacspeechClient] = None


def get_client() -> MacspeechClient:
    """Get or create the global macspeech client instance."""
    global _client
    if _client is None:
        _client = MacspeechClient()
    return _client
