"""Create funds for future weekly contributions, optionally replacing a paid bill."""
from datetime import date
from uuid import uuid4
import requests
from cli_tools_shared.exceptions import ClientError
from .constants import DOCUMENT_ROOT, USER_DOCUMENT_ROOT
from .firestore import firestore_context, list_documents, encode_value
from .spending import check_response, export_doc, validate_transaction_version, get_document, firestore_amount
from .weeks import money


def read_document(http, user_url, headers, uid, collection, ident):
    doc = get_document(http, user_url + '/' + collection, headers, uid, ident, collection)
    validate_transaction_version(doc)
    return doc


def create(config, name, contribution, starting_balance, emoji, color,
           goal=None, replace_bill=None, settled_transaction=None, dry_run=False):
    if not isinstance(name, str) or not name.strip() or not isinstance(emoji, str) or not emoji.strip():
        raise ClientError('Fund name and emoji must not be empty')
    if color != 'gray':
        raise ClientError('Supported fund color: gray')
    contribution, starting_balance = money(contribution), money(starting_balance)
    if contribution < 0 or starting_balance < 0:
        raise ClientError('Contribution and starting balance must not be negative')
    values = dict(name=name.strip(), contributionAmount=float(contribution),
                  contributionInterval='weekly', startingBalance=float(starting_balance),
                  emoji=emoji.strip(), color=color)
    if goal is not None:
        goal = money(goal)
        if goal <= 0:
            raise ClientError('Goal must be positive')
        values['goalAmount'] = float(goal)
    if settled_transaction and not replace_bill:
        raise ClientError('--settled-transaction requires --replace-bill')
    for ident in (replace_bill, settled_transaction):
        if ident is not None and (not ident or '/' in ident or ident in ('.', '..')):
            raise ClientError('Invalid bill or transaction ID')
    try:
        if any(f.get('name', '').casefold() == values['name'].casefold() for f in list_documents(config, 'funds')):
            raise ClientError('A fund with this name already exists')
        http, user_url, headers, data = firestore_context(config)
        uid = data['user_id']
        fund_id = uuid4().hex
        fields = {k: encode_value(v) for k, v in values.items()}
        plans = [('funds', fund_id, fields, None)]
        if replace_bill:
            if starting_balance != 0:
                raise ClientError('Replacing a bill requires a zero starting balance')
            bill = read_document(http, user_url, headers, uid, 'items', replace_bill)
            b = bill['fields']
            if b.get('color') != {'stringValue': 'warning'} or b.get('archived') == {'booleanValue': True}:
                raise ClientError('Replacement requires an active expense bill')
            bill_changes = {'archived': encode_value(True)}
            plans.append(('items', replace_bill, bill_changes, bill))
            if settled_transaction:
                tx = read_document(http, user_url, headers, uid, 'transactions', settled_transaction)
                t = tx['fields']
                bank = t.get('__plaidTx', {}).get('mapValue', {}).get('fields', {})
                bank_id = bank.get('id', {}).get('stringValue')
                if (t.get('target') != {'stringValue': 'INITIAL'}
                        or t.get('color') != {'stringValue': 'warning'}
                        or not isinstance(bank_id, str) or not bank_id.strip()
                        or t.get('isCash') == {'booleanValue': True} or 'transferDirection' in t):
                    raise ClientError('Settlement requires an unreviewed bank expense')
                try:
                    firestore_amount(t.get('amount'))
                    firestore_amount(bank.get('amount'))
                except (ValueError, ClientError):
                    raise ClientError('Settlement requires a positive bank debit') from None
                tx_date = t.get('date', {}).get('stringValue')
                try:
                    if date.fromisoformat(tx_date).isoformat() != tx_date:
                        raise ValueError
                except (ValueError, TypeError):
                    raise ClientError('Settlement date is invalid') from None
                merchant = t.get('title', {}).get('stringValue')
                if not isinstance(merchant, str) or not merchant.strip():
                    raise ClientError('Settlement title is invalid')
                changes = {'latestTransactionDate': encode_value(tx_date),
                           'latestTransactionMerchant': encode_value(merchant)}
                bill_changes.update(changes)
                plans.append(('transactions', settled_transaction, {'target': encode_value('RECURRING'), 'itemId': encode_value(replace_bill)}, tx))
        writes = []
        for collection, ident, change, original in plans:
            write = {'update': {'name': USER_DOCUMENT_ROOT + uid + '/' + collection + '/' + ident, 'fields': change},
                     'currentDocument': {'updateTime': original['updateTime']} if original else {'exists': False}}
            if original:
                write['updateMask'] = {'fieldPaths': list(change)}
            writes.append(write)
        preview = {'fund': {'id': fund_id, **values}, 'current_week_credits_created': False,
                   'changes': [{'collection': col, 'id': ident, 'fields': {k: v for k, v in export_doc({'name': ident, 'fields': change}).items() if k != 'id'}} for col, ident, change, _ in plans]}
        if dry_run:
            return {'dry_run': True, **preview}
        uncertain = f'Fund creation outcome uncertain; read fund {fund_id} and the selected bill/transaction before retrying'
        try:
            response = http.post('https://firestore.googleapis.com/v1/' + DOCUMENT_ROOT + ':commit',
                                 headers=headers, json={'writes': writes}, timeout=30, allow_redirects=False)
            if response.status_code == 408 or response.status_code >= 500:
                raise ClientError(uncertain)
            if not 200 <= response.status_code < 300:
                raise ClientError(f'Weekly fund creation failed (HTTP {response.status_code})')
            body = check_response(response)
            if not isinstance(body.get('writeResults'), list) or len(body['writeResults']) != len(plans):
                raise ClientError(uncertain)
            for collection, ident, change, original in plans:
                actual = read_document(http, user_url, headers, uid, collection, ident)
                if actual['fields'] != {**(original['fields'] if original else {}), **change}:
                    raise ClientError(uncertain)
            return {'created': True, **preview}
        except requests.RequestException:
            raise ClientError(uncertain) from None
        except ClientError as error:
            if str(error).startswith('Weekly fund creation failed'):
                raise
            raise ClientError(uncertain) from None
    except requests.RequestException:
        raise ClientError('Weekly fund read failed') from None
