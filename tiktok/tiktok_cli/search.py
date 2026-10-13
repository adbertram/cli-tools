"""Bounded hashtag search through TikTok's observed native search endpoint."""
import json
import re
import time
from urllib.parse import urlencode, urlsplit, parse_qsl
from datetime import datetime, timezone

from .client import ClientError, normalize_posted_video

SEARCH_PATH = '/api/search/general/full/'
_SIGNATURE_FIELDS = {'msToken', 'X-Bogus', 'X-Gnarly', 'X-Dynosaur'}


def normalize_hashtag(value):
    """Accept one hashtag, retaining Unicode letters and numbers."""
    value = value.strip().removeprefix('#') if isinstance(value, str) else ''
    if not value or len(value) > 100 or not re.fullmatch(r'\w+', value):
        raise ClientError('Hashtag must contain 1–100 letters, numbers, or underscores.', code='invalid_hashtag', category='validation')
    return value.casefold()


def _count(raw, key):
    value = raw.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ClientError('TikTok search contains an invalid measurement.', code='search_malformed', category='provider')
    return value


def normalize_search_video(raw, hashtag):
    """Require exact native hashtag or caption match; preserve missing counts."""
    if not isinstance(raw, dict):
        raise ClientError('TikTok search video is malformed.', code='search_malformed', category='provider')
    caption = raw.get('desc')
    tags = raw.get('textExtra') or []
    if not isinstance(caption, str) or not isinstance(tags, list):
        raise ClientError('TikTok search caption or hashtags are malformed.', code='search_malformed', category='provider')
    exact = any(isinstance(tag, dict) and isinstance(tag.get('hashtagName'), str) and tag['hashtagName'].casefold() == hashtag for tag in tags)
    if not exact and hashtag not in [tag.casefold() for tag in re.findall(r'(?<!\w)#(\w+)', caption)]:
        return None
    row = normalize_posted_video(raw)
    if not re.fullmatch(r'[1-9][0-9]*', row['id']) or not isinstance(row['author'], str) or not row['author']:
        raise ClientError('TikTok search video identity is malformed.', code='search_malformed', category='provider')
    stats = raw.get('stats')
    video = raw.get('video')
    stats = {} if stats is None else stats
    video = {} if video is None else video
    if not isinstance(stats, dict) or not isinstance(video, dict):
        raise ClientError('TikTok search measurements are malformed.', code='search_malformed', category='provider')
    if type(row['created_at']) is not int or row['created_at'] < 0:
        raise ClientError('TikTok search creation time is malformed.', code='search_malformed', category='provider')
    row.update({name: _count(stats, key) for name, key in {'views':'playCount','likes':'diggCount','comments':'commentCount','shares':'shareCount','saves':'collectCount'}.items()})
    row['duration'] = _count(video, 'duration')
    row['matched_hashtags'] = [hashtag]
    return row


def _open_search(client, hashtag):
    """Capture the page's first native GET response without repeating it."""
    page = client._page('/')
    session = page.begin_network_observation(method='GET', origin='https://www.tiktok.com', path=SEARCH_PATH)
    request_ids, statuses = set(), {}
    try:
        page.goto(client.config.base_url.rstrip('/') + '/search?' + urlencode({'q':'#'+hashtag}))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            events = page.network_observations(session, method='GET', origin='https://www.tiktok.com', path=SEARCH_PATH, request_ids=tuple(request_ids))
            for event in events:
                request_id = event['request_id']
                if event['kind'] == 'request':
                    request_ids.add(request_id)
                elif event['kind'] == 'response':
                    if not event['route_matches']:
                        raise ClientError('TikTok native search response changed route.', code='search_malformed', category='provider')
                    statuses[request_id] = event['status']
                elif event['kind'] == 'failed':
                    raise ClientError('TikTok native search request failed.', code='search_native_failed', category='transient')
                elif event['kind'] == 'finished':
                    status = statuses.get(request_id)
                    if status != 200:
                        raise ClientError('TikTok native search request failed.', code=f'tiktok_http_{status}', category='auth' if status in (401,403) else 'rate_limit' if status == 429 else 'provider', status=status)
                    body = page.network_response_body(session, request_id)
                    if not body:
                        raise ClientError('TikTok native search response is empty.', code='tiktok_empty_response', category='provider', status=status)
                    try:
                        payload = json.loads(body)
                    except ValueError:
                        raise ClientError('TikTok native search response is not JSON.', code='tiktok_non_json_response', category='provider', status=status) from None
                    if not isinstance(payload, dict):
                        raise ClientError('TikTok native search response is malformed.', code='search_malformed', category='provider', status=status)
                    code = payload.get('status_code', payload.get('statusCode'))
                    if code not in (None,0):
                        raise ClientError('TikTok native search rejected the request.', code=f'tiktok_provider_{code}' if type(code) is int else 'tiktok_provider_status', category='provider', status=status)
                    native_url = page.evaluate("() => performance.getEntriesByType('resource').map(e=>e.name).find(x=>new URL(x).pathname === '/api/search/general/full/') || null")
                    if not native_url:
                        raise ClientError('TikTok native search request metadata is missing.', code='search_malformed', category='provider')
                    return page, payload, native_url
            time.sleep(.25)
        raise ClientError('TikTok native search response timed out.', code='search_unavailable', category='transient')
    except ClientError:
        raise
    except Exception:
        raise ClientError('TikTok native search capture failed.', code='search_capture_failed', category='provider') from None
    finally:
        page.end_network_observation(session)


def search_hashtag_videos(client, hashtag, *, limit=30, max_pages=2):
    """Return at most limit exact hashtag videos in at most max_pages requests.

    A bounded sample is not an exhaustive hashtag inventory. TikTok search ranks
    results and may personalize them. Endpoint errors never become empty feeds.
    """
    hashtag = normalize_hashtag(hashtag)
    if type(limit) is not int or not 1 <= limit <= 300 or type(max_pages) is not int or not 1 <= max_pages <= 20:
        raise ClientError('Search limit must be 1–300; max_pages must be 1–20.', code='invalid_search_bounds', category='validation')
    page, initial_payload, native_url = _open_search(client, hashtag)
    url = urlsplit(native_url)
    if url.hostname != 'www.tiktok.com' or url.path != SEARCH_PATH:
        raise ClientError('TikTok search request origin is invalid.', code='search_malformed', category='provider')
    params = {key:value for key,value in parse_qsl(url.query) if key not in _SIGNATURE_FIELDS}
    if params.get('keyword', '').casefold() != '#'+hashtag:
        raise ClientError('TikTok search request does not match the requested hashtag.', code='search_malformed', category='provider')
    rows, seen, cursors = [], set(), set()
    cursor = 0
    for page_index in range(max_pages):
        params.update(cursor=str(cursor), offset=str(cursor))
        try:
            payload = initial_payload if page_index == 0 else client._fetch_json(page, SEARCH_PATH+'?'+urlencode(params))
        except ClientError as exc:
            raise ClientError('TikTok public search request failed.', code=exc.code, category=exc.category, status=exc.status, retry_after_seconds=exc.retry_after_seconds) from None
        observed_at = datetime.now(timezone.utc).isoformat()
        data, more, next_cursor = payload.get('data'), payload.get('has_more'), payload.get('cursor')
        if not isinstance(data, list) or more not in (0, 1, False, True) or type(next_cursor) is not int or next_cursor < 0:
            raise ClientError('TikTok search response is malformed.', code='search_malformed', category='provider')
        for entry in data:
            if not isinstance(entry, dict):
                raise ClientError('TikTok search entry is malformed.', code='search_malformed', category='provider')
            if entry.get('type') != 1:
                continue
            row = normalize_search_video(entry.get('item'), hashtag)
            if row and row['id'] not in seen:
                row['observed_at'] = observed_at
                row['provenance'] = 'https://www.tiktok.com' + SEARCH_PATH
                seen.add(row['id']); rows.append(row)
            if len(rows) >= limit:
                return rows
        if not more:
            return rows
        if not params.get('search_id'):
            extra = payload.get('extra')
            search_id = extra.get('logid') if isinstance(extra, dict) else None
            if not isinstance(search_id, str) or not search_id:
                raise ClientError('TikTok search continuation identity is missing.', code='search_malformed', category='provider')
            params['search_id'] = search_id
        if next_cursor <= cursor or next_cursor in cursors:
            raise ClientError('TikTok search pagination did not advance.', code='search_pagination_stalled', category='provider')
        cursors.add(cursor); cursor = next_cursor
    return rows
