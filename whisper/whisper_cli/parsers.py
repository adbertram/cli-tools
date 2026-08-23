"""Parse whisper.cpp JSON output into the uniform transcript shape.

whisper.cpp (`whisper-cli -oj`) writes a JSON file whose ``transcription`` key
is a list of entries shaped like::

    {"text": " for this", "offsets": {"from": 0, "to": 480}, ...}

Offsets are in MILLISECONDS. This module converts each entry to the public
segment shape ``{"start": <sec>, "end": <sec>, "text": <str>}`` used by both
this wrapper and the ``openai-whisper`` wrapper, dropping entries whose text is
empty or whitespace.
"""

from typing import Optional


def _entry_to_segment(entry: dict) -> Optional[dict]:
    """Convert one whisper.cpp transcription entry to a segment dict.

    Returns ``None`` for entries whose text is empty/whitespace so callers can
    drop them.
    """
    text = entry.get("text", "")
    if not text or not text.strip():
        return None

    offsets = entry.get("offsets", {})
    start_ms = offsets.get("from", 0)
    end_ms = offsets.get("to", 0)
    return {
        "start": round(start_ms / 1000.0, 3),
        "end": round(end_ms / 1000.0, 3),
        "text": text.strip(),
    }


def parse_whisper_cpp_json(data: dict) -> list[dict]:
    """Extract non-empty segments from a parsed whisper.cpp JSON document.

    The ``transcription`` key is required; a missing key is a contract error
    (the wrapper invoked whisper.cpp with ``-oj`` and must get it back).
    """
    if "transcription" not in data:
        raise KeyError(
            "whisper.cpp JSON output is missing the 'transcription' key"
        )

    transcription = data["transcription"]
    segments: list[dict] = []
    for entry in transcription:
        segment = _entry_to_segment(entry)
        if segment is not None:
            segments.append(segment)
    return segments
