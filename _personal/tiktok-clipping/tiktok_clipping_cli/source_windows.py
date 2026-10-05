"""Complete, deterministic source-time windows; windows remain one video."""
from .safety import SafetyError, canonical, digest, keys, number, string

MAX_WINDOW_SECONDS = 600
MAX_WINDOW_BYTES = 24576
MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024


def build_windows(segments, duration_seconds):
    """Retain every ordered measured cue exactly once, without changing times."""
    number(duration_seconds, 1, 86400)
    if not isinstance(segments, list) or not 1 <= len(segments) <= 10000:
        raise SafetyError('catalog_timed_transcript_required')
    try:size = len(canonical(segments).encode())
    except (TypeError,ValueError):raise SafetyError('catalog_transcript_invalid') from None
    if size > MAX_TRANSCRIPT_BYTES:
        raise SafetyError('catalog_transcript_exceeds_bound')
    result, current, previous = [], [], 0
    def payload(cues):
        return {'transcript': ' '.join(cue['text'] for cue in cues), 'transcript_segments': cues}
    def finish(cues):
        data = payload(cues)
        return {**data, 'window_id': digest(data), 'start_seconds': cues[0]['start_seconds'],
                'end_seconds': cues[-1]['end_seconds'], 'ordinal': len(result)}
    for cue in segments:
        keys(cue, {'start_seconds', 'end_seconds', 'text'})
        start = number(cue['start_seconds'], previous, duration_seconds)
        end = number(cue['end_seconds'], start, duration_seconds)
        string(cue['text'], 2000)
        if end <= start or end - start > MAX_WINDOW_SECONDS:
            raise SafetyError('catalog_caption_interval_unsupported')
        candidate = current + [cue]
        if current and (end - current[0]['start_seconds'] > MAX_WINDOW_SECONDS or
                        len(canonical(payload(candidate)).encode()) > MAX_WINDOW_BYTES):
            result.append(finish(current));current = []
        current.append(dict(cue))
        if len(canonical(payload(current)).encode()) > MAX_WINDOW_BYTES:
            raise SafetyError('catalog_caption_window_exceeds_bound')
        previous = end
    if current:result.append(finish(current))
    return result


def window_record(window):
    """The admitted range is explicit; model cuts keep the original timebase."""
    return {key: window[key] for key in ('window_id', 'ordinal', 'start_seconds', 'end_seconds')}


def require_window_cuts(window, cuts):
    if any(cut['start_seconds'] < window['start_seconds'] or cut['end_seconds'] > window['end_seconds'] for cut in cuts):
        raise SafetyError('proposal_outside_admitted_source_window')
