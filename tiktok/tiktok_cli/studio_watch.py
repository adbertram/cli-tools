"""Read owned Studio watch analytics from the native insight API.

Observed 2026-10-12: native overview request includes the history insight types;
removing them suppresses realtime scalar fields. Preserve that observed batch.
Times in scalar metrics are seconds; retention timestamps are milliseconds.
"""
import json
import math
from datetime import datetime, timezone
from urllib.parse import urlencode

from .studio import StudioContractError, parse_response, positive_decimal_id

PATH = '/aweme/v2/data/insight/'
INSIGHTS = (
    'video_info', 'item_search_terms', 'video_traffic_source_percent_realtime',
    'video_retention_rate_realtime', 'video_info', 'video_view_realtime',
    'video_total_duration_realtime', 'video_per_duration_realtime',
    'video_finish_rate_realtime', 'video_new_follower_realtime', 'photo_viewed',
    'video_total_duration_realtime', 'video_new_followers',
    'photo_retention_rate_history_7d', 'video_vv_history_7d', 'video_vv_history_48_hours',
)
FIELDS = {
    'total_watch_time_seconds': 'video_total_duration_realtime',
    'average_watch_time_seconds': 'video_per_duration_realtime',
    'completion_rate': 'video_finish_rate_realtime',
    'retention': 'video_retention_rate_realtime',
}
FETCH = r"""async (path) => {
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
 try {
  const r=await fetch(path,{credentials:'include',redirect:'error',signal:controller.signal});
  if(r.status!==200){await r.body?.cancel();return {status:r.status,body:null};}
  const reader=r.body.getReader(),chunks=[];let size=0;
  try {while(true){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;
   if(size>2097152){await reader.cancel();return {status:200,body:null};}chunks.push(part.value);}}
  finally {reader.releaseLock();}
  const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
  return {status:200,body:new TextDecoder('utf-8',{fatal:true}).decode(bytes)};
 }catch(_){return {status:0,body:null};}finally{clearTimeout(timer);}
}"""


def number(value, maximum=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0 and (maximum is None or value <= maximum)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('invalid measurement')
    return value


def normalize(payload, identity, video_id):
    """Whitelist measurements, reject wrong owners, preserve provider unknowns."""
    if not isinstance(payload, dict) or type(payload.get('status_code')) is not int or payload['status_code'] != 0:
        raise StudioContractError('TikTok Studio watch response was not successful.')
    info = payload.get('video_info')
    if not isinstance(info, dict) or info.get('aweme_id') != video_id or not isinstance(info.get('author'), dict) or info['author'].get('uid') != identity['account_id']:
        raise StudioContractError('TikTok Studio watch post or owner did not match the requested identity.')
    metrics, unavailable = {}, {}
    for name, field in FIELDS.items():
        metrics[name] = None
        wrapper = payload.get(field)
        value = wrapper.get('value') if isinstance(wrapper, dict) else None
        if not isinstance(value, dict) or type(value.get('status')) is not int or value['status'] != 0:
            unavailable[name] = 'processing_or_unavailable'
            continue
        if wrapper.get('is_data_delay') is not False:
            unavailable[name] = 'delayed_or_unverified'
            continue
        try:
            if name != 'retention':
                metrics[name] = number(value.get('value'), 1 if name == 'completion_rate' else None)
                continue
            points = value.get('list')
            if not isinstance(points, list) or not 2 <= len(points) <= 10000:
                raise ValueError('invalid retention curve')
            curve = []
            for point in points:
                if not isinstance(point, dict):
                    raise ValueError('invalid retention point')
                timestamp = point.get('timestamp')
                if not isinstance(timestamp, str) or not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 12:
                    raise ValueError('invalid retention timestamp')
                seconds = int(timestamp) / 1000
                if curve and seconds <= curve[-1]['time_seconds']:
                    raise ValueError('unordered retention timestamps')
                curve.append({'time_seconds': seconds, 'retention_rate': number(point.get('value'), 1)})
            metrics[name] = curve
        except ValueError:
            unavailable[name] = 'malformed_measurement'
    extra = payload.get('extra')
    if not isinstance(extra, dict) or extra.get('fatal_item_ids') != []:
        raise StudioContractError('TikTok Studio watch response has incomplete measurement provenance.')
    server_time = extra.get('now')
    if type(server_time) is not int or server_time <= 0:
        raise StudioContractError('TikTok Studio watch timestamp is malformed.')
    return {'id': video_id, **{k: identity[k] for k in ('account_id', 'username', 'profile')},
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'server_timestamp_ms': server_time, 'provenance': 'https://www.tiktok.com' + PATH,
            'metrics': metrics, 'unavailable': unavailable,
            'watch_metrics_error': '; '.join(f'{k}: {v}' for k, v in unavailable.items()) or None}


ANALYTICS_URL = 'https://www.tiktok.com/tiktokstudio/analytics/{}?qa_enter_from=analytics'
MAX_BATCH_IDS = 1000


def _fetch(page, identity, video_id):
    """One same-origin insight fetch for one post; any open Studio page serves every ID."""
    query = urlencode({'aid': '1988', 'type_requests': json.dumps(
        [{'insigh_type': kind, 'aweme_id': video_id} for kind in INSIGHTS], separators=(',', ':'))})
    response = page.evaluate(FETCH, PATH + '?' + query)
    if not isinstance(response, dict) or response.get('status') != 200 or not isinstance(response.get('body'), str):
        raise StudioContractError('TikTok Studio watch request failed, timed out, or exceeded its size bound.')
    return normalize(parse_response(response['body']), identity, video_id)


def _verified(client, username, expected_account_id, read_posts):
    """Bind every read to one owner identity checked before and after."""
    identity = client.get_account(expected_username=username, expected_account_id=expected_account_id)
    result = read_posts(identity)
    checked = client.get_account(expected_username=username, expected_account_id=expected_account_id)
    if any(checked[k] != identity[k] for k in ('account_id', 'username', 'profile')):
        raise StudioContractError('TikTok Studio watch owner changed during the read.')
    return result


def read(client, username, video_id, expected_account_id):
    if not positive_decimal_id(video_id) or not positive_decimal_id(expected_account_id):
        raise StudioContractError('TikTok Studio watch requires exact positive post and account IDs.')
    return _verified(client, username, expected_account_id, lambda identity: _fetch(
        client._get_browser().get_page(ANALYTICS_URL.format(video_id)), identity, video_id))


def read_many(client, username, video_ids, expected_account_id):
    """Read many owned posts in one browser page; one post's failure never aborts the batch."""
    if type(video_ids) is not list or not 1 <= len(video_ids) <= MAX_BATCH_IDS:
        raise StudioContractError('TikTok Studio watch batch requires between 1 and 1000 exact post IDs.')
    if any(not positive_decimal_id(v) for v in video_ids) or len(set(video_ids)) != len(video_ids) \
            or not positive_decimal_id(expected_account_id):
        raise StudioContractError('TikTok Studio watch requires unique exact positive post and account IDs.')

    def read_posts(identity):
        page = client._get_browser().get_page(ANALYTICS_URL.format(video_ids[0]))
        records, errors = [], {}
        for video_id in video_ids:
            try:
                records.append(_fetch(page, identity, video_id))
            except ValueError as error:  # StudioContractError included
                errors[video_id] = str(error)
        return {'records': records, 'errors': errors, 'requested': len(video_ids)}
    return _verified(client, username, expected_account_id, read_posts)
