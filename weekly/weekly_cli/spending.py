"""Create and edit manual spending using the observed Weekly document shape."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import requests
from cli_tools_shared.exceptions import ClientError
from .firestore import firestore_context, user_preferences, decode_value, list_documents
from .constants import USER_DOCUMENT_ROOT


def amount_value(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('0.01')):
            raise ValueError
        return float(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise ClientError('Amount must be positive and have at most two decimal places') from None


def client_context(config):
    http, user_url, headers, data = firestore_context(config)
    return http, user_url + '/transactions', headers, data


def check_response(response):
    if not 200 <= response.status_code < 300:
        raise ClientError(f'Weekly spending request failed (HTTP {response.status_code})')
    try:
        result = response.json()
    except ValueError:
        raise ClientError('Weekly spending response was not valid JSON') from None
    if not isinstance(result, dict):
        raise ClientError('Weekly spending response has an unexpected shape')
    return result


def get_document(http, url, headers, uid, transaction_id):
    response = http.get(url + '/' + quote(transaction_id, safe=''), headers=headers, timeout=30, allow_redirects=False)
    doc = check_response(response)
    prefix = USER_DOCUMENT_ROOT + uid + '/transactions/'
    if doc.get('name') != prefix + transaction_id or not isinstance(doc.get('fields'), dict) or not doc.get('updateTime'):
        raise ClientError('Weekly spending response has an unexpected identity or shape')
    return doc


def export_doc(doc):
    return {'id':doc['name'].rsplit('/',1)[-1], **{k:decode_value(v) for k,v in doc['fields'].items()}}


def update(config, transaction_id, amount=None, title=None):
    if amount is None and title is None:
        raise ClientError('Provide --amount or --title')
    fields = {}
    if amount is not None: fields['amount'] = {'doubleValue': amount_value(amount)}
    if title is not None:
        if not title.strip(): raise ClientError('Title must not be empty')
        fields['title'] = {'stringValue': title}
    try:
        http, url, headers, data = client_context(config)
        original = get_document(http, url, headers, data['user_id'], transaction_id)
        if original['fields'].get('target', {}).get('stringValue') != 'SAFE_TO_SPEND' or original['fields'].get('isCash', {}).get('booleanValue') is not True or '__plaidTx' in original['fields'] or 'transferDirection' in original['fields']:
            raise ClientError('Only manual safe-to-spend entries can be edited')
        params = [('currentDocument.updateTime', original['updateTime'])] + [('updateMask.fieldPaths', key) for key in fields]
        result = check_response(http.patch(url + '/' + quote(transaction_id, safe=''), headers=headers, params=params, json={'fields': fields}, timeout=30, allow_redirects=False))
        if result.get('name') != original['name'] or not isinstance(result.get('fields'),dict):
            raise ClientError('Weekly spending update returned an unexpected identity')
        return export_doc(result)
    except requests.RequestException:
        raise ClientError('Weekly spending request failed') from None


def create(config, title, amount, spending_date=None, category=None):
    if not title.strip(): raise ClientError('Title must not be empty')
    numeric = amount_value(amount)
    try:
        prefs = user_preferences(config)
        day = date.fromisoformat(spending_date) if spending_date else datetime.now(ZoneInfo(prefs['timezone'])).date()
    except (ValueError, KeyError, ZoneInfoNotFoundError):
        raise ClientError('Provide a valid YYYY-MM-DD date and account timezone') from None
    try:
        http, url, headers, data = client_context(config)
        matches = [tag for tag in list_documents(config, 'tags') if isinstance(tag.get('name'), str) and tag['name'].casefold() == category.casefold()]
        if len(matches) != 1:
            raise ClientError('Category must match exactly one saved category')
        defaults = {'tagId': matches[0]['id'], 'color': 'warning'}
        now = datetime.now(timezone.utc)
        fields = {'isCash':{'booleanValue':True}, 'amount':{'doubleValue':numeric}, 'title':{'stringValue':title}, 'target':{'stringValue':'SAFE_TO_SPEND'}, 'date':{'stringValue':day.isoformat()}, 'tagId':{'stringValue':defaults['tagId']}, 'color':{'stringValue':defaults['color']}, 'created':{'integerValue':str(int(now.timestamp()))}, 'createdTime':{'stringValue':now.strftime('%Y-%m-%dT%H:%M:%SZ')}}
        result = check_response(http.post(url, headers=headers, json={'fields':fields}, timeout=30, allow_redirects=False))
        expected = USER_DOCUMENT_ROOT + data['user_id'] + '/transactions/'
        if not result.get('name','').startswith(expected) or '/' in result['name'][len(expected):] or not isinstance(result.get('fields'),dict):
            raise ClientError('Weekly spending creation returned an unexpected identity')
        return export_doc(result)
    except requests.RequestException:
        raise ClientError('Weekly spending request failed') from None

