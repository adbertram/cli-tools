"""Create recurring items with native Weekly configuration values."""
from datetime import date

from cli_tools_shared.exceptions import ClientError
from .firestore import create_document
from .weeks import money


# Identifiers observed in native Weekly saved records.
INTERVALS = (
    'weekly', 'biweekly', 'every3weeks', 'every4weeks', 'every5weeks',
    'every6weeks', 'every7weeks', 'every8weeks', 'every10weeks', 'bimonthly',
    'monthly', 'two_months', 'quarterly', 'every4months', 'every5months',
    'biannually', 'every7months', 'annually', 'every2years',
)
CATEGORIES = (
    'utilities', 'donations', 'education', 'health', 'housing', 'income',
    'kids', 'loan', 'medical', 'uncategorized', 'pets', 'savings',
    'subscriptions', 'taxes', 'transportation',
)
EMOJI_COLORS = ('red', 'orange', 'yellow', 'green', 'blue', 'purple', 'gray')
KINDS = {'expense': 'warning', 'income': 'success'}


def bill_fields(title, amount, interval, category, emoji, emoji_color,
                kind='expense', next_date=None, hide_from_reports=False, archived=False):
    values = {'title': title, 'interval': interval, 'category': category,
              'emoji': emoji, 'emojiColor': emoji_color, 'kind': kind}
    if any(not isinstance(value, str) or not value.strip() for value in values.values()):
        raise ClientError('Bill title, interval, category, emoji, emoji color and kind must not be empty')
    values = {key: value.strip() for key, value in values.items()}
    for key, choices in (('interval', INTERVALS), ('category', CATEGORIES),
                         ('emojiColor', EMOJI_COLORS), ('kind', KINDS)):
        if values[key] not in choices:
            raise ClientError(f'Unsupported bill {key}: {values[key]}. Values: {", ".join(choices)}')
    numeric = money(amount)
    if numeric <= 0:
        raise ClientError('Bill amount must be positive')
    record = {key: value for key, value in values.items() if key != 'kind'}
    record.update(amount=float(numeric), color=KINDS[values['kind']])
    if next_date is not None:
        try:
            day = date.fromisoformat(next_date)
            if day.isoformat() != next_date:
                raise ValueError
        except (ValueError, TypeError):
            raise ClientError('Next transaction date must be YYYY-MM-DD') from None
        record.update(nextTransactionDateOverride=day.isoformat(),
                      nextTransactionDateStored=day.isoformat())
    if hide_from_reports:
        record['excludeFromReports'] = True
    if archived:
        record['archived'] = True
    return record


def create(config, title, amount, interval, category, emoji, emoji_color,
           kind='expense', next_date=None, dry_run=False, hide_from_reports=False, archived=False):
    record = bill_fields(title, amount, interval, category, emoji, emoji_color,
                         kind, next_date, hide_from_reports, archived)
    if dry_run:
        return {'dry_run': True, 'collection': 'items', 'fields': record}
    return create_document(config, 'items', record)
