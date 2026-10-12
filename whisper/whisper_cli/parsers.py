"""Parse whisper.cpp JSON output into the uniform transcript shape.

whisper.cpp (`whisper-cli -oj`) writes a JSON file whose ``transcription`` key
is a list of entries shaped like::

    {"text": " for this", "offsets": {"from": 0, "to": 480}, ...}

Offsets are in MILLISECONDS. This module converts each entry to the public
segment shape ``{"start": <sec>, "end": <sec>, "text": <str>}`` used by both
this wrapper and the ``openai-whisper`` wrapper, dropping entries whose text is
empty or whitespace.
"""

import re
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


def parse_whisper_cpp_words(data: dict) -> list[dict]:
    """Merge native timed subword tokens at their original whitespace boundaries.

    Segment text must match speech tokens exactly. Special-token markers are
    omitted only when that equality proves they are not transcript text.
    Every word bound comes from a real constituent token; no interpolation.
    """
    words=[]
    current=None
    for entry in data['transcription']:
        tokens=entry.get('tokens')
        if not isinstance(tokens,list):
            raise ValueError('whisper.cpp full JSON is missing token timestamps')
        speech=[]
        for token in tokens:
            text=token.get('text')
            if not isinstance(text,str):
                raise ValueError('whisper.cpp token text is malformed')
            if text.startswith('[_') and text.endswith(']'):
                continue
            speech.append(token)
        if ''.join(token['text'] for token in speech)!=entry.get('text'):
            raise ValueError('whisper.cpp speech tokens do not match segment text')
        for token in speech:
            offsets=token.get('offsets')
            if not isinstance(offsets,dict):
                raise ValueError('whisper.cpp token offsets are missing')
            start,end=offsets.get('from'),offsets.get('to')
            if type(start) is not int or type(end) is not int or not 0<=start<=end:
                raise ValueError('whisper.cpp token offsets are malformed')
            for part in re.findall(r'\s+|\S+',token['text']):
                if part.isspace():
                    if current is not None:
                        words.append(current);current=None
                elif current is None:
                    current={'start':round(start/1000,3),'end':round(end/1000,3),'text':part}
                else:
                    current['text']+=part
                    current['start']=min(current['start'],round(start/1000,3))
                    current['end']=max(current['end'],round(end/1000,3))
    if current is not None:words.append(current)
    return words
