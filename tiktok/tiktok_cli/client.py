"""TikTok transcript downloader using yt-dlp."""
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional


class ClientError(Exception):
    """Custom exception for TikTok CLI errors."""
    pass


class TiktokClient:
    """Client for downloading TikTok transcripts using yt-dlp."""

    def __init__(self):
        """Initialize TikTok client."""
        self.ytdlp_path = self._find_ytdlp()

    def _find_ytdlp(self) -> str:
        """Find yt-dlp executable path."""
        result = subprocess.run(
            ["which", "yt-dlp"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise ClientError(
                "yt-dlp not found. Install it with: brew install yt-dlp"
            )
        return result.stdout.strip()

    def get_video_metadata(self, url: str) -> Dict:
        """Get video metadata using yt-dlp."""
        cmd = [
            self.ytdlp_path,
            "--dump-json",
            "--skip-download",
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise ClientError(f"Failed to get video metadata: {result.stderr}")

        return json.loads(result.stdout)

    def _get_available_sub_lang(self, url: str, preferred_lang: str) -> str:
        """Discover available subtitle language matching the preferred language.

        TikTok uses language codes like 'eng-US' instead of 'en'.
        This method finds the best match from available subtitles.
        """
        cmd = [
            self.ytdlp_path,
            "--list-subs",
            "--skip-download",
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout + result.stderr

        # Map short codes to yt-dlp language prefixes
        lang_map = {
            "en": "eng",
            "es": "spa",
            "fr": "fra",
            "de": "deu",
            "ja": "jpn",
            "ko": "kor",
            "zh": "zho",
            "pt": "por",
            "it": "ita",
            "ru": "rus",
        }

        prefix = lang_map.get(preferred_lang, preferred_lang)

        # Parse available languages from --list-subs output
        for line in output.split('\n'):
            line = line.strip()
            # Lines like "eng-US   vtt"
            if line and not line.startswith('[') and not line.startswith('WARNING') and not line.startswith('Language'):
                available_lang = line.split()[0]
                # Match by prefix (eng matches eng-US)
                if available_lang.startswith(prefix) or available_lang == preferred_lang:
                    return available_lang

        # No match found — return original and let yt-dlp handle it
        return preferred_lang

    def download_transcript(
        self,
        url: str,
        output_dir: str = ".",
        format: str = "srt",
        lang: str = "en",
        auto_sub: bool = True,
        manual_sub: bool = False,
    ) -> Dict:
        """Download transcript for a TikTok video."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Get metadata first
        metadata = self.get_video_metadata(url)

        # Discover the actual subtitle language code available
        actual_lang = self._get_available_sub_lang(url, lang)

        # Build yt-dlp command — TikTok subs use --write-sub (not --write-auto-sub)
        cmd = [
            self.ytdlp_path,
            "--skip-download",
            "--write-sub",
            "--sub-lang", actual_lang,
            "--convert-subs", format,
            "-o", f"{output_dir}/%(title)s.%(ext)s",
            url,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise ClientError(f"Failed to download transcript: {result.stderr}")

        # Check if subtitles were actually found
        if "There are no subtitles" in result.stderr or "There aren't any subtitles" in result.stderr:
            raise ClientError(f"No subtitles available for language '{lang}' (tried '{actual_lang}')")

        # Find the downloaded file — try both the actual lang code and the requested one
        output_files = list(Path(output_dir).glob(f"*.{actual_lang}.{format}"))
        if not output_files:
            output_files = list(Path(output_dir).glob(f"*.{lang}.{format}"))

        actual_file = None
        if output_files:
            output_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            actual_file = output_files[0]
        else:
            title = metadata.get("title", "unknown")
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            actual_file = Path(output_dir) / f"{safe_title}.{actual_lang}.{format}"

        return {
            "url": url,
            "title": metadata.get("title", "Unknown"),
            "duration": metadata.get("duration", 0),
            "file_path": str(actual_file),
            "file_size": actual_file.stat().st_size if actual_file.exists() else 0,
            "format": format,
            "language": actual_lang,
        }

    def download_transcripts(
        self,
        urls: List[str],
        output_dir: str = ".",
        format: str = "srt",
        lang: str = "en",
        auto_sub: bool = True,
        manual_sub: bool = False,
    ) -> List[Dict]:
        """Download transcripts for multiple TikTok videos."""
        results = []
        for url in urls:
            result = self.download_transcript(
                url=url,
                output_dir=output_dir,
                format=format,
                lang=lang,
                auto_sub=auto_sub,
                manual_sub=manual_sub,
            )
            results.append(result)
        return results


# Module-level client instance - singleton pattern
_client: Optional[TiktokClient] = None


def get_client() -> TiktokClient:
    """Get or create the global TikTok client instance."""
    global _client
    if _client is None:
        _client = TiktokClient()
    return _client
