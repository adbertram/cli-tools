"""Ignore unreviewed bank transactions using the native IGNORED target."""
from urllib.parse import quote
import requests
from cli_tools_shared.exceptions import ClientError
from .spending import client_context, get_document, export_doc, check_response, validate_transaction_version


TARGET_IGNORED = 'IGNORED'

def ignore(config, transaction_id, dry_run=False):
    if not transaction_id or '/' in transaction_id or transaction_id in ('.', '..'):
        raise ClientError('Invalid transaction ID')
    try:
        http, url, headers, data = client_context(config)
        original = get_document(http, url, headers, data['user_id'], transaction_id)
    except requests.RequestException:
        raise ClientError('Weekly transaction read failed') from None
    fields = original['fields']
    target = fields.get('target', {}).get('stringValue')
    if target not in ('INITIAL', TARGET_IGNORED):
        raise ClientError('Only unreviewed bank transactions can be ignored')
    bank_id = fields.get('__plaidTx', {}).get('mapValue', {}).get('fields', {}).get('id', {}).get('stringValue')
    if not isinstance(bank_id, str) or not bank_id.strip() or 'transferDirection' in fields or 'isCash' in fields:
        raise ClientError('Only unreviewed bank transactions can be ignored')
    validate_transaction_version(original)
    if dry_run:
        return {'dry_run': True, 'changed': target != TARGET_IGNORED,
                'transaction': export_doc(original), 'changes': {'target': TARGET_IGNORED}}
    if target == TARGET_IGNORED:
        return {'changed': False, 'transaction': export_doc(original)}
    expected = {**fields, 'target': {'stringValue': TARGET_IGNORED}}
    uncertain = f'Ignore outcome uncertain; run weekly transactions ignore {transaction_id} --dry-run before retrying'
    try:
        response = http.patch(url + '/' + quote(transaction_id, safe=''), headers=headers,
                              params=[('currentDocument.updateTime', original['updateTime']),
                                      ('updateMask.fieldPaths', 'target')],
                              json={'fields': {'target': {'stringValue': TARGET_IGNORED}}},
                              timeout=30, allow_redirects=False)
        if response.status_code == 408 or response.status_code >= 500:
            raise ClientError(uncertain)
        if not 200 <= response.status_code < 300:
            raise ClientError(f'Weekly ignore request failed (HTTP {response.status_code})')
        result = check_response(response)
        if result.get('name') != original['name'] or result.get('fields') != expected:
            raise ClientError(uncertain)
        verified = get_document(http, url, headers, data['user_id'], transaction_id)
        if verified['fields'] != expected:
            raise ClientError(uncertain)
        return {'changed': True, 'transaction': export_doc(verified)}
    except requests.RequestException:
        raise ClientError(uncertain) from None
    except ClientError as error:
        if str(error).startswith('Weekly ignore request failed'):
            raise
        raise ClientError(uncertain) from None
