"""Bounded owning yt-dlp reads with an explicit original video timebase."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import re
import sys

from cli_tools_shared.bounded_read import run_bounded_read
from .client import ClientError
from .source_metadata import canonical_video

NORMALIZATION_VERSION = 'json3-single-window-continuation-v1'
TIMESTAMP_PRECISION_MS = 1
TERMINAL_CAPTION_OVERSHOOT_MS = 5000


class SourceAcquisitionError(ClientError):
    def __init__(self, code, category='transient', status=None, retry_after_seconds=None):
        super().__init__(code)
        self.code = code
        self.category = category
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        self.cleanup_failed = False


def fail(code, category='invalid_data'):
    raise SourceAcquisitionError(code, category)


def positive(value, maximum, *, integer=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
        fail('source_acquisition_bound_invalid', 'invalid_request')
    return value


def retry_after(value):
    if type(value) is not str or len(value) > 200:
        return None
    try:
        if re.fullmatch('[0-9]+', value.strip()):
            seconds = float(value)
        else:
            when = parsedate_to_datetime(value)
            if when.tzinfo is None:
                return None
            seconds = max(0, (when - datetime.now(timezone.utc)).total_seconds())
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def typed_provider_failure(error, operation):
    """Inspect the owning library's exception chain without forwarding text."""
    from yt_dlp.networking.exceptions import HTTPError
    seen = set()
    pending = [error]
    while pending and len(seen) < 16:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, HTTPError):
            status = current.status
            delay = retry_after(current.response.headers.get('Retry-After'))
            current.close()
            category = 'rate_limit' if status == 429 else 'access_denied' if status in (401, 403) else 'transient' if status >= 500 else 'upstream'
            return SourceAcquisitionError(operation + '_http_' + str(status), category, status, delay)
        for key in ('__cause__', '__context__', 'cause'):
            value = getattr(current, key, None)
            if isinstance(value, BaseException):
                pending.append(value)
        info = getattr(current, 'exc_info', None)
        if type(info) is tuple and len(info) == 3 and isinstance(info[1], BaseException):
            pending.append(info[1])
    return error if isinstance(error, SourceAcquisitionError) else SourceAcquisitionError(operation + '_read_failed')


def normalize_json3(raw, *, duration_seconds, max_cues):
    """Preserve every text event once; shorten only its display tail.

    Touching word offsets at the observed integer-ms precision merge adjacent
    same-window continuations. Independent/greater speech overlaps refuse.
    These are provider caption display times, not measured acoustic boundaries.
    """
    positive(duration_seconds, 86400)
    positive(max_cues, 20000, integer=True)
    if type(raw) is not dict or raw.get('wireMagic') != 'pb3' or type(raw.get('events')) is not list or len(raw['events']) > max_cues * 3:
        fail('source_caption_schema_changed')
    records = []
    previous_start = -1
    for index, event in enumerate(raw['events']):
        if type(event) is not dict:
            fail('source_caption_event_invalid')
        segs = event.get('segs', [])
        if type(segs) is not list or len(segs) > 512 or any(type(seg) is not dict or type(seg.get('utf8')) is not str for seg in segs):
            fail('source_caption_text_invalid')
        text = ''.join(seg['utf8'] for seg in segs).strip()
        if not text:
            continue  # Actual control/whitespace append events contain no words.
        if len(text.encode('utf-8')) > 2048 or any(ord(c) < 32 and c not in '\n\t\r' for c in text):
            fail('source_caption_text_invalid')
        start, length, window = event.get('tStartMs'), event.get('dDurationMs'), event.get('wWinId')
        if type(start) is not int or start < previous_start or type(length) is not int or length <= 0 or type(window) is not int or window < 0:
            fail('source_caption_timebase_invalid')
        if event.get('aAppend', 0) != 0:
            fail('source_caption_spoken_append_unsupported')
        end = start + length
        if start < 0 or end > duration_seconds * 1000:
            if start < 0 or start >= duration_seconds * 1000 or end - duration_seconds * 1000 > TERMINAL_CAPTION_OVERSHOOT_MS:
                fail('source_caption_outside_video')
            # A provider display tail may linger past the reported video end;
            # shorten only that bounded display tail to the exact video end.
            end = duration_seconds * 1000
        offsets = [seg.get('tOffsetMs', 0) for seg in segs]
        if any(type(offset) is not int or offset < 0 or offset >= length for offset in offsets) or offsets != sorted(offsets):
            fail('source_caption_word_offsets_invalid')
        records.append({'start': start, 'end': end, 'last_word': start + max(offsets), 'text': text,
                        'window': window, 'speaker_change': any(seg.get('isSpeakerChange') for seg in segs), 'events': [index],
                        'first_fragment': segs[0]['utf8'], 'last_fragment': segs[-1]['utf8']})
        previous_start = start
    if not records or len(records) > max_cues:
        fail('source_caption_cue_bound_exceeded')
    if len({record['window'] for record in records}) != 1:
        fail('source_caption_independent_windows_unsupported')
    merged = []
    for record in records:
        if merged and merged[-1]['last_word'] >= record['start']:
            previous = merged[-1]
            if previous['last_word'] - record['start'] > TIMESTAMP_PRECISION_MS or record['speaker_change'] or previous['window'] != record['window']:
                fail('source_caption_independent_speech_overlap')
            previous['end'] = max(previous['end'], record['end'])
            previous['last_word'] = max(previous['last_word'], record['last_word'])
            # The observed apostrophe fragment continues the next numeric
            # decade token without a word separator, e.g. "'" + "80s".
            join = '' if previous['last_fragment'].strip() == "'" and re.match(r'^[0-9]{2}s\b', record['first_fragment']) else ' '
            previous['text'] += join + record['text']
            previous['last_fragment'] = record['last_fragment']
            previous['events'] += record['events']
        else:
            merged.append(record.copy())
    result = []
    for index, record in enumerate(merged):
        end = min(record['end'], merged[index + 1]['start']) if index + 1 < len(merged) else record['end']
        if end <= record['start'] or record['last_word'] >= end:
            fail('source_caption_word_would_be_lost')
        result.append({'start': record['start'] / 1000, 'end': end / 1000, 'text': record['text']})
    return result


class QuietLogger:
    def debug(self, *args):
        pass
    info = warning = error = debug


def _request(request):
    expected = {'url', 'expected_video_id', 'duration_seconds', 'language', 'timeout_seconds', 'max_caption_bytes', 'max_cues', 'max_result_bytes'}
    if type(request) is not dict or set(request) != expected:
        fail('source_acquisition_request_invalid', 'invalid_request')
    identifier, canonical = canonical_video(request['url'])
    if identifier != request['expected_video_id'] or request['language'] != 'en':
        fail('source_caption_identity_or_language_invalid', 'invalid_request')
    positive(request['duration_seconds'], 86400)
    if positive(request['timeout_seconds'], 3600) <= .75:
        fail('source_acquisition_timeout_invalid', 'invalid_request')
    positive(request['max_caption_bytes'], 32 * 1024 * 1024, integer=True)
    positive(request['max_cues'], 20000, integer=True)
    positive(request['max_result_bytes'], 32 * 1024 * 1024, integer=True)
    return identifier, canonical


def _transcript(request):
    identifier, canonical = _request(request)
    import yt_dlp
    from yt_dlp.networking import Request
    from yt_dlp.networking.exceptions import HTTPError
    options = {'logger': QuietLogger(), 'quiet': True, 'noplaylist': True, 'cachedir': False,
               'writeautomaticsub': True, 'writesubtitles': False, 'subtitleslangs': ['en'], 'subtitlesformat': 'json3',
               'skip_download': True, 'socket_timeout': min(20, request['timeout_seconds']),
               'retries': 0, 'fragment_retries': 0, 'extractor_retries': 0}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(canonical, download=False)
            if type(info) is not dict or info.get('id') != identifier or info.get('duration') != request['duration_seconds']:
                fail('source_caption_metadata_identity_changed')
            selected = ydl.process_subtitles(identifier, info.get('subtitles'), info.get('automatic_captions'))
            if type(selected) is not dict or set(selected) != {'en'} or selected['en'].get('ext') != 'json3':
                fail('source_english_automatic_captions_unavailable', 'not_ready')
            caption = selected['en']
            # The owning extractor selects this ephemeral URL; never persist it.
            with ydl.urlopen(Request(caption['url'], headers=caption.get('http_headers', info.get('http_headers', {})))) as response:
                body = bytearray()
                while chunk := response.read(min(16384, request['max_caption_bytes'] - len(body) + 1)):
                    body.extend(chunk)
                    if len(body) > request['max_caption_bytes']:
                        fail('source_caption_response_exceeds_bound')
            try:
                raw = json.loads(body.decode('utf-8'))
            except (ValueError, UnicodeError):
                fail('source_caption_json_invalid')
            segments = normalize_json3(raw, duration_seconds=request['duration_seconds'], max_cues=request['max_cues'])
            return {'video_id': identifier, 'duration_seconds': request['duration_seconds'], 'language': 'en', 'segments': segments,
                    'observed_at': datetime.now(timezone.utc).isoformat(),
                    'provenance': {'kind': 'youtube_automatic_caption_display_times', 'url': canonical, 'format': 'json3',
                                   'raw_sha256': hashlib.sha256(body).hexdigest(), 'raw_bytes': len(body),
                                   'normalization_version': NORMALIZATION_VERSION, 'timebase': 'original_full_video_seconds'}}
    except HTTPError as error:
        status = error.status
        delay = retry_after(error.response.headers.get('Retry-After'))
        error.close()
        category = 'rate_limit' if status == 429 else 'access_denied' if status in (401, 403) else 'transient' if status >= 500 else 'upstream'
        raise SourceAcquisitionError('source_caption_http_' + str(status), category, status, delay) from None


def read_source_transcript(url, *, expected_video_id, duration_seconds, language, timeout_seconds, max_caption_bytes, max_cues, max_result_bytes):
    request = dict(url=url, expected_video_id=expected_video_id, duration_seconds=duration_seconds, language=language,
                   timeout_seconds=timeout_seconds, max_caption_bytes=max_caption_bytes, max_cues=max_cues, max_result_bytes=max_result_bytes)
    _request(request)
    result = run_bounded_read([sys.executable, '-m', __name__, json.dumps(request, separators=(',', ':'))],
                              timeout_seconds=timeout_seconds - .75, max_stdout_bytes=max_result_bytes)
    try:
        envelope = json.loads(result.stdout.decode('utf-8'))
        if result.returncode == 1 and type(envelope) is dict and set(envelope) == {'failure'}:
            failure = envelope['failure']
            if type(failure) is not dict or set(failure) != {'code', 'category', 'status', 'retry_after_seconds'}:
                raise ValueError()
            if not re.fullmatch('[a-z0-9_]{1,128}', failure['code']) or failure['category'] not in ('invalid_data', 'invalid_request', 'not_ready', 'access_denied', 'rate_limit', 'transient', 'upstream'):
                raise ValueError()
            status, delay = failure['status'], failure['retry_after_seconds']
            if status is not None and (type(status) is not int or not 100 <= status <= 599):
                raise ValueError()
            if delay is not None and (type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0):
                raise ValueError()
            raise SourceAcquisitionError(**failure)
        if result.returncode != 0 or type(envelope) is not dict or set(envelope) != {'result'}:
            raise ValueError()
        value = envelope['result']
        if type(value) is not dict or set(value) != {'video_id', 'duration_seconds', 'language', 'segments', 'observed_at', 'provenance'} or value.get('video_id') != expected_video_id or value.get('duration_seconds') != duration_seconds or value.get('language') != language:
            raise ValueError()
        provenance = value['provenance']
        if type(provenance) is not dict or set(provenance) != {'kind', 'url', 'format', 'raw_sha256', 'raw_bytes', 'normalization_version', 'timebase'}:
            raise ValueError()
        if provenance['kind'] != 'youtube_automatic_caption_display_times' or provenance['url'] != canonical_video(url)[1] or provenance['format'] != 'json3' or provenance['normalization_version'] != NORMALIZATION_VERSION or provenance['timebase'] != 'original_full_video_seconds':
            raise ValueError()
        if type(provenance['raw_sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', provenance['raw_sha256']) or type(provenance['raw_bytes']) is not int or not 0 < provenance['raw_bytes'] <= max_caption_bytes:
            raise ValueError()
        observed = datetime.fromisoformat(value['observed_at'])
        if observed.tzinfo is None:
            raise ValueError()
        segments = value['segments']
        if type(segments) is not list or not 0 < len(segments) <= max_cues:
            raise ValueError()
        previous = 0
        for cue in segments:
            if type(cue) is not dict or set(cue) != {'start', 'end', 'text'} or any(type(cue[k]) not in (int, float) or not math.isfinite(cue[k]) for k in ('start', 'end')):
                raise ValueError()
            if not previous <= cue['start'] < cue['end'] <= duration_seconds or type(cue['text']) is not str or not cue['text'].strip() or len(cue['text'].encode()) > 4096 or any(ord(c) < 32 and c not in '\n\t\r' for c in cue['text']):
                raise ValueError()
            previous = cue['end']
        return value
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise SourceAcquisitionError('source_caption_worker_schema_changed', 'invalid_data') from None


def main():
    try:
        if len(sys.argv) != 2 or len(sys.argv[1].encode()) > 8192:
            fail('source_acquisition_request_invalid', 'invalid_request')
        request = json.loads(sys.argv[1])
        value = _transcript(request)
        encoded = json.dumps({'result': value}, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if len(encoded) > request['max_result_bytes']:
            fail('source_caption_result_exceeds_bound')
        sys.stdout.buffer.write(encoded)
        return 0
    except Exception as error:
        error = typed_provider_failure(error, 'source_caption')
        print(json.dumps({'failure': {key: getattr(error, key) for key in ('code', 'category', 'status', 'retry_after_seconds')}}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
