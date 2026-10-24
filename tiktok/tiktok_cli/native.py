"""Bounded capture of one native TikTok GET response; never invent empty feeds."""
import hashlib
import json
import time
from .client import ClientError


def observe_get(client, path, navigate):
    """Capture the page's first native GET response without repeating it."""
    page = client._page('/')
    session = page.begin_network_observation(method='GET', origin='https://www.tiktok.com', path=path)
    request_ids, statuses, digests = set(), {}, {}
    try:
        navigate(page)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            events = page.network_observations(session, method='GET', origin='https://www.tiktok.com', path=path, request_ids=tuple(request_ids))
            for event in events:
                request_id = event['request_id']
                if event['kind'] == 'request':
                    request_ids.add(request_id)
                    digests[request_id] = event.get("url_sha256")
                elif event['kind'] == 'response':
                    if not event['route_matches']:
                        raise ClientError('TikTok native feed response changed route.', code='native_feed_malformed', category='provider')
                    statuses[request_id] = event['status']
                elif event['kind'] == 'failed':
                    raise ClientError('TikTok native feed request failed.', code='native_feed_failed', category='transient')
                elif event['kind'] == 'finished':
                    status = statuses.get(request_id)
                    if status != 200:
                        raise ClientError('TikTok native feed request failed.', code=f'tiktok_http_{status}', category='auth' if status in (401,403) else 'rate_limit' if status == 429 else 'provider', status=status)
                    body = page.network_response_body(session, request_id)
                    if not body:
                        raise ClientError('TikTok native feed response is empty.', code='tiktok_empty_response', category='provider', status=status)
                    try:
                        payload = json.loads(body)
                    except ValueError:
                        raise ClientError('TikTok native feed response is not JSON.', code='tiktok_non_json_response', category='provider', status=status) from None
                    if not isinstance(payload, dict):
                        raise ClientError('TikTok native feed response is malformed.', code='native_feed_malformed', category='provider', status=status)
                    code = payload.get('status_code', payload.get('statusCode'))
                    if type(code) is not int:
                        raise ClientError('TikTok native feed status is malformed.', code='native_feed_malformed', category='provider', status=status)
                    if code != 0:
                        raise ClientError('TikTok native feed rejected the request.', code=f'tiktok_provider_{code}' if type(code) is int else 'tiktok_provider_status', category='provider', status=status)
                    urls = page.evaluate("(path) => performance.getEntriesByType('resource').map(e=>e.name).filter(x=>new URL(x).pathname === path)", path)
                    native_url = next((url for url in urls if isinstance(url, str) and hashlib.sha256(url.encode()).hexdigest() == digests.get(request_id)), None)
                    if not native_url:
                        raise ClientError('TikTok native feed request metadata is missing.', code='native_feed_malformed', category='provider')
                    return page, payload, native_url
            time.sleep(.25)
        raise ClientError('TikTok native feed response timed out.', code='native_feed_unavailable', category='transient')
    except ClientError:
        raise
    except Exception:
        raise ClientError('TikTok native feed capture failed.', code='native_feed_capture_failed', category='provider') from None
    finally:
        page.end_network_observation(session)

