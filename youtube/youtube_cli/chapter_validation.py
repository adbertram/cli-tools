"""Validation helpers for YouTube manual video chapters."""

import re
from typing import Optional

from cli_tools_shared import AIInstruction


MIN_CHAPTER_SECONDS = 10
TIMESTAMP_LINE_RE = re.compile(
    r"^\s*(?P<timestamp>\d+:\d{2}(?::\d{2})?)(?:\s+(?P<title>.+))?\s*$"
)
POSSIBLE_TIMESTAMP_RE = re.compile(r"^\s*\d+(?::\d+){1,2}\b")


def _issue(code: str, message: str, line: Optional[int] = None) -> dict:
    return {"code": code, "message": message, "line": line}


def _parse_timestamp(timestamp: str) -> int:
    parts = [int(part) for part in timestamp.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        if seconds >= 60:
            raise ValueError("seconds must be less than 60")
        return minutes * 60 + seconds
    if len(parts) == 3:
        hours, minutes, seconds = parts
        if minutes >= 60 or seconds >= 60:
            raise ValueError("minutes and seconds must be less than 60")
        return hours * 3600 + minutes * 60 + seconds
    raise ValueError("timestamp must be MM:SS or HH:MM:SS")


def validate_chapters_description(
    description: str,
    *,
    duration_seconds: Optional[int] = None,
) -> dict:
    """Validate YouTube manual chapter timestamp formatting in a description."""
    issues = []
    chapters = []

    for line_number, line in enumerate(description.splitlines(), start=1):
        if not POSSIBLE_TIMESTAMP_RE.match(line):
            continue

        match = TIMESTAMP_LINE_RE.match(line)
        if not match:
            issues.append(
                _issue(
                    "invalid_timestamp_format",
                    "Chapter timestamps must be MM:SS or HH:MM:SS at the start of a line.",
                    line_number,
                )
            )
            continue

        timestamp = match.group("timestamp")
        title = (match.group("title") or "").strip()
        if not title:
            issues.append(
                _issue(
                    "missing_chapter_title",
                    "Each chapter timestamp must be followed by a title.",
                    line_number,
                )
            )
            continue

        try:
            start_seconds = _parse_timestamp(timestamp)
        except ValueError as exc:
            issues.append(_issue("invalid_timestamp_format", str(exc), line_number))
            continue

        chapters.append(
            {
                "line": line_number,
                "timestamp": timestamp,
                "start_seconds": start_seconds,
                "title": title,
            }
        )

    if len(chapters) < 3:
        issues.append(
            _issue(
                "too_few_chapters",
                "YouTube chapters require at least three timestamped chapter lines.",
            )
        )

    if chapters and chapters[0]["start_seconds"] != 0:
        issues.append(
            _issue(
                "first_timestamp_not_zero",
                "The first chapter timestamp must start at 00:00.",
                chapters[0]["line"],
            )
        )

    for previous, current in zip(chapters, chapters[1:]):
        gap = current["start_seconds"] - previous["start_seconds"]
        if gap <= 0:
            issues.append(
                _issue(
                    "timestamps_not_ascending",
                    "Chapter timestamps must be listed in ascending order.",
                    current["line"],
                )
            )
        elif gap < MIN_CHAPTER_SECONDS:
            issues.append(
                _issue(
                    "chapter_too_short",
                    f"Each chapter must be at least {MIN_CHAPTER_SECONDS} seconds long.",
                    previous["line"],
                )
            )

    if duration_seconds is not None and chapters:
        last = chapters[-1]
        last_duration = duration_seconds - last["start_seconds"]
        if last_duration <= 0:
            issues.append(
                _issue(
                    "timestamp_after_duration",
                    "The last chapter timestamp must be before the video duration.",
                    last["line"],
                )
            )
        elif last_duration < MIN_CHAPTER_SECONDS:
            issues.append(
                _issue(
                    "last_chapter_too_short",
                    f"The final chapter must be at least {MIN_CHAPTER_SECONDS} seconds long.",
                    last["line"],
                )
            )

    return {
        "valid": len(issues) == 0,
        "chapter_count": len(chapters),
        "minimum_chapter_seconds": MIN_CHAPTER_SECONDS,
        "duration_seconds": duration_seconds,
        "duration_checked": duration_seconds is not None,
        "chapters": chapters,
        "issues": issues,
    }


def build_recommended_chapters_instruction(
    *,
    command: str,
    description: str,
    original_command: dict,
    validation: Optional[dict] = None,
) -> AIInstruction:
    """Build the shared AI handoff contract for chapter recommendation."""
    validation = validation or validate_chapters_description(description)
    return AIInstruction(
        tool="youtube",
        command=command,
        action_id="recommend_video_chapters",
        objective=(
            "Rewrite the supplied YouTube video description to include valid manual "
            "Video Chapters, then rerun the original command without "
            "--include-recommended-chapters."
        ),
        structured_context={
            "description": description,
            "validation": validation,
            "original_command": original_command,
            "youtube_chapter_rules": {
                "first_timestamp_seconds": 0,
                "minimum_chapters": 3,
                "minimum_chapter_seconds": MIN_CHAPTER_SECONDS,
                "timestamp_order": "ascending",
            },
        },
        narrative_context=(
            "The CLI can deterministically validate YouTube chapter formatting, "
            "but selecting useful chapter boundaries and labels requires AI judgment."
        ),
        allowed_tools=["cli", "file"],
        constraints=[
            "Preserve the original non-chapter description text.",
            "Add exactly one manual Video Chapters list.",
            "Do not invent exact timestamps without timing evidence from the video, transcript, or a timed outline.",
            "Do not upload or update the video until the revised description passes chapter validation.",
        ],
        success_criteria=[
            "The revised description has at least three chapter lines.",
            "The first chapter starts at 00:00.",
            f"Every chapter is at least {MIN_CHAPTER_SECONDS} seconds long.",
            "Chapter timestamps are in ascending order and each has a non-empty label.",
            "The original youtube command is rerun without --include-recommended-chapters and with the revised description.",
        ],
        verification_commands=[
            'youtube videos chapters validate --description "$CHAPTERED_DESCRIPTION"'
        ],
        follow_up_commands=[
            "Rerun the original youtube command without --include-recommended-chapters and with the chaptered description."
        ],
    )
