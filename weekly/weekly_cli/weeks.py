"""Create completed historical weeks using the observed native record shape."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cli_tools_shared.exceptions import ClientError
from .firestore import create_document, current_week, list_documents, user_preferences


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
