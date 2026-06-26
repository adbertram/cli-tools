"""whisper.cpp wrapper client.

Drives the ``whisper-cli`` binary (whisper.cpp) via subprocess to produce
transcripts, normalizing audio to the 16 kHz mono WAV that whisper.cpp
requires and parsing its JSON output into a uniform transcript shape.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from cli_tools_shared.exceptions import ClientError

from .config import get_config
from .parsers import parse_whisper_cpp_json

FFMPEG_COMMAND = "ffmpeg"


class WhisperClient:
    """Wrapper client for the whisper.cpp ``whisper-cli`` binary."""

    def __init__(self):
        self.config = get_config()
        if not self.config.is_cli_available():
            raise ClientError(
                f"whisper.cpp binary '{self.config.get_cli_executable()}' not "
                "found. Install whisper.cpp (brew install whisper-cpp) or set "
                "WHISPER_CLI_PATH to the whisper-cli binary."
            )

    # ==================== Subprocess plumbing ====================

    def _run(self, cmd: List[str], timeout: int) -> subprocess.CompletedProcess:
        """Run a subprocess, raising ClientError on failure or timeout."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise ClientError(
                f"Command timed out after {timeout} seconds: {cmd[0]}"
            )
        except FileNotFoundError:
            raise ClientError(f"Executable not found: {cmd[0]}")

        if result.returncode != 0:
            message = (
                result.stderr.strip()
                or result.stdout.strip()
                or "command failed"
            )
            raise ClientError(f"{Path(cmd[0]).name} error: {message}")
        return result

    def _resolve_model(self, model: Optional[str]) -> str:
        """Resolve the ggml model path and fail fast if it is missing."""
        model_path = (
            os.path.expanduser(model) if model else self.config.model_path
        )
        if not os.path.isfile(model_path):
            raise ClientError(
                f"Whisper model not found: {model_path}. Download a ggml model "
                "(e.g. ggml-small.en.bin) into the models directory or pass "
                "--model / set WHISPER_CPP_MODEL to an existing file."
            )
        return model_path

    def _normalize_audio(self, src: str, dest: str, timeout: int) -> None:
        """Transcode any input to 16 kHz mono WAV (whisper.cpp requirement)."""
        if shutil.which(FFMPEG_COMMAND) is None:
            raise ClientError(
                "ffmpeg not found in PATH. Install ffmpeg (brew install ffmpeg) "
                "to normalize audio for whisper.cpp."
            )
        self._run(
            [
                FFMPEG_COMMAND,
                "-y",
                "-i",
                src,
                "-ar",
                "16000",
                "-ac",
                "1",
                dest,
            ],
            timeout=timeout,
        )

    # ==================== Transcription ====================

    def transcribe(
        self,
        file_path: str,
        model: Optional[str] = None,
        language: str = "en",
        word_timestamps: bool = False,
        output_dir: Optional[str] = None,
        timeout: int = 600,
        prompt: Optional[str] = None,
    ) -> dict:
        """Transcribe an audio/video file with whisper.cpp.

        Returns a dict uniform with the ``openai-whisper`` wrapper:
        ``{"text", "language", "segments": [...], "words": [...]?}``.
        ``words`` is present only when ``word_timestamps`` is requested.

        ``prompt`` is whisper.cpp's initial prompt for vocabulary biasing; when
        non-empty it is passed through as ``--prompt``. An empty/None prompt is
        not passed at all.
        """
        src = os.path.abspath(file_path)
        if not os.path.isfile(src):
            raise ClientError(f"File not found: {src}")

        model_path = self._resolve_model(model)

        # whisper.cpp requires 16 kHz mono WAV. Normalize into a tempdir and
        # run whisper.cpp there, then copy the JSON out if an output dir was
        # requested. The tempdir (and the normalized WAV) is always removed.
        tmpdir = tempfile.mkdtemp(prefix="whisper-cpp-")
        try:
            stem = Path(src).stem
            wav_path = os.path.join(tmpdir, f"{stem}.16k.wav")
            self._normalize_audio(src, wav_path, timeout=timeout)

            out_stem = os.path.join(tmpdir, stem)
            cmd = [
                self.config.get_cli_executable(),
                "-m",
                model_path,
                "-f",
                wav_path,
                "-l",
                language,
                "-oj",
                "-of",
                out_stem,
            ]
            if word_timestamps:
                # -ml 1 splits the transcription into per-word entries.
                cmd.extend(["-ml", "1"])
            if prompt:
                # Initial prompt biases whisper.cpp toward the listed
                # vocabulary/spellings (max n_text_ctx/2 tokens).
                cmd.extend(["--prompt", prompt])

            self._run(cmd, timeout=timeout)

            json_path = f"{out_stem}.json"
            if not os.path.isfile(json_path):
                raise ClientError(
                    f"whisper.cpp did not produce expected JSON output: {json_path}"
                )

            with open(json_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)

            if output_dir:
                out_dir = os.path.abspath(output_dir)
                os.makedirs(out_dir, exist_ok=True)
                shutil.copy2(json_path, os.path.join(out_dir, f"{stem}.json"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        segments = parse_whisper_cpp_json(data)
        text = " ".join(segment["text"] for segment in segments).strip()

        transcript = {
            "text": text,
            "language": language,
            "segments": segments,
        }
        if word_timestamps:
            # With -ml 1 the parsed entries are per-word; expose them as words.
            transcript["words"] = segments
        return transcript

    # ==================== Models ====================

    def list_models(self) -> List[dict]:
        """List local ggml model files found in the models directory."""
        models_dir = self.config.models_dir
        if not models_dir.is_dir():
            return []
        models = []
        for path in sorted(models_dir.glob("*.bin")):
            stat = path.stat()
            models.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_mb": round(stat.st_size / (1024 * 1024), 1),
                }
            )
        return models


_client: Optional[WhisperClient] = None


def get_client() -> WhisperClient:
    """Get or create the global whisper.cpp client instance."""
    global _client
    if _client is None:
        _client = WhisperClient()
    return _client
