"""Read confirmed Weekly-owned Firestore documents via the user-token API."""
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import requests
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, apply_limit, validate_filters
from .session import refresh, secret
from .constants import FIRESTORE_USER_URL, USER_DOCUMENT_ROOT

ROOT = FIRESTORE_USER_URL



def firestore_context(config):
    token = refresh(config, with_token=True)
    data = secret(config, 'get')
    client = requests.Session()
    client.trust_env = False
    user_url = ROOT + quote(data['user_id'], safe='')
    return client, user_url, {'Authorization': 'Bearer ' + token}, data


def decode_value(value):
    if not isinstance(value, dict) or len(value) != 1:
        raise ClientError('Firestore returned an invalid value')
    kind, val = next(iter(value.items()))
    if kind == 'nullValue': return None
    if kind == 'integerValue': return int(val)
    if kind == 'doubleValue': return float(val)
    if kind in ('booleanValue', 'stringValue', 'timestampValue', 'bytesValue', 'referenceValue', 'geoPointValue'): return val
    if kind == 'arrayValue': return [decode_value(v) for v in val.get('values', [])]
    if kind == 'mapValue': return {k: decode_value(v) for k, v in val.get('fields', {}).items()}
    raise ClientError('Firestore returned an unsupported value type')


def list_documents(config, collection, limit=None, filters=None):
    if collection not in ('accounts', 'weekInstances', 'items', 'funds', 'tags', 'transactions'):
        raise ClientError('Unsupported Weekly collection')
    client, user_url, headers, data = firestore_context(config)
    url = user_url + '/' + collection
    records = []
    page = None
    seen_pages = set()
    try:
        while True:
            params = {'pageSize': min(100, limit - len(records)) if limit and not filters else 100}
            if page: params['pageToken'] = page
            response = client.get(url, headers=headers, params=params, timeout=30, allow_redirects=False)
            if response.status_code != 200:
                raise ClientError(f'Weekly data request failed (HTTP {response.status_code})')
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get('documents', []), list):
                raise ClientError('Weekly data response has an unexpected shape')
            expected = USER_DOCUMENT_ROOT + data['user_id'] + '/' + collection + '/'
            for doc in body.get('documents', []):
                name = doc.get('name', '')
                if not name.startswith(expected) or '/' in name[len(expected):] or not isinstance(doc.get('fields', {}), dict):
                    raise ClientError('Weekly data response has an unexpected identity or shape')
                records.append({'id': name[len(expected):], **{key: decode_value(value) for key, value in doc.get('fields', {}).items()}})
            if limit and not filters and len(records) >= limit:
                return records
            next_page = body.get('nextPageToken')
            if not next_page:
                if filters:
                    validate_filters(filters)
                    records = apply_filters(records, filters)
                return apply_limit(records, limit)
            if not isinstance(next_page, str) or next_page in seen_pages:
                raise ClientError('Weekly data pagination failed')
            seen_pages.add(next_page)
            page = next_page
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise ClientError('Weekly data request failed') from None


def create_category(config, name, color, emoji):
    values = {'name': name.strip(), 'color': color.strip(), 'emoji': emoji.strip()}
    if not all(values.values()):
        raise ClientError('Category name, color and emoji must not be empty')
    if any(tag.get('name', '').casefold() == values['name'].casefold() for tag in list_documents(config, 'tags')):
        raise ClientError('A category with this name already exists')
    return create_document(config, 'tags', values)


def encode_value(value):
    if isinstance(value, bool): return {'booleanValue': value}
    if isinstance(value, str): return {'stringValue': value}
    if isinstance(value, int): return {'integerValue': str(value)}
    if isinstance(value, float): return {'doubleValue': value}
    if isinstance(value, dict): return {'mapValue': {'fields': {key: encode_value(item) for key, item in value.items()}}}
    raise ClientError('Unsupported Weekly document value')


def create_document(config, collection, values):
    resources = {'tags': ('category', 'categories'), 'weekInstances': ('week', 'weeks')}
    if collection not in resources:
        raise ClientError('Unsupported Weekly creation collection')
    noun, plural = resources[collection]
    client, user_url, headers, data = firestore_context(config)
    fields = {key: encode_value(value) for key, value in values.items()}
    try:
        response = client.post(user_url + '/' + collection, headers=headers, json={'fields': fields}, timeout=30, allow_redirects=False)
        if not 200 <= response.status_code < 300:
            raise ClientError(f'Weekly {noun} creation failed (HTTP {response.status_code})')
        doc = response.json()
        prefix = USER_DOCUMENT_ROOT + data['user_id'] + '/' + collection + '/'
        if not isinstance(doc, dict):
            raise ClientError(f'Weekly {noun} creation returned an unexpected response; check {plural} before retrying')
        path = doc.get('name', '')
        if not isinstance(path, str) or not path.startswith(prefix) or not path[len(prefix):] or '/' in path[len(prefix):] or doc.get('fields') != fields:
            raise ClientError(f'Weekly {noun} creation returned an unexpected identity or fields; check {plural} before retrying')
        return {'id': path[len(prefix):], **{key: decode_value(value) for key, value in doc['fields'].items()}}
    except (requests.RequestException, ValueError):
        raise ClientError(f'Weekly {noun} creation outcome uncertain; check {plural} before retrying') from None


def user_preferences(config):
    client, user_url, headers, data = firestore_context(config)
    uid = data['user_id']
    try:
        response = client.get(user_url, headers=headers, timeout=30, allow_redirects=False)
        if response.status_code != 200:
            raise ClientError(f'Weekly user settings request failed (HTTP {response.status_code})')
        doc = response.json()
        if doc.get('name') != USER_DOCUMENT_ROOT + uid or not isinstance(doc.get('fields', {}), dict):
            raise ClientError('Weekly user settings have an unexpected identity or shape')
        names = ('initialWeeklySpendingLimit', 'savingsAmount', 'startDayOfWeek', 'timezone', 'timezoneOffset')
        return {key: decode_value(doc['fields'][key]) for key in names if key in doc['fields']}
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise ClientError('Weekly user settings request failed') from None


def current_week(config, preferences=None, weeks=None):
    preferences = user_preferences(config) if preferences is None else preferences
    weeks = list_documents(config, 'weekInstances') if weeks is None else weeks
    try:
        today = datetime.now(ZoneInfo(preferences['timezone'])).date()
        current = [week for week in weeks if datetime.fromisoformat(week['startDate'].replace('Z', '+00:00')).date() <= today <= datetime.fromisoformat(week['endDate'].replace('Z', '+00:00')).date()]
    except (ValueError, KeyError, AttributeError, TypeError, ZoneInfoNotFoundError):
        raise ClientError('Weekly week dates or timezone are missing or invalid') from None
    if len(current) != 1:
        raise ClientError('No unique current week found')
    return current[0]
