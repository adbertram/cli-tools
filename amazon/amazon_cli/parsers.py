"""Normalize observed Amazon order-detail evidence without inventing prices."""
from decimal import Decimal, InvalidOperation
import re
from cli_tools_shared.exceptions import ClientError


def _money(value):
    if not isinstance(value, str) or not re.fullmatch(r'-?\$?\d[\d,]*\.\d{2}', value.strip()):
        return None
    try:
        return Decimal(value.strip().replace('$', '').replace(',', ''))
    except InvalidOperation:
        return None


def normalize_item_detail(raw: dict) -> dict:
    """Parse only purchased-item containers and the order's own summary."""
    if not isinstance(raw, dict) or not isinstance(raw.get('items'), list):
        raise ClientError('Amazon order detail could not be read.')
    if not isinstance(raw.get('order_id'), str) or not isinstance(raw.get('summary'), str):
        raise ClientError('Amazon order detail is missing its order ID or summary.')
    order_id = raw['order_id'].strip()
    if not re.fullmatch(r'\d{3}-\d{7}-\d{7}', order_id):
        raise ClientError('Amazon order detail did not identify an order.')
    summary_lines = [x.strip() for x in raw.get('summary', '').splitlines() if x.strip()]
    summary = []
    for i, label in enumerate(summary_lines[:-1]):
        amount = _money(summary_lines[i + 1])
        if label.endswith(':') and amount is not None:
            summary.append({'label': label.rstrip(':'), 'amount': str(amount)})
    def amount_for(label):
        return next((x['amount'] for x in summary if x['label'] == label), None)
    items = []
    for item in raw['items']:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not isinstance(item.get('quantity', ''), str):
            raise ClientError('Amazon purchased item could not be read.')
        name = item.get('name', '').strip()
        if not name:
            raise ClientError('Amazon purchased item is missing its title.')
        # Amazon leaves the quantity component blank for a single unit.
        quantity_text = item.get('quantity', '').strip()
        match = re.fullmatch(r'(?:Qty:?\s*|Quantity:?\s*)?(\d+)', quantity_text)
        quantity = 1 if not quantity_text else None
        if match:
            quantity = int(match.group(1))
        unit_price = _money(item.get('unit_price'))
        price = unit_price * quantity if unit_price is not None and quantity else None
        items.append({'name': name, 'quantity': quantity,
                      'unit_price': str(unit_price) if unit_price is not None else None,
                      'item_price': str(price) if price is not None else None})
    subtotal = amount_for('Item(s) Subtotal')
    complete = bool(items) and all(x['item_price'] is not None for x in items)
    if complete:
        complete = subtotal is not None and sum(
            Decimal(x['item_price']) for x in items
        ) == Decimal(subtotal)
    return {'order_id': order_id, 'order_date': raw.get('order_date', '').strip(),
            'url': raw.get('url'), 'items': items, 'item_subtotal': subtotal,
            'total': amount_for('Grand Total'), 'summary': summary,
            'item_prices_complete': complete,
            'split_blocker': None if complete else 'Missing item prices/quantities or item subtotal does not reconcile; needs-input, never fabricate prices.'}
