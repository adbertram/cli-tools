"""Create completed historical weeks using the observed native record shape."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from urllib.parse import quote
import requests

from cli_tools_shared.exceptions import ClientError
from .firestore import create_document, current_week, decode_value, firestore_context, list_documents, user_preferences
from .constants import USER_DOCUMENT_ROOT


def week_dates(start_date, end_date, existing_weeks):
    try:
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        if start.isoformat() != start_date or end.isoformat() != end_date or start > end:
            raise ValueError
    except (TypeError, ValueError):
        raise ClientError('Provide ordered start and end dates in YYYY-MM-DD format') from None
    try:
        for week in existing_weeks:
            old_start = datetime.fromisoformat(week['startDate'].replace('Z', '+00:00')).date()
            old_end = datetime.fromisoformat(week['endDate'].replace('Z', '+00:00')).date()
            if start <= old_end and old_start <= end:
                raise ClientError('Requested dates overlap an existing week')
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ClientError('An existing week has missing or invalid dates') from None
    return start, end


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount != amount.quantize(Decimal('0.01')):
            raise ValueError
        if Decimal(str(float(amount))) != amount:
            raise ValueError
        return amount
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        raise ClientError('Amount must be finite exact cents representable by Weekly') from None


def require_completed_week(end, today):
    if end >= today:
        raise ClientError('Current and upcoming week creation is not supported; only completed past weeks have been verified')


def historical_week(start_date, end_date, spending_limit, plan, existing_weeks, transactions, today):
    start, end = week_dates(start_date, end_date, existing_weeks)
    allowance = money(spending_limit)
    require_completed_week(end, today)
    if not isinstance(plan, str) or not plan.strip():
        raise ClientError('Provide the explicit Weekly plan recorded for this week')
    summary = Decimal(0)
    for transaction in transactions:
        try:
            day = date.fromisoformat(transaction['date'])
        except (KeyError, TypeError, ValueError):
            raise ClientError('A transaction has a missing or invalid date') from None
        if not start <= day <= end:
            continue
        if transaction.get('target') != 'INITIAL' or 'transferDirection' in transaction or '__plaidTx' not in transaction:
            raise ClientError('Historical creation with reviewed, manual or transfer entries has not been established')
        try:
            amount = money(transaction['__plaidTx']['amount'])
        except (KeyError, TypeError):
            raise ClientError('A bank-linked transaction is missing its signed bank amount') from None
        if amount > 0:
            summary += amount
    return {
        'startDate': start.isoformat(), 'endDate': end.isoformat(),
        'allowanceAmount': float(allowance), 'spentAmount': 0,
        'endingBalance': float(allowance),
        'spendingSummary': {'INITIAL': float(money(summary))} if summary else {},
        'rolloverAmount': 0, 'rolloverEnabled': False, 'rolloverOption': 'ignore',
        'currentPlan': plan.strip(), 'showPastWeekTxsForReview': False,
        'weekCreationType': 'historical',
    }


def create(config, start_date, end_date, spending_limit, dry_run=False):
    _, end = week_dates(start_date, end_date, [])
    money(spending_limit)
    preferences = user_preferences(config)
    try:
        today = datetime.now(ZoneInfo(preferences['timezone'])).date()
    except (KeyError, TypeError, ZoneInfoNotFoundError):
        raise ClientError('Provide a valid saved account timezone') from None
    require_completed_week(end, today)
    existing_weeks = list_documents(config, 'weekInstances')
    plan = current_week(config, preferences, existing_weeks).get('currentPlan')
    record = historical_week(start_date, end_date, spending_limit, plan,
                             existing_weeks,
                             list_documents(config, 'transactions'), today)
    if dry_run:
        return {'dry_run': True, 'collection': 'weekInstances', 'fields': record}
    return create_document(config, 'weekInstances', record)


def delete(config, week_id, dry_run=False, yes=False):
    if dry_run and yes:
        raise ClientError('Use either --dry-run or --yes, not both')
    if not dry_run and not yes:
        raise ClientError('Refusing to delete week without --yes or --dry-run')
    if not week_id or '/' in week_id or week_id in ('.', '..'):
        raise ClientError('Invalid week ID')
    http, user_url, headers, data = firestore_context(config)
    url = user_url + '/weekInstances/' + quote(week_id, safe='')
    try:
        response = http.get(url, headers=headers, timeout=30, allow_redirects=False)
        if response.status_code == 404:
            raise ClientError('Week not found')
        if response.status_code != 200:
            raise ClientError(f'Weekly week read failed (HTTP {response.status_code})')
        doc = response.json()
        expected = USER_DOCUMENT_ROOT + data['user_id'] + '/weekInstances/' + week_id
        if not isinstance(doc, dict) or doc.get('name') != expected or not isinstance(doc.get('fields'), dict):
            raise ClientError('Weekly week has an unexpected identity or fields')
        version = doc.get('updateTime')
        if not isinstance(version, str) or datetime.fromisoformat(version.replace('Z', '+00:00')).utcoffset() is None:
            raise ValueError
        record = {key: decode_value(value) for key, value in doc['fields'].items()}
        start = datetime.fromisoformat(record['startDate'].replace('Z', '+00:00')).date()
        end = datetime.fromisoformat(record['endDate'].replace('Z', '+00:00')).date()
        today = datetime.now(ZoneInfo(user_preferences(config)['timezone'])).date()
    except requests.RequestException:
        raise ClientError('Weekly week read failed') from None
    except (KeyError, TypeError, ValueError, AttributeError, ZoneInfoNotFoundError):
        raise ClientError('Week dates, version or account timezone are missing or invalid') from None
    is_current = start <= today <= end
    preview = {'id': week_id, 'startDate': record['startDate'], 'endDate': record['endDate'],
               'is_current': is_current,
               'effect': 'Removes this week budget record. The CLI does not delete transactions or fund contributions, or recalculate later rollover balances.'}
    if 'allowanceAmount' in record:
        preview['allowanceAmount'] = record['allowanceAmount']
    if is_current:
        preview['current_week_effect'] = 'Current-budget and unreviewed-transaction commands will have no current week until one covering today exists.'
    if dry_run:
        return {'dry_run': True, **preview}
    uncertain = f'Week deletion outcome uncertain; inspect week {week_id} before retrying'
    try:
        result = http.delete(url, headers=headers, params={'currentDocument.updateTime': version}, timeout=30, allow_redirects=False)
        if result.status_code == 408 or result.status_code >= 500:
            raise ClientError(uncertain)
        if not 200 <= result.status_code < 300:
            raise ClientError(f'Weekly week deletion failed (HTTP {result.status_code})')
        if http.get(url, headers=headers, timeout=30, allow_redirects=False).status_code != 404:
            raise ClientError(uncertain)
    except requests.RequestException:
        raise ClientError(uncertain) from None
    return {'deleted': True, **preview}
