"""Read confirmed Weekly-owned Firestore documents via the user-token API."""
from urllib.parse import quote
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
    if collection not in ('accounts', 'weekInstances', 'items', 'funds', 'tags'):
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
