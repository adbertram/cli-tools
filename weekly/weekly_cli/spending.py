"""Create and edit manual spending using the observed Weekly document shape."""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import requests
from cli_tools_shared.exceptions import ClientError
from .firestore import firestore_context, user_preferences, decode_value, list_documents
from .constants import DOCUMENT_ROOT, USER_DOCUMENT_ROOT


def amount_decimal(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal('0.01')):
            raise ValueError
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise ClientError('Amount must be positive and have at most two decimal places') from None


def amount_value(value):
    return float(amount_decimal(value))

def firestore_amount(value):
    if not isinstance(value, dict) or len(value) != 1 or next(iter(value), None) not in ('integerValue', 'doubleValue'):
        raise ValueError('Invalid Firestore amount')
    return amount_decimal(next(iter(value.values())))


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


def category_id(config, category, tags=None):
    matches = [tag for tag in (list_documents(config, 'tags') if tags is None else tags) if isinstance(tag.get('name'), str) and tag['name'].casefold() == category.casefold()]
    if len(matches) != 1:
        raise ClientError('Category must match exactly one saved category')
    return matches[0]['id']


def update(config, transaction_id, amount=None, title=None, category=None):
    if amount is None and title is None and category is None:
        raise ClientError('Provide --amount, --title or --category')
    fields = {}
    if amount is not None: fields['amount'] = {'doubleValue': amount_value(amount)}
    if title is not None:
        if not title.strip(): raise ClientError('Title must not be empty')
        fields['title'] = {'stringValue': title}
    try:
        http, url, headers, data = client_context(config)
        original = get_document(http, url, headers, data['user_id'], transaction_id)
        existing = original['fields']
        if existing.get('target', {}).get('stringValue') != 'SAFE_TO_SPEND' or 'transferDirection' in existing:
            raise ClientError('Only non-transfer safe-to-spend entries can be edited')
        if (amount is not None or title is not None) and (existing.get('isCash', {}).get('booleanValue') is not True or '__plaidTx' in existing):
            raise ClientError('Amount and title can only be edited on manual entries')
        if category is not None:
            fields['tagId'] = {'stringValue': category_id(config, category)}
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
        defaults = {'tagId': category_id(config, category), 'color': 'warning'}
        now = datetime.now(timezone.utc)
        fields = {'isCash':{'booleanValue':True}, 'amount':{'doubleValue':numeric}, 'title':{'stringValue':title}, 'target':{'stringValue':'SAFE_TO_SPEND'}, 'date':{'stringValue':day.isoformat()}, 'tagId':{'stringValue':defaults['tagId']}, 'color':{'stringValue':defaults['color']}, 'created':{'integerValue':str(int(now.timestamp()))}, 'createdTime':{'stringValue':now.strftime('%Y-%m-%dT%H:%M:%SZ')}}
        result = check_response(http.post(url, headers=headers, json={'fields':fields}, timeout=30, allow_redirects=False))
        expected = USER_DOCUMENT_ROOT + data['user_id'] + '/transactions/'
        if not result.get('name','').startswith(expected) or '/' in result['name'][len(expected):] or not isinstance(result.get('fields'),dict):
            raise ClientError('Weekly spending creation returned an unexpected identity')
        return export_doc(result)
    except requests.RequestException:
        raise ClientError('Weekly spending request failed') from None



def split(config, transaction_id, parts):
    if not transaction_id or '/' in transaction_id or transaction_id in ('.', '..'):
        raise ClientError('Invalid transaction ID')
    if len(parts) < 2:
        raise ClientError('Provide at least two parts')
    parsed = []
    for part in parts:
        amount, separator, category = part.partition(':')
        if not separator or not category.strip():
            raise ClientError('Each part must be AMOUNT:CATEGORY')
        parsed.append((amount_decimal(amount), category.strip()))
    try:
        http, url, headers, data = client_context(config)
        original = get_document(http, url, headers, data['user_id'], transaction_id)
        try:
            if datetime.fromisoformat(original['updateTime'].replace('Z', '+00:00')).utcoffset() is None:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ClientError('Original transaction version is invalid') from None
        existing = original['fields']
        try:
            bank_id = existing['__plaidTx']['mapValue']['fields']['id']['stringValue']
        except (KeyError, TypeError):
            bank_id = None
        if (existing.get('target', {}).get('stringValue') != 'SAFE_TO_SPEND'
                or 'transferDirection' in existing or existing.get('isSplit', {}).get('booleanValue') is True
                or existing.get('isCash', {}).get('booleanValue') is True
                or not isinstance(bank_id, str) or not bank_id.strip()):
            raise ClientError('Only unsplit bank-linked safe-to-spend expenses can be split')
        try:
            amount = firestore_amount(existing.get('amount'))
        except ValueError:
            raise ClientError('Original amount is invalid') from None
        if sum((item[0] for item in parsed), Decimal(0)) != amount:
            raise ClientError('Split amounts must equal the original amount')
        tags = list_documents(config, 'tags')
        categories = [category_id(config, name, tags) for _, name in parsed]
        ids = [transaction_id] + [uuid4().hex for _ in parsed[1:]]
        names = [USER_DOCUMENT_ROOT + data['user_id'] + '/transactions/' + ident for ident in ids]
        def changes(index):
            return {'amount':{'doubleValue':float(parsed[index][0])}, 'tagId':{'stringValue':categories[index]}, 'isSplit':{'booleanValue':True}}
        writes = [{'update':{'name':names[0], 'fields':changes(0)}, 'updateMask':{'fieldPaths':['amount','tagId','isSplit']}, 'currentDocument':{'updateTime':original['updateTime']}}]
        now = datetime.now(timezone.utc)
        for index in range(1, len(ids)):
            fields = {**existing, **changes(index), 'created':{'integerValue':str(int(now.timestamp()))}, 'createdTime':{'stringValue':now.strftime('%Y-%m-%dT%H:%M:%SZ')}}
            writes.append({'update':{'name':names[index], 'fields':fields}, 'currentDocument':{'exists':False}})
        reconciliation = 'Split outcome uncertain; check transaction IDs: ' + ', '.join(ids)
        try:
            response = http.post('https://firestore.googleapis.com/v1/' + DOCUMENT_ROOT + ':commit', headers=headers, json={'writes':writes}, timeout=30, allow_redirects=False)
        except requests.RequestException:
            raise ClientError(reconciliation) from None
        if response.status_code == 408 or response.status_code >= 500:
            raise ClientError(reconciliation)
        if not 200 <= response.status_code < 300:
            raise ClientError(f'Weekly split request failed (HTTP {response.status_code})')
        try:
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get('writeResults'), list) or len(body['writeResults']) != len(writes) or not all(isinstance(item, dict) for item in body['writeResults']):
                raise ValueError
            records = []
            for index, ident in enumerate(ids):
                doc = get_document(http, url, headers, data['user_id'], ident)
                if datetime.fromisoformat(doc['updateTime'].replace('Z', '+00:00')).utcoffset() is None:
                    raise ValueError
                expected = {**existing, **changes(0)} if index == 0 else writes[index]['update']['fields']
                actual = doc['fields']
                if any(actual.get(key) != value for key, value in expected.items() if key != 'amount'):
                    raise ValueError
                if firestore_amount(actual.get('amount')) != parsed[index][0]:
                    raise ValueError
                records.append(export_doc(doc))
            return records
        except (requests.RequestException, ValueError, TypeError, AttributeError, ClientError):
            raise ClientError(reconciliation) from None
    except requests.RequestException:
        raise ClientError('Weekly spending request failed') from None
