"""Read transactions from the observed Weekly CSV export."""
import csv
import io
import requests
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filters import apply_filters, apply_limit, validate_filters
from .session import refresh, secret
from .constants import CLOUD_FUNCTIONS_BASE, EXPORT_HEADER_NAMES

URL = CLOUD_FUNCTIONS_BASE + '/downloadTransactionsCsv'


def list_transactions(config, range_key=None, timezone_offset=None, limit=None, filters=None):
    token = refresh(config, with_token=True)
    data = secret(config, 'get')
    settings = data.get('export_settings')
    if not isinstance(settings, dict):
        raise ClientError('Import an observed transaction export with weekly auth import-export first')
    names = EXPORT_HEADER_NAMES
    if any(not isinstance(settings.get(name), str) for name in names) or settings['summaryonly'].lower() != 'false':
        raise ClientError('Saved transaction export settings are invalid')
    headers = {name: settings[name] for name in names}
    if range_key is not None:
        headers['rangekey'] = range_key
    if timezone_offset is not None:
        headers['timezoneoffset'] = str(timezone_offset)
    headers['authorization'] = 'Bearer ' + token
    headers['requesteduserid'] = data['user_id']
    client = requests.Session()
    client.trust_env = False
    try:
        response = client.get(URL, headers=headers, timeout=30, allow_redirects=False)
        if response.status_code != 200:
            raise ClientError(f'Transaction export failed (HTTP {response.status_code})')
        if not response.headers.get('content-type', '').lower().startswith('text/csv'):
            raise ClientError('Transaction export returned an unexpected content type')
        rows = csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')))
        if not rows.fieldnames or 'Id' not in rows.fieldnames:
            raise ClientError('Transaction export has an unexpected CSV header')
        result = list(rows)
        if any(None in row or any(value is None for value in row.values()) for row in result):
            raise ClientError('Transaction export contains malformed CSV rows')
        if filters:
            validate_filters(filters)
            result = apply_filters(result, filters)
        return apply_limit(result, limit)
    except (requests.RequestException, UnicodeError, csv.Error):
        raise ClientError('Transaction export request failed') from None
