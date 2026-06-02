"""YouTube transcript downloader using yt-dlp."""
import subprocess
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Set


class ClientError(Exception):
    """Custom exception for YouTube CLI errors."""
    pass


MAX_RESOLUTION_FORMATS = {
    "480p": "bestvideo[height<=480][vcodec^=avc]+bestaudio[acodec^=mp4a]",
    "360p": "bestvideo[height<=360][vcodec^=avc]+bestaudio[acodec^=mp4a]",
    "240p": "bestvideo[height<=240][vcodec^=avc]+bestaudio[acodec^=mp4a]",
}
MAX_RESOLUTION_VALUES = ", ".join(MAX_RESOLUTION_FORMATS)
TRANSCRIPT_FORMATS = {"srt", "vtt", "txt"}
YT_DLP_SUBTITLE_FORMATS = {"srt", "vtt"}


class YoutubeClient:
    """Client for downloading YouTube transcripts using yt-dlp."""

    def __init__(self):
        """Initialize YouTube client."""
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
        """
        Get video metadata using yt-dlp.

        Args:
            url: YouTube video URL

        Returns:
            Video metadata dictionary

        Raises:
            ClientError: If metadata extraction fails
        """
        cmd = [
            self.ytdlp_path,
            "--dump-json",
            "--skip-download",
            url,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise ClientError(f"Failed to get video metadata: {result.stderr}")

        return json.loads(result.stdout)

    def _validate_transcript_format(self, format: str) -> None:
        if format not in TRANSCRIPT_FORMATS:
            valid_formats = ", ".join(sorted(TRANSCRIPT_FORMATS))
            raise ClientError(f"Invalid transcript format: {format}. Valid values: {valid_formats}")

    def _convert_vtt_to_text(self, source_file: Path, target_file: Path) -> None:
        lines = []
        last_line = None

        for line in source_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == "WEBVTT" or stripped.startswith(("Kind:", "Language:", "NOTE ")):
                continue
            if "-->" in stripped:
                continue

            text = re.sub(r"<[^>]+>", "", stripped).strip()
            if not text or text == last_line:
                continue

            lines.append(text)
            last_line = text

        target_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def download_transcript(
        self,
        url: str,
        output_dir: str = ".",
        format: str = "srt",
        lang: str = "en",
        auto_sub: bool = True,
        manual_sub: bool = False,
    ) -> Dict:
        """
        Download transcript for a YouTube video.

        Args:
            url: YouTube video URL
            output_dir: Directory to save transcript
            format: Subtitle format (srt, vtt, txt)
            lang: Subtitle language code
            auto_sub: Download auto-generated subtitles
            manual_sub: Prefer manual subtitles over auto-generated

        Returns:
            Dictionary with download results

        Raises:
            ClientError: If download fails
        """
        self._validate_transcript_format(format)

        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        ytdlp_format = "vtt" if format == "txt" else format
        if ytdlp_format not in YT_DLP_SUBTITLE_FORMATS:
            valid_formats = ", ".join(sorted(YT_DLP_SUBTITLE_FORMATS))
            raise ClientError(f"Invalid yt-dlp subtitle format: {ytdlp_format}. Valid values: {valid_formats}")

        # Build yt-dlp command
        cmd = [
            self.ytdlp_path,
            "--skip-download",
            "--sub-lang", lang,
            "--convert-subs", ytdlp_format,
            "-o", f"{output_dir}/%(title)s.%(ext)s",
        ]

        # Add subtitle download flag
        if manual_sub:
            cmd.extend(["--write-sub", "--write-auto-sub"])
        elif auto_sub:
            cmd.append("--write-auto-sub")
        else:
            cmd.append("--write-sub")

        cmd.append(url)

        # Get metadata first
        try:
            metadata = self.get_video_metadata(url)
        except Exception as e:
            raise ClientError(f"Failed to get video info: {e}")

        # Run download
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise ClientError(f"Failed to download transcript: {result.stderr}")

        # Find the downloaded file - look for files created/modified in last few seconds
        import time
        title = metadata.get("title", "unknown")

        # Get all matching subtitle files in directory
        output_files = list(Path(output_dir).glob(f"*.{lang}.{ytdlp_format}"))

        # Find the most recently modified file
        actual_file = None
        if output_files:
            # Sort by modification time, newest first
            output_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
            actual_file = output_files[0]
        else:
            # Construct expected filename
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            actual_file = Path(output_dir) / f"{safe_title}.{lang}.{ytdlp_format}"

        if not actual_file.exists():
            raise ClientError(f"Transcript download completed but file was not found: {actual_file}")

        if format == "txt":
            text_file = actual_file.with_suffix(".txt")
            self._convert_vtt_to_text(actual_file, text_file)
            actual_file.unlink()
            actual_file = text_file

        return {
            "url": url,
            "title": metadata.get("title", "Unknown"),
            "duration": metadata.get("duration", 0),
            "file_path": str(actual_file),
            "file_size": actual_file.stat().st_size if actual_file.exists() else 0,
            "format": format,
            "language": lang,
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
        """
        Download transcripts for multiple YouTube videos.

        Args:
            urls: List of YouTube video URLs
            output_dir: Directory to save transcripts
            format: Subtitle format (srt, vtt, txt)
            lang: Subtitle language code
            auto_sub: Download auto-generated subtitles
            manual_sub: Prefer manual subtitles over auto-generated

        Returns:
            List of download results

        Raises:
            ClientError: If any download fails
        """
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

    def download_video(
        self,
        url: str,
        output_dir: str = ".",
        format: str = "mp4",
        quality: str = "best",
        max_resolution: Optional[str] = None,
    ) -> Dict:
        """
        Download a YouTube video.

        Args:
            url: YouTube video URL
            output_dir: Directory to save video
            format: Video container format (mp4, mkv, webm)
            quality: Quality selection (best, worst, or yt-dlp format code)
            max_resolution: Maximum video resolution preset (480p, 360p, 240p)

        Returns:
            Dictionary with download results

        Raises:
            ClientError: If download fails
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Build yt-dlp command
        format_spec = self._get_video_format_spec(quality, max_resolution)

        # Get metadata first
        metadata = self.get_video_metadata(url)

        cmd = [
            self.ytdlp_path,
            "-f", format_spec,
            "--merge-output-format", format,
            "-o", f"{output_dir}/%(title)s.%(ext)s",
            url,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise ClientError(f"Failed to download video: {result.stderr}")

        # Find the downloaded file — check requested format first, then any video file
        title = metadata.get("title", "")
        actual_file = None
        for ext in [format, "mkv", "mp4", "webm", "m4a"]:
            matches = list(Path(output_dir).glob(f"*.{ext}"))
            if matches:
                matches.sort(key=lambda f: f.stat().st_mtime, reverse=True)
                actual_file = matches[0]
                break

        return {
            "url": url,
            "title": metadata.get("title", "Unknown"),
            "duration": metadata.get("duration", 0),
            "file_path": str(actual_file) if actual_file else "unknown",
            "file_size": actual_file.stat().st_size if actual_file else 0,
            "format": actual_file.suffix.lstrip(".") if actual_file else format,
            "quality": max_resolution if max_resolution else quality,
        }

    def _get_video_format_spec(self, quality: str, max_resolution: Optional[str]) -> str:
        """Return the yt-dlp format selector for the requested video quality."""
        if max_resolution:
            if quality != "best":
                raise ClientError("Use --quality or --max-resolution, not both")
            if max_resolution not in MAX_RESOLUTION_FORMATS:
                raise ClientError(f"Invalid max resolution: {max_resolution}. Valid values: {MAX_RESOLUTION_VALUES}")
            return MAX_RESOLUTION_FORMATS[max_resolution]
        if quality == "best":
            return "bestvideo[vcodec^=avc]+bestaudio[acodec^=mp4a]/bestvideo+bestaudio/best"
        return quality

    def download_videos(
        self,
        urls: List[str],
        output_dir: str = ".",
        format: str = "mp4",
        quality: str = "best",
        max_resolution: Optional[str] = None,
    ) -> List[Dict]:
        """
        Download multiple YouTube videos.

        Args:
            urls: List of YouTube video URLs
            output_dir: Directory to save videos
            format: Video container format (mp4, mkv, webm)
            quality: Quality selection (best, worst, or yt-dlp format code)
            max_resolution: Maximum video resolution preset (480p, 360p, 240p)

        Returns:
            List of download results

        Raises:
            ClientError: If any download fails
        """
        results = []
        for url in urls:
            result = self.download_video(
                url=url,
                output_dir=output_dir,
                format=format,
                quality=quality,
                max_resolution=max_resolution,
            )
            results.append(result)
        return results

    def _resolve_channel_tab_url(self, channel: str, tab: str) -> str:
        """Resolve a channel handle or URL to a specific channel tab URL."""
        if channel.startswith("http"):
            channel_url = channel.rstrip("/")
            channel_url = re.sub(r"/(videos|shorts|streams)$", "", channel_url)
            return f"{channel_url}/{tab}"
        return f"https://www.youtube.com/@{channel}/{tab}"

    def get_video_title_key(self, title: str) -> str:
        """Normalize video titles for exact folder comparison."""
        return re.sub(r"\.f\d+$", "", title).strip()

    def get_folder_video_titles(self, folder_path: str) -> Set[str]:
        """Return normalized video titles already present in a folder."""
        folder = Path(folder_path)
        if not folder.is_dir():
            raise ClientError(f"Folder path not found: {folder_path}")

        video_extensions = {".mp4", ".mkv", ".webm", ".m4v", ".mov"}
        return {
            self.get_video_title_key(path.stem)
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in video_extensions
        }

    def get_channel_video_urls(
        self,
        channel: str,
        exclude_shorts: bool = False,
        limit: int = 0,
    ) -> List[str]:
        """
        Get all video URLs from a YouTube channel.

        Args:
            channel: Channel handle (e.g. 'myclassroom') or full channel URL
            exclude_shorts: If True, filter out YouTube Shorts
            limit: Max videos to discover (0 = all)

        Returns:
            List of video URLs

        Raises:
            ClientError: If channel extraction fails
        """
        videos = self.list_channel_videos(
            channel=channel,
            exclude_shorts=exclude_shorts,
            limit=limit,
        )
        return [video["url"] for video in videos]

    def get_channel_shorts_ids(self, channel: str, limit: int = 0) -> Set[str]:
        """Get video IDs from a channel's Shorts tab."""
        shorts_url = self._resolve_channel_tab_url(channel, "shorts")
        cmd = [
            self.ytdlp_path,
            "--flat-playlist",
            "--print", "id",
        ]
        if limit > 0:
            cmd.extend(["--playlist-end", str(limit)])
        cmd.append(shorts_url)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise ClientError(f"Failed to list channel shorts: {result.stderr}")

        return {line.strip() for line in result.stdout.strip().split("\n") if line.strip()}

    def list_channel_videos(
        self,
        channel: str,
        exclude_shorts: bool = False,
        limit: int = 0,
    ) -> List[Dict]:
        """
        List all videos from a YouTube channel with metadata.

        Args:
            channel: Channel handle or full channel URL
            exclude_shorts: If True, filter out YouTube Shorts
            limit: Max videos to discover (0 = all)

        Returns:
            List of video metadata dicts (title, url, duration, upload_date)

        Raises:
            ClientError: If channel extraction fails
        """
        channel_url = self._resolve_channel_tab_url(channel, "videos")

        cmd = [
            self.ytdlp_path,
            "--flat-playlist",
            "--print", "%(id)s\t%(title)s\t%(url)s\t%(duration)s\t%(upload_date)s",
        ]
        if limit > 0:
            cmd.extend(["--playlist-end", str(limit)])
        cmd.append(channel_url)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise ClientError(f"Failed to list channel videos: {result.stderr}")

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 5:
                raise ClientError(f"Unexpected yt-dlp channel row: {line}")

            video_id = parts[0]
            title = parts[1]
            url = parts[2]
            duration_str = parts[3]
            upload_date = parts[4]

            try:
                duration = int(float(duration_str)) if duration_str and duration_str != "NA" else 0
            except (ValueError, TypeError):
                duration = 0

            videos.append({
                "id": video_id,
                "title": title,
                "url": url,
                "duration": duration,
                "upload_date": upload_date,
            })

        if exclude_shorts:
            shorts_ids = self.get_channel_shorts_ids(channel, limit=limit)
            videos = [video for video in videos if video["id"] not in shorts_ids]

        if not videos:
            raise ClientError(f"No videos found for channel: {channel}")

        return videos

    def download_channel_videos(
        self,
        channel: str,
        output_dir: str = ".",
        format: str = "mp4",
        quality: str = "best",
        max_resolution: Optional[str] = None,
    ) -> List[Dict]:
        """
        Download all videos from a YouTube channel.

        Args:
            channel: Channel handle or URL
            output_dir: Directory to save videos
            format: Video container format
            quality: Quality selection
            max_resolution: Maximum video resolution preset (480p, 360p, 240p)

        Returns:
            List of download results

        Raises:
            ClientError: If download fails
        """
        urls = self.get_channel_video_urls(channel)
        return self.download_videos(
            urls=urls,
            output_dir=output_dir,
            format=format,
            quality=quality,
            max_resolution=max_resolution,
        )


# Module-level client instance - singleton pattern
_client: Optional[YoutubeClient] = None


def get_client() -> YoutubeClient:
    """Get or create the global YouTube client instance."""
    global _client
    if _client is None:
        _client = YoutubeClient()
    return _client
