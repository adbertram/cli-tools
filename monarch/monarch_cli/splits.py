"""Exact-cent item allocation for transaction splits (no service access)."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENT = Decimal('0.01')


def money(value):
    if isinstance(value, bool):
        raise ValueError('money must be a decimal amount')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('money must be a decimal amount') from None
    if not result.is_finite() or result != result.quantize(CENT):
        raise ValueError('money must be finite and have at most two decimal places')
    return result


def allocate_items(items, amount):
    """Allocate the original total by extended item-price weight; last gets remainder."""
    total = money(amount)
    if not total:
        raise ValueError('original amount must be nonzero')
    if not isinstance(items, list) or len(items) < 2:
        raise ValueError('at least two priced items are required')
    prices = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('each item must be an object')
        if item.get('item_price') is None:
            raise ValueError('missing item_price: needs-input; do not split')
        price = money(item['item_price'])
        if price < 0:
            raise ValueError('item_price cannot be negative')
        if not all(isinstance(item.get(k), str) and item[k].strip() for k in ('category_id', 'category', 'notes')):
            raise ValueError('every item requires category_id, category and notes')
        prices.append(price)
    subtotal = sum(prices)
    if subtotal <= 0:
        raise ValueError('item-price subtotal must be positive')
    allocated = Decimal(0)
    result = []
    sign = Decimal(-1) if total < 0 else Decimal(1)
    for index, (item, price) in enumerate(zip(items, prices)):
        value = (abs(total) * price / subtotal).quantize(CENT, rounding=ROUND_HALF_UP) * sign if index < len(items)-1 else total - allocated
        if value * sign < 0:
            raise ValueError('rounding produced a negative last item; needs-input')
        if item.get('amount') is not None and money(item['amount']) != value:
            raise ValueError('stored item amount differs from weighted allocation')
        allocated += value
        result.append({**item, 'item_price': str(price.quantize(CENT)), 'amount': str(value.quantize(CENT))})
    return result


def validate_split_categories(items, category_id_by_name):
    """Require prepared category evidence for every proposed child."""
    if not isinstance(category_id_by_name, dict) or not category_id_by_name:
        raise ValueError('split decisions require category_id_by_name from prepared categories')
    for item in items:
        if str(category_id_by_name.get(item['category'])) != item['category_id']:
            raise ValueError('split category name/id does not match prepared categories')


def validate_split_decision(row, category_id_by_name):
    """Validate the same approved item proposal for preview and application."""
    splits = row.get('splits')
    if not isinstance(splits, list) or any(not isinstance(item, dict) or 'amount' not in item for item in splits):
        raise ValueError('each proposed split must include its allocated amount')
    items = allocate_items(splits, row['amount'])
    validate_split_categories(items, category_id_by_name)
    if row.get('suggested_category') != 'Split by item':
        raise ValueError('split rows require suggested_category=Split by item')
    if row.get('needs_input') is not False or row.get('rule_command') or row.get('recommended_rule') != 'Apply once — suppressed: multi-category merchant':
        raise ValueError('split rows must be resolved, apply-once, with no merchant rule')
    return items
